"""Offline, single-instance scheduling policy for Caravansary coverage cells."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from heapq import nsmallest
import math


_SECOND = 1_000_000
_HOUR = 3600 * _SECOND
_ELIGIBLE = ("pending", "priced", "unavailable", "failed")


def _integer(value, name, *, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _instant(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("expected an aware datetime")
    utc = value.astimezone(timezone.utc)
    # An exact integer clock avoids floating-point boundary errors and permits
    # duration arithmetic even when a deadline exceeds datetime's year range.
    return (((utc.toordinal() * 24 + utc.hour) * 60 + utc.minute) * 60
            + utc.second) * _SECOND + utc.microsecond


def _timestamp(value):
    if value is None:
        return 0  # Earlier than any valid datetime.
    if not isinstance(value, str):
        raise ValueError("expected a coverage RFC 3339 timestamp or null")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return _instant(datetime.fromisoformat(value))


def _receipt(record):
    return 0 if record is None else _timestamp(record["received_at"])


@dataclass(slots=True)
class _Source:
    budget: int
    concurrency: int
    attempts: deque = field(default_factory=deque)
    active: int = 0
    fairness_position: int = 0


@dataclass(slots=True)
class _Cell:
    last_attempt: int = 0
    last_success: int = 0
    not_before: int = 0
    retries: int = 0
    backoff: int = 0
    active: bool = False


class Scheduler:
    """Reserve work from validated planner or coverage rows; never execute it.

    A reservation counts as one attempt immediately, including retries and
    reservations that are never used. The budget window is (now - 1h, now].
    This is in-memory policy for one instance, called serially by one host;
    it has no restart/shared-state guarantees. It models immediate dispatch,
    one request per reservation, no batching, and no pagination. A real host
    must enforce limits at the actual time requests are sent.
    """

    def __init__(self, refresh, sources, *, minimum_service_every=4, max_retries=2,
                 backoff_initial_seconds=30, backoff_max_seconds=3600):
        self._tick = _integer(refresh.get("tick_seconds"), "tick_seconds")
        self._age = _integer(refresh.get("max_age_seconds"), "max_age_seconds")
        self._minimum = _integer(minimum_service_every, "minimum_service_every")
        self._max_retries = _integer(max_retries, "max_retries", minimum=0)
        self._backoff_initial = _integer(backoff_initial_seconds, "backoff_initial_seconds")
        self._backoff_max = _integer(
            backoff_max_seconds, "backoff_max_seconds", minimum=self._backoff_initial
        )
        self._sources = {}
        for name in sources:
            if name not in ("booking", "agoda") or name in self._sources:
                raise ValueError(f"invalid or duplicate source: {name!r}")
            budget = f"{name}_requests_per_hour"
            concurrency = f"{name}_concurrency"
            self._sources[name] = _Source(_integer(refresh.get(budget), budget),
                                          _integer(refresh.get(concurrency), concurrency))
        if not self._sources:
            raise ValueError("at least one source is required")
        self._cells = {}
        self._active = {}
        self._next_id = 1
        self._last_tick = None
        self._clock = 0

    def _time(self, now):
        instant = _instant(now)
        if instant < self._clock:
            raise ValueError("scheduler clock cannot move backwards")
        return instant

    def _rows(self, rows):
        seen = set()
        for row in rows:
            name = row["source"]
            if name not in self._sources:
                continue
            key, status = row["cell_key"], row["status"]
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError(f"invalid or duplicate scheduler cell key: {key!r}")
            seen.add(key)
            if status != "unsupported" and status not in _ELIGIBLE:
                raise ValueError(f"invalid scheduler status: {status!r}")
            yield name, key, status, row

    def capacity(self, rows):
        """Return per-source *necessary*, not sufficient, capacity conditions.

        Count every eligible cell, including zero weights. Assume sustained
        full passes with instant successful results, one request per cell and
        every free slot used. Ignore initial fill, retries, and other overhead.
        """
        eligible = dict.fromkeys(self._sources, 0)
        unsupported = dict.fromkeys(self._sources, 0)
        for name, _, status, _ in self._rows(rows):
            counts = unsupported if status == "unsupported" else eligible
            counts[name] += 1
        result = {}
        for name, source in self._sources.items():
            count = eligible[name]
            slots = min(source.budget, source.concurrency)
            budget_ok = count * 3600 <= source.budget * self._age
            tick_ok = count == 0 or (
                self._tick <= self._age and count * self._tick <= slots * self._age
            )
            result[name] = {
                "eligible_cells": count,
                "unsupported_cells": unsupported[name],
                "attempts_per_full_pass": count,
                "required_attempts_per_hour": count * 3600 / self._age,
                "requests_per_hour": source.budget,
                "concurrency": source.concurrency,
                "max_attempts_per_tick": slots,
                "tick_seconds": self._tick,
                "max_age_seconds": self._age,
                "necessary_budget_condition_met": budget_ok,
                "necessary_tick_condition_met": tick_ok,
                "necessary_capacity_condition_met": budget_ok and tick_ok,
            }
        return result

    def schedule(self, coverage_rows, *, now):
        """Spend at most one tick and return shallow row copies with reservation_id.

        The first call starts a tick; subsequent ticks are at least tick_seconds
        apart, without catch-up bursts. Among due cells, ordinary slots use
        descending positive weight then earliest due. Every Nth reservation per
        source (N = minimum_service_every), and slots without positive-weight
        candidates, select the least recently served due cell regardless of
        weight. Count attempts as service for rotation so persistent failures
        do not monopolize those slots; break ties by oldest success, then key.
        """
        instant = self._time(now)
        if self._last_tick is not None and instant - self._last_tick < self._tick * _SECOND:
            self._clock = instant
            return []

        slots = {}
        expired = {}
        for name, source in self._sources.items():
            expired[name] = 0
            for attempt in source.attempts:
                if attempt > instant - _HOUR:
                    break
                expired[name] += 1
            slots[name] = min(source.concurrency - source.active,
                              source.budget - len(source.attempts) + expired[name])
        candidates = {name: [] for name in self._sources}
        if any(slots.values()):
            for name, key, status, row in self._rows(coverage_rows):
                if status == "unsupported" or not slots[name]:
                    continue
                state = self._cells.get(key)
                if state is not None and (state.active or state.not_before > instant):
                    continue
                success = _receipt(row.get("latest_success"))
                last_attempt = _receipt(row.get("latest_attempt"))
                if state is not None:
                    success = max(success, state.last_success)
                    last_attempt = max(last_attempt, state.last_attempt)
                due = _timestamp(row.get("next_due_at"))
                if success:
                    due = max(due, success + self._age * _SECOND)
                if due > instant:
                    continue
                weight = row["weight"]
                if (type(weight) not in (int, float) or weight < 0
                        or (type(weight) is float and not math.isfinite(weight))):
                    raise ValueError(f"invalid scheduler weight for {key!r}")
                candidates[name].append((weight, due, max(last_attempt, success),
                                         success, key, row))

        self._clock = self._last_tick = instant
        reservations = []
        for name, source in self._sources.items():
            for _ in range(expired[name]):
                source.attempts.popleft()
            due_rows = candidates[name]
            limit = min(slots[name], len(due_rows))
            least_served = iter(nsmallest(limit, due_rows, key=lambda item: item[2:5]))
            weighted = iter(nsmallest(
                limit,
                (item for item in due_rows if item[0] > 0),
                key=lambda item: (-item[0], item[1], *item[2:5]),
            ))
            selected = set()
            for _ in range(limit):
                source.fairness_position = (source.fairness_position + 1) % self._minimum
                choice = None
                if source.fairness_position:
                    choice = next((item for item in weighted if item[4] not in selected), None)
                if choice is None:
                    choice = next(item for item in least_served if item[4] not in selected)
                key, row = choice[4:]
                selected.add(key)
                state = self._cells.setdefault(key, _Cell())
                state.active = True
                state.last_attempt = instant
                source.active += 1
                source.attempts.append(instant)
                reservation_id = self._next_id
                self._next_id += 1
                self._active[reservation_id] = (name, key)
                reservations.append({**row, "reservation_id": reservation_id})
        return reservations

    def finish(self, reservation_id, *, now, success, retryable=True):
        """Release an active reservation without refunding its hourly attempt.

        success means a complete authoritative observation; the cell is then
        locally due no earlier than now + max_age_seconds, even if the host
        has not folded the result into coverage yet. A retryable failure allows
        up to max_retries extra attempts with capped exponential backoff;
        retries are scheduled normally and still cost budget. Exhaustion or a
        nonretryable failure ends the chain and defers normal service at least
        max_age_seconds. Unknown or already finished IDs raise ValueError.
        """
        instant = self._time(now)
        if type(reservation_id) is not int or reservation_id not in self._active:
            raise ValueError(f"unknown or finished reservation: {reservation_id!r}")
        if type(success) is not bool or type(retryable) is not bool:
            raise ValueError("success and retryable must be booleans")
        name, key = self._active.pop(reservation_id)
        self._sources[name].active -= 1
        state = self._cells[key]
        state.active = False
        self._clock = instant

        delay = self._age
        if success:
            state.last_success = instant
        elif retryable and state.retries < self._max_retries:
            state.retries += 1
            state.backoff = (min(2 * state.backoff, self._backoff_max)
                             if state.backoff else self._backoff_initial)
            state.not_before = instant + state.backoff * _SECOND
            return
        elif state.backoff:
            delay = max(delay, state.backoff)
        state.retries = state.backoff = 0
        state.not_before = instant + delay * _SECOND
