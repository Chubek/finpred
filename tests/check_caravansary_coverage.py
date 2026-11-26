#!/usr/bin/env python3
"""Focused, offline tests of Caravansary's coverage fold."""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "caravansary"))
from caravansary_core.coverage import coverage


def _time(hms):
    return f"2026-11-26T{hms}Z"


class CoverageTest(unittest.TestCase):
    def setUp(self):
        guest = {
            "id": "one", "rooms": 1, "adults": 1, "child_ages": [],
            "allocation": [{"adults": 1, "child_ages": []}],
        }
        self.context = {
            "source": "booking", "checkin": "2026-12-01", "checkout": "2026-12-03",
            "guest_configuration": guest, "booker_country": "FR", "locale": "fr-FR",
            "currency": "EUR",
        }
        self.row = {
            "cell_key": "a" * 64, "config_id": "b" * 64, "source": "booking",
            "competitor_id": "example", "checkin": self.context["checkin"],
            "checkout": self.context["checkout"], "guest_configuration": guest,
            "stay_length": 2, "request_context": self.context, "provider_property_id": "123",
            "provider_url": None, "status": "pending", "reason": None, "weight": 1,
        }
        self.offer = {
            "room_name": "Double", "rate_plan": "Flex", "meal": "none",
            "cancellation": None, "cancellation_reason": "not_disclosed",
            "allocation": deepcopy(guest["allocation"]), "currency": "EUR",
            "availability": "available", "amount_decimal": "132.40",
            "price_basis": "stay_total", "taxes_fees": {"inclusion": "included", "components": []},
        }

    def record(self, ident="quote", **changes):
        record = {
            "kind": "caravansary.observation@1", "observation_id": ident,
            "cell_key": self.row["cell_key"], "provider_property_id": "123",
            "request_context": deepcopy(self.context), "complete": True,
            "received_at": _time("10:00:00"), "ingested_at": _time("10:00:30"),
            "adapter_version": "test", "extractor_version": "test",
            "outcome": "priced", "offers": [deepcopy(self.offer)],
        }
        return dict(record, **changes)

    def fold(self, *observations, clock="10:10:00"):
        now = datetime.fromisoformat(_time(clock).replace("Z", "+00:00"))
        return coverage([self.row], observations, now=now, max_age_seconds=600)

    def test_receipt_order_and_failure_preserve_success(self):
        quote = self.record(observed_at="2026-11-26T09:05:00+00:00")
        late_older = self.record("older", received_at=_time("09:10:00"),
                                 ingested_at=_time("10:04:00"))
        failure = self.record("failure", complete=False, outcome="failed", reason="transport_error",
                              offers=[], received_at=_time("10:01:00"),
                              ingested_at=_time("10:02:00"))
        for records in ((failure, late_older, quote), (quote, late_older, failure)):
            report = self.fold(*records)
            cell = report["cells"][0]
            self.assertEqual(cell["status"], "failed")
            self.assertEqual(cell["freshness"], "stale")
            self.assertEqual(cell["reason"], "transport_error")
            self.assertEqual(cell["latest_attempt"]["observation_id"], "failure")
            self.assertEqual(cell["latest_success"]["observation_id"], "quote")
            self.assertEqual(cell["latest_success"]["observed_at"], _time("09:05:00"))
            self.assertEqual(cell["latest_success"]["offers"][0]["amount_decimal"], "132.40")
            self.assertEqual(cell["next_due_at"], _time("10:10:00"))
            self.assertEqual(report["counts_by_status"]["failed"], 1)
            self.assertEqual(report["counts_by_freshness"]["stale"], 1)
        cell = self.fold(quote, failure, clock="10:09:59")["cells"][0]
        self.assertEqual((cell["status"], cell["freshness"]), ("failed", "fresh"))

    def test_as_of_ingestion_and_tie_breaks(self):
        unavailable = self.record("unavailable", outcome="unavailable", authoritative=True, offers=[])
        delayed = self.record("delayed", ingested_at=_time("10:05:00"))
        tie = self.record("z-tie", complete=False, outcome="failed", reason="partial_response",
                          offers=[], ingested_at=_time("10:05:00"))
        cell = self.fold(tie, delayed, unavailable, clock="10:01:00")["cells"][0]
        self.assertEqual((cell["status"], cell["freshness"]), ("unavailable", "fresh"))
        cell = self.fold(tie, delayed, unavailable)["cells"][0]
        self.assertEqual(cell["latest_attempt"]["observation_id"], "z-tie")
        self.assertEqual(cell["latest_success"]["observation_id"], "delayed")

    def test_partial_and_empty_are_not_unavailable(self):
        cell = self.fold(self.record(complete=False))["cells"][0]
        self.assertEqual((cell["status"], cell["freshness"]), ("priced", "none"))
        self.assertIsNone(cell["latest_success"])
        for record in (
            self.record(offers=[]),
            self.record(outcome="unavailable", offers=[]),
            self.record(outcome="unavailable", authoritative=True, offers=[], complete=False),
            self.record(outcome="unavailable", authoritative=True),
        ):
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.fold(record)

    def test_exact_cell_and_timestamps_are_validated(self):
        context = deepcopy(self.context)
        context["guest_configuration"]["allocation"][0]["adults"] = True
        for record in (
            self.record(cell_key="wrong"),
            self.record(provider_property_id="wrong"),
            self.record(request_context=context),
            self.record(observed_at=_time("10:00:01")),
            self.record(received_at=_time("10:00:31")),
            self.record(received_at="2026-11-26T12:00:00+02:00"),
        ):
            with self.subTest(record=record), self.assertRaises(ValueError):
                self.fold(record)
        with self.assertRaisesRegex(ValueError, "duplicate observation_id"):
            self.fold(self.record(), self.record())

    def test_offer_fields_and_itemized_stay(self):
        itemized = dict(self.offer, price_basis="nightly_itemized", nightly_itemized=[
            {"date": "2026-12-01", "amount_minor": 5500},
            {"date": "2026-12-02", "amount_decimal": "77.40"},
        ])
        del itemized["amount_decimal"]
        self.assertEqual(self.fold(self.record(offers=[itemized]))["cells"][0]["status"], "priced")
        for bad_offer in (
            dict(itemized, nightly_itemized=itemized["nightly_itemized"][:1]),
            dict(itemized, nightly_itemized=itemized["nightly_itemized"][::-1]),
            dict(self.offer, currency="USD"),
            dict(self.offer, amount_decimal=132.40),
            dict(self.offer, availability="unknown"),
            dict(self.offer, price_basis="unknown"),
        ):
            with self.subTest(offer=bad_offer), self.assertRaises(ValueError):
                self.fold(self.record(offers=[bad_offer]))

    def test_unobserved_and_unsupported_cells(self):
        pending = self.fold()["cells"][0]
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(pending["next_due_at"], _time("10:10:00"))
        self.row.update(status="unsupported", reason="mapping_missing", provider_property_id=None)
        unsupported = self.fold()["cells"][0]
        self.assertEqual(unsupported["reason"], "mapping_missing")
        self.assertEqual(unsupported["freshness"], "none")
        self.assertIsNone(unsupported["next_due_at"])
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.fold(self.record())


if __name__ == "__main__":
    unittest.main()
