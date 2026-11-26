#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "caravansary"))

from caravansary_core.scheduler import Scheduler


START = datetime(2026, 11, 26, tzinfo=timezone.utc)


def clock(seconds):
    return START + timedelta(seconds=seconds)


def row(key, *, source="booking", weight=1, status="pending", **extra):
    return {"cell_key": key, "source": source, "status": status, "weight": weight, **extra}


def policy(*, tick=1, age=10, budget=100, concurrency=1, sources=("booking",), **kwargs):
    return Scheduler({
        "tick_seconds": tick,
        "max_age_seconds": age,
        "booking_requests_per_hour": budget,
        "booking_concurrency": concurrency,
        "agoda_requests_per_hour": 1,
        "agoda_concurrency": 1,
    }, sources, **kwargs)


class CheckScheduler(unittest.TestCase):
    def test_trailing_hour_concurrency_and_per_source_limits(self):
        scheduler = policy(tick=5, budget=2, sources=("booking", "agoda"))
        rows = [row("x"), row("y"), row("z", source="agoda")]
        first = scheduler.schedule(rows, now=clock(0))
        self.assertEqual([item["cell_key"] for item in first], ["x", "z"])
        self.assertNotIn("reservation_id", rows[0])
        self.assertEqual(scheduler.schedule(rows, now=clock(5)), [])
        scheduler.finish(first[0]["reservation_id"], now=clock(5), success=True)
        self.assertEqual(scheduler.schedule(rows, now=clock(9)), [])
        second, = scheduler.schedule(rows, now=clock(10))
        self.assertEqual(second["cell_key"], "y")
        scheduler.finish(second["reservation_id"], now=clock(10), success=False)
        self.assertEqual(scheduler.schedule(rows, now=clock(3595)), [])
        third, = scheduler.schedule(rows, now=clock(3600))
        self.assertEqual(third["cell_key"], "y")
        # Agoda's older reservation still occupies its sole concurrency slot.
        self.assertEqual(scheduler.schedule(rows, now=clock(3610)), [])

    def test_microsecond_window_and_validation_does_not_refund(self):
        scheduler = policy(budget=1)
        first, = scheduler.schedule([row("x")], now=clock(0))
        scheduler.finish(first["reservation_id"], now=clock(0), success=True)
        with self.assertRaises(ValueError):
            scheduler.schedule([row("y", weight=float("inf"))], now=clock(3600))
        self.assertEqual(scheduler.schedule([row("y")], now=clock(1)), [])
        wait = clock(3600) - timedelta(microseconds=1)
        self.assertEqual(scheduler.schedule([row("y")], now=wait), [])
        reservation, = scheduler.schedule([row("y")], now=wait + timedelta(seconds=1))
        self.assertNotEqual(first["reservation_id"], reservation["reservation_id"])
        with self.assertRaises(ValueError):
            scheduler.finish(first["reservation_id"], now=clock(3601), success=False)
        with self.assertRaises(ValueError):
            scheduler.schedule([], now=clock(3000))
        with self.assertRaises(ValueError):
            scheduler.schedule([], now=START.replace(tzinfo=None))

    def test_fairness_spends_every_nth_slot_even_with_positive_work(self):
        scheduler = policy(age=1, minimum_service_every=3)
        rows = [
            row("unknown", source="agoda", weight=1000),
            row("unsupported", weight=1000, status="unsupported"),
            row("future", weight=1000, next_due_at=clock(100).isoformat()),
            row("low", weight=0),
            row("high", weight=10),
        ]
        for second, expected in enumerate(("high", "high", "low") * 2):
            reserved, = scheduler.schedule(reversed(rows), now=clock(second))
            self.assertEqual(reserved["cell_key"], expected)
            scheduler.finish(reserved["reservation_id"], now=clock(second), success=True)

    def test_due_includes_latest_success_and_ties_are_deterministic(self):
        scheduler = policy(concurrency=2)
        rows = [
            row("c", next_due_at=clock(-1).isoformat()),
            row("x", weight=10, latest_success={"received_at": clock(-5).isoformat()}),
            row("b", next_due_at=clock(-2).isoformat()),
            row("a", next_due_at=clock(-2).isoformat()),
        ]
        self.assertEqual([item["cell_key"] for item in scheduler.schedule(rows, now=START)],
                         ["a", "b"])

    def test_capped_retry_then_returns_to_normal_service(self):
        scheduler = policy(max_retries=2, backoff_initial_seconds=2, backoff_max_seconds=3)
        rows = [row("x", status="failed")]
        for second, success, retryable in ((0, False, True), (2, False, True),
                                           (5, False, True), (15, False, False),
                                           (25, True, False)):
            reserved, = scheduler.schedule(rows, now=clock(second))
            scheduler.finish(reserved["reservation_id"], now=clock(second),
                             success=success, retryable=retryable)
            self.assertEqual(scheduler.schedule(rows, now=clock(second + 1)), [])

    def test_capacity_counts_zero_weights_and_distinguishes_tick_and_budget(self):
        rows = [row("a", weight=0), row("b"), row("c", status="unsupported")]
        report = policy(tick=20, age=30, budget=1000).capacity(iter(rows))["booking"]
        self.assertEqual(report["eligible_cells"], 2)
        self.assertEqual(report["unsupported_cells"], 1)
        self.assertEqual(report["required_attempts_per_hour"], 240)
        self.assertTrue(report["necessary_budget_condition_met"])
        self.assertFalse(report["necessary_tick_condition_met"])
        report = policy(age=1800, budget=2, sources=("booking", "agoda")).capacity(rows)
        self.assertFalse(report["booking"]["necessary_budget_condition_met"])
        self.assertTrue(report["agoda"]["necessary_capacity_condition_met"])


if __name__ == "__main__":
    unittest.main()
