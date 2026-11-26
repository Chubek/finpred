"""Validate decoded observations and fold them into offline matrix coverage.

Record contract (``caravansary.observation@1``; unknown fields are rejected):

- Required: ``kind``, unique nonempty ``observation_id``, ``cell_key``,
  ``provider_property_id``, ``received_at``, ``ingested_at``, nonempty
  ``adapter_version`` and ``extractor_version``, ``request_context``, boolean
  ``complete``, ``outcome``, and the list ``offers``. The cell must exist and
  be eligible, and the property ID and context must exactly match the
  planner's values (JSON types matter). A URL-only mapping uses the row's null
  ID; the cell key already binds the configured URL via the config identity.
- Optional ``observed_at`` is asserted only for a trustworthy provider clock.
  Explicit null for ``observed_at`` or ``provider_property_id`` requires a
  matching ``<field>_reason``. Times are RFC 3339 UTC (``Z`` or ``+00:00``,
  at most six fractional digits), with observed <= received <= ingested.
  Optional ``source_url``, ``capture_digest`` and ``capture_reference`` are
  nonempty strings allowed only when the caller has permission to retain them.
- ``priced`` requires a qualifying offer. Incomplete positive results can be
  ``priced`` but do not renew freshness. ``unavailable`` requires
  ``complete: true``, explicit ``authoritative: true``, and ``offers: []``.
  Empty or partial responses do not imply unavailable. ``failed`` requires
  ``complete: false`` and ``reason`` (a bounded lowercase ASCII reason code,
  e.g. ``transport_error`` or ``partial_response``); offers can be retained
  from partial results. Other outcomes have no reason (absent or null).
  ``authoritative`` is an optional boolean and is an adapter attestation,
  not an inference or independent provider verification.

Normalized offer contract (one object per rate/room allocation):

- Required: ``room_name``, ``rate_plan``, ``meal``, ``cancellation`` (strings
  or null with ``<field>_reason``), ``allocation`` (exact planner request room
  allocation), ``currency`` (exact requested currency), ``availability``
  (``available``, ``unavailable`` or ``unknown``), ``price_basis``
  (``stay_total``, ``nightly_average``, ``nightly_itemized`` or ``unknown``)
  and ``taxes_fees``.
- Supply one of ``amount_minor`` (nonnegative integer, not boolean) or
  ``amount_decimal`` (nonnegative exact decimal string without exponent).
  With ``nightly_itemized``, that top-level amount is optional and only for
  a separate provider-supplied amount. The required ``nightly_itemized`` list
  then holds ``{date, amount_minor|amount_decimal}`` pairs in increasing
  YYYY-MM-DD order within [checkin, checkout), only for reported nights.
  A qualifying offer is available, has a known price basis, and for itemized
  quotes includes all nights. Known availability with unknown price basis
  can be retained as evidence, but does not establish ``priced``.
- ``taxes_fees`` is ``{inclusion, components}``; each component is
  ``{name, inclusion, [amount_minor|amount_decimal]}`` in the offer currency.
  Inclusion states are ``included``, ``excluded``, ``mixed`` and ``unknown``.
  Optional nonempty strings: ``provider_offer_id``, ``provider_room_id``,
  ``source_text``, plus ``raw_value`` and ``raw_locale`` together if allowed.
  For a derived ``nightly_average`` include ``derived_average`` containing
  ``formula`` and ``rounding`` strings and an ``original_total`` object
  with one amount field in the offer currency. The module does no price
  arithmetic and cannot detect an undeclared derivation.

The caller supplies trusted planner rows and a log scoped to that exact
matrix. This module does not read files, determine provider authority,
or authorize collection, capture, storage, or historical retention.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import re


_OBSERVATION_KIND = "caravansary.observation@1"
_STATUSES = ("pending", "priced", "unavailable", "unsupported", "failed")
_FRESHNESS = ("fresh", "stale", "none")
_STAMP = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.([0-9]{1,6}))?(?:Z|\+00:00)"
)
_REASON = re.compile(r"[a-z][a-z0-9_]{0,47}")
_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_AMOUNT = {"amount_minor", "amount_decimal"}
_INCLUSION = ("included", "excluded", "mixed", "unknown")
_REQUIRED_RECORD = {
    "kind", "observation_id", "cell_key", "provider_property_id",
    "received_at", "ingested_at", "adapter_version", "extractor_version",
    "request_context", "complete", "outcome", "offers",
}
_OPTIONAL_RECORD = {
    "provider_property_id_reason", "observed_at", "observed_at_reason",
    "authoritative", "reason", "source_url", "capture_digest", "capture_reference",
}
_OFFER_DESCRIPTIONS = {"room_name", "rate_plan", "meal", "cancellation"}
_REQUIRED_OFFER = _OFFER_DESCRIPTIONS | {
    "allocation", "currency", "availability", "price_basis", "taxes_fees",
}
_OPTIONAL_OFFER_TEXT = {
    "provider_offer_id", "provider_room_id", "source_text", "raw_value", "raw_locale",
}
_OPTIONAL_OFFER = _AMOUNT | _OPTIONAL_OFFER_TEXT | {
    f"{field}_reason" for field in _OFFER_DESCRIPTIONS
} | {"nightly_itemized", "derived_average"}


def _object(value, required, optional, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if required - value.keys():
        missing = ", ".join(sorted(required - value.keys()))
        raise ValueError(f"{field} is missing {missing}")
    if value.keys() - required - optional:
        raise ValueError(f"{field} contains an unknown field")


def _list(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _reason(value, field):
    if not isinstance(value, str) or not _REASON.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase ASCII reason code (1–48 characters)")


def _null_reason(record, field):
    reason = f"{field}_reason"
    if field in record and record[field] is None:
        _reason(record.get(reason), reason)
    elif reason in record:
        raise ValueError(f"{reason} requires explicit null {field}")


def _timestamp(value, field):
    stamp = _STAMP.fullmatch(value) if isinstance(value, str) else None
    if stamp:
        try:
            seconds, fraction = stamp.groups()
            return datetime.fromisoformat(f"{seconds}.{(fraction or '').ljust(6, '0')}+00:00")
        except ValueError:
            pass
    raise ValueError(f"{field} must be an RFC 3339 UTC timestamp")


def _utc_text(value):
    return value.isoformat().replace("+00:00", "Z")


def _same_json(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys() and
                all(_same_json(actual[key], val) for key, val in expected.items()))
    if isinstance(expected, list):
        return (len(actual) == len(expected) and
                all(_same_json(a, b) for a, b in zip(actual, expected)))
    return actual == expected


def _amount(record, *, required):
    keys = _AMOUNT & record.keys()
    if not keys and not required:
        return
    if len(keys) != 1:
        raise ValueError("expected exactly one amount_minor or amount_decimal")
    if "amount_minor" in keys:
        value = record["amount_minor"]
        if type(value) is not int or value < 0:
            raise ValueError("amount_minor must be a nonnegative integer")
    else:
        value = record["amount_decimal"]
        if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
            raise ValueError("amount_decimal must be a nonnegative exact decimal string")


def _taxes_fees(charges):
    _object(charges, {"inclusion", "components"}, set(), "taxes_fees")
    if charges["inclusion"] not in _INCLUSION:
        raise ValueError("invalid taxes_fees inclusion state")
    for component in _list(charges["components"], "taxes_fees.components"):
        _object(component, {"name", "inclusion"}, _AMOUNT, "tax/fee component")
        _text(component["name"], "tax/fee component name")
        if component["inclusion"] not in _INCLUSION:
            raise ValueError("invalid tax/fee component inclusion state")
        _amount(component, required=False)


def _nightly(nights, context):
    nights = _list(nights, "nightly_itemized")
    if not nights:
        raise ValueError("nightly_itemized must contain reported nights")
    start, end = context["checkin"], context["checkout"]
    previous = ""
    for night in nights:
        _object(night, {"date"}, _AMOUNT, "nightly item")
        _amount(night, required=True)
        try:
            day = date.fromisoformat(night["date"])
        except (ValueError, TypeError):
            raise ValueError("nightly item date must be YYYY-MM-DD") from None
        stamp = day.isoformat()
        if stamp != night["date"] or not (start <= stamp < end and previous < stamp):
            raise ValueError("nightly item dates must be unique, ordered and within the stay")
        previous = stamp
    return len(nights) == (date.fromisoformat(end) - date.fromisoformat(start)).days


def _offer(offer, context):
    _object(offer, _REQUIRED_OFFER, _OPTIONAL_OFFER, "offer")
    for field in sorted(_OFFER_DESCRIPTIONS):
        _null_reason(offer, field)
        if offer[field] is not None:
            _text(offer[field], field)
    for field in sorted(_OPTIONAL_OFFER_TEXT & offer.keys()):
        _text(offer[field], field)
    if ("raw_value" in offer) != ("raw_locale" in offer):
        raise ValueError("raw_value and raw_locale must be supplied together")
    if not _same_json(offer["allocation"], context["guest_configuration"]["allocation"]):
        raise ValueError("offer allocation does not match the cell")
    if offer["currency"] != context["currency"]:
        raise ValueError("offer currency does not match the cell")
    if offer["availability"] not in ("available", "unavailable", "unknown"):
        raise ValueError("invalid offer availability")
    basis = offer["price_basis"]
    if basis not in ("stay_total", "nightly_average", "nightly_itemized", "unknown"):
        raise ValueError("invalid price_basis")
    _amount(offer, required=basis != "nightly_itemized")
    _taxes_fees(offer["taxes_fees"])
    known_price = basis != "unknown"
    if basis == "nightly_itemized":
        known_price = _nightly(offer.get("nightly_itemized"), context)
    elif "nightly_itemized" in offer:
        raise ValueError("nightly_itemized entries require nightly_itemized price_basis")
    if "derived_average" in offer:
        if basis != "nightly_average":
            raise ValueError("derived_average requires nightly_average price_basis")
        derived = offer["derived_average"]
        _object(derived, {"formula", "rounding", "original_total"}, set(), "derived_average")
        _text(derived["formula"], "formula")
        _text(derived["rounding"], "rounding")
        _object(derived["original_total"], set(), _AMOUNT, "original_total")
        _amount(derived["original_total"], required=True)
    return offer["availability"] == "available" and known_price


def _observation(record, rows):
    _object(record, _REQUIRED_RECORD, _OPTIONAL_RECORD, "observation")
    if record["kind"] != _OBSERVATION_KIND:
        raise ValueError(f"expected {_OBSERVATION_KIND} kind")
    key = _text(record["cell_key"], "cell_key")
    if key not in rows:
        raise ValueError("observation cell_key is not in the report matrix")
    row = rows[key]
    if row["status"] == "unsupported":
        raise ValueError("observations cannot target an unsupported cell")
    if not _same_json(record["provider_property_id"], row["provider_property_id"]):
        raise ValueError("provider_property_id does not match the cell")
    context = row["request_context"]
    if not _same_json(record["request_context"], context):
        raise ValueError("request_context does not match the exact cell")
    for field in ("observation_id", "adapter_version", "extractor_version"):
        _text(record[field], field)
    for field in ("source_url", "capture_digest", "capture_reference"):
        if field in record:
            _text(record[field], field)
    _null_reason(record, "provider_property_id")
    _null_reason(record, "observed_at")
    received = _timestamp(record["received_at"], "received_at")
    ingested = _timestamp(record["ingested_at"], "ingested_at")
    observed = (_timestamp(record["observed_at"], "observed_at")
                if record.get("observed_at") is not None else None)
    if received > ingested or (observed is not None and observed > received):
        raise ValueError("expected observed_at <= received_at <= ingested_at")
    complete = record["complete"]
    authoritative = record.get("authoritative", False)
    if type(complete) is not bool or type(authoritative) is not bool:
        raise ValueError("complete and authoritative must be booleans")
    result = record["outcome"]
    offers = _list(record["offers"], "offers")
    qualified = False
    for number, offer in enumerate(offers, 1):
        try:
            # Always validate all offers, even after finding a qualifying one.
            qualified = _offer(offer, context) or qualified
        except ValueError as exc:
            raise ValueError(f"offer {number}: {exc}") from exc
    if result == "priced":
        if not qualified:
            raise ValueError("priced requires at least one qualifying offer")
    elif result == "unavailable":
        if not complete or not authoritative or offers:
            raise ValueError("unavailable requires complete authority and no offers")
    elif result == "failed":
        if complete:
            raise ValueError("failed observations cannot be complete")
        _reason(record.get("reason"), "reason")
    else:
        raise ValueError("outcome must be priced, unavailable or failed")
    if result != "failed" and record.get("reason") is not None:
        raise ValueError("reason is reserved for failed observations")
    return (received, ingested, record["observation_id"]), observed


def _canonical(record, order, observed):
    normalized = deepcopy(record)
    normalized["received_at"] = _utc_text(order[0])
    normalized["ingested_at"] = _utc_text(order[1])
    if observed is not None:
        normalized["observed_at"] = _utc_text(observed)
    return normalized


def coverage(rows, observations, *, now, max_age_seconds, capacity=None):
    """Return a ``caravansary.coverage@1`` dict for iterable rows and records.

    ``now`` is an aware datetime; ``max_age_seconds`` is a positive integer.
    Invalid records raise ValueError (including duplicates and out-of-matrix
    keys). For an as-of report all records are validated, but only records
    ingested by ``now`` take effect. Compare eligible observations by receipt
    time, then ingestion time, then lexicographic observation ID, not by input
    order or provider clock. The latest attempt sets status; only complete
    priced/unavailable attempts count as successes.

    The report includes ``as_of``, ``max_age_seconds``, ``counts_by_status``,
    ``counts_by_freshness`` (both including zero counts), and ``capacity``
    verbatim if supplied. ``cells`` augments planner rows in their input
    order; nested planner fields remain read-only by convention. Cells report
    canonical ``latest_attempt`` and ``latest_success`` records or null and
    independent ``freshness``. A success expires at receipt + max age
    (stale at equality); this deadline is ``next_due_at`` even when overdue.
    Without success it is ``now`` for eligible cells or null if unsupported.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be an aware datetime")
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be a positive integer")
    try:
        now = now.astimezone(timezone.utc)
        max_age = timedelta(seconds=max_age_seconds)
    except OverflowError as exc:
        raise ValueError("now or max_age_seconds is outside supported bounds") from exc
    expected = {}
    for row in rows:
        key = _text(row["cell_key"], "planner cell_key")
        if key in expected:
            raise ValueError("duplicate planner cell_key")
        if row["status"] not in ("pending", "unsupported"):
            raise ValueError("planner rows must start pending or unsupported")
        expected[key] = row

    attempts, successes, seen = {}, {}, set()
    for number, record in enumerate(observations, 1):
        try:
            order, observed = _observation(record, expected)
            if order[2] in seen:
                raise ValueError("duplicate observation_id")
            seen.add(order[2])
        except ValueError as exc:
            raise ValueError(f"observation {number}: {exc}") from exc
        if order[1] > now:
            continue
        key = record["cell_key"]
        update_attempt = key not in attempts or attempts[key][0] < order
        update_success = record["complete"] and (key not in successes or successes[key][0] < order)
        if update_attempt or update_success:
            normalized = (order, _canonical(record, order, observed))
            if update_attempt:
                attempts[key] = normalized
            if update_success:
                successes[key] = normalized

    as_of = _utc_text(now)
    by_status = dict.fromkeys(_STATUSES, 0)
    by_freshness = dict.fromkeys(_FRESHNESS, 0)
    cells = []
    for key, row in expected.items():
        attempt = attempts[key][1] if key in attempts else None
        success = successes[key][1] if key in successes else None
        status = attempt["outcome"] if attempt else row["status"]
        reason = attempt.get("reason") if attempt else row["reason"]
        next_due = None if status == "unsupported" else as_of
        freshness = "none"
        if success:
            try:
                deadline = successes[key][0][0] + max_age
            except OverflowError as exc:
                raise ValueError("freshness deadline is outside the supported UTC calendar") from exc
            next_due = _utc_text(deadline)
            freshness = "fresh" if now < deadline else "stale"
        by_status[status] += 1
        by_freshness[freshness] += 1
        cells.append(dict(row, status=status, reason=reason, freshness=freshness,
                          latest_attempt=attempt, latest_success=success, next_due_at=next_due))
    result = {
        "kind": "caravansary.coverage@1", "as_of": as_of, "max_age_seconds": max_age_seconds,
        "counts_by_status": by_status, "counts_by_freshness": by_freshness, "cells": cells,
    }
    if capacity is not None:
        result["capacity"] = capacity
    return result
