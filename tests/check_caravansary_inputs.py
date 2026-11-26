#!/usr/bin/env python3
"""Offline tests for the v1 Caravansary input contracts."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/caravansary/examples"
SPEC = importlib.util.spec_from_file_location(
    "caravansary_inputs", ROOT / "plugins/caravansary/caravansary_core/inputs.py",
)
inputs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inputs)


class InputChecks(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name) / "input.json"

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")
        return self.path

    def test_examples(self):
        guests, properties = inputs.load_competitors(EXAMPLES / "riviera-comparables.json")
        self.assertEqual(guests["two_adults"]["allocation"], [{"adults": 2, "child_ages": []}])
        self.assertEqual(len(properties), 2)
        self.assertEqual(properties[1]["providers"]["booking"], {"mapping_status": "missing"})
        weights = inputs.load_weights(EXAMPLES / "riviera-weights.json", guests, [1, 2, 3])
        self.assertEqual(weights, {(guest, stay): 1 for guest in guests for stay in [1, 2, 3]})

    def test_room_allocations(self):
        party = {
            "id": "family", "rooms": 2, "adults": 3, "child_ages": [4, 4, 17],
            "allocation": [{"adults": 2, "child_ages": [17, 4]}, {"adults": 1, "child_ages": [4]}],
        }
        doc = {"kind": "caravansary.competitors@1", "guest_configurations": [party], "properties": []}
        self.assertEqual(inputs.load_competitors(self.write(doc))[0]["family"], party)
        for changes in (
            {"rooms": True}, {"adults": 2}, {"child_ages": [4, 17, 17]},
            {"child_ages": [4, 4, 18]}, {"child_ages": [False, 4, 17]},
            {"allocation": None}, {"allocation": party["allocation"][:1]},
            {"allocation": [{"adults": 0, "child_ages": [4]}, {"adults": 3, "child_ages": [17, 4]}]},
        ):
            with self.subTest(changes=changes):
                doc["guest_configurations"] = [{**party, **changes}]
                with self.assertRaises(ValueError):
                    inputs.load_competitors(self.write(doc))
        doc["guest_configurations"] = [{k: v for k, v in party.items() if k != "allocation"}]
        with self.assertRaises(ValueError):
            inputs.load_competitors(self.write(doc))
        doc["guest_configurations"] = [party, party]
        with self.assertRaises(ValueError):
            inputs.load_competitors(self.write(doc))

    def test_provider_mappings(self):
        mapping = {
            "mapping_status": "verified", "provider_property_id": "001",
            "url": "https://example.test/listing",
        }
        doc = {
            "kind": "caravansary.competitors@1", "guest_configurations": [],
            "properties": [
                {
                    "id": "a", "name": "Property", "type": "hotel", "latitude": "90.0",
                    "longitude": -180, "providers": {"booking": mapping},
                },
                {"id": "b", "name": "Similar property", "providers": {"agoda": mapping}},
                {"id": "c", "name": "Unmapped", "providers": {}},
            ],
        }
        self.assertEqual(inputs.load_competitors(self.write(doc))[1], doc["properties"])
        doc["properties"][1]["providers"]["booking"] = {**mapping, "mapping_status": "unverified"}
        self.assertEqual(inputs.load_competitors(self.write(doc))[1], doc["properties"])
        for invalid in (
            {"mapping_status": "verified"},
            {"mapping_status": "unverified"},
            {"mapping_status": "missing", "provider_property_id": "001"},
            {"mapping_status": "available", "provider_property_id": "002"},
            {"mapping_status": "verified", "provider_property_id": 2},
            {"mapping_status": "verified", "provider_property_id": "001"},
            {"mapping_status": "verified", "provider_property_id": "002", "url": mapping["url"]},
            {"mapping_status": "verified", "url": "https://user:pass@example.test/"},
            {"mapping_status": "verified", "url": "not a URL"},
        ):
            with self.subTest(mapping=invalid):
                doc["properties"][1]["providers"]["booking"] = invalid
                with self.assertRaises(ValueError):
                    inputs.load_competitors(self.write(doc))
        del doc["properties"][1]["providers"]["booking"]
        for changes in (
            {"id": "a"}, {"name": ""}, {"latitude": "90.001"}, {"longitude": True},
            {"providers": {"unknown": {"mapping_status": "missing"}}},
        ):
            with self.subTest(property=changes):
                candidate = copy.deepcopy(doc)
                candidate["properties"][1].update(changes)
                with self.assertRaises(ValueError):
                    inputs.load_competitors(self.write(candidate))

    def test_joint_weights(self):
        entry = {"guest_configuration": "a", "stay_length": 1, "weight": 0}
        other = {"guest_configuration": "a", "stay_length": 3, "weight": 0.25}
        doc = {
            "kind": "caravansary.weights@1", "mode": "joint", "source": "assumptions",
            "weights": [other, entry],
        }
        self.assertEqual(inputs.load_weights(self.write(doc), ["a"], [1, 3]), {("a", 1): 0, ("a", 3): 0.25})
        for changes in (
            {"weights": [other]}, {"weights": [entry, entry]}, {"mode": "marginal"},
            {"source": "   "}, {"default": 1}, {"weights": [entry, {**other, "weight": 0}]},
            *({"weights": [other, {**entry, **change}]} for change in (
                {"weight": True}, {"weight": "1"}, {"weight": -0.25}, {"weight": float("inf")},
                {"weight": float("nan")}, {"stay_length": True}, {"stay_length": 2},
                {"guest_configuration": "b"},
            )),
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    inputs.load_weights(self.write({**doc, **changes}), ["a"], [1, 3])
        doc["weights"][0] = {**other, "weight": 10**400}
        self.assertEqual(inputs.load_weights(self.write(doc), ["a"], [1, 3])[("a", 3)], 10**400)

    def test_strict_file_reader(self):
        self.assertEqual(inputs.parse_json(r'{"symbol": "\ud83d\ude00"}'), {"symbol": "😀"})
        for invalid in (
            b'{"kind": 1, "kind": 2}', br'{"x": {"z": 1, "\u007a": 2}}',
            b'{"weight": NaN}', b'{"weight": -Infinity}', b'{"weight": 1e999}',
            b'{"weight": -1e-999}', b'{"weight": 1e-999}', b'{} {}',
            b'\xff', br'{"name": "\ud800"}',
        ):
            with self.subTest(raw=invalid):
                self.path.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    inputs.load_competitors(self.path)
                # Syntactically invalid JSON must fail before schema validation.
                if invalid != b"\xff":
                    with self.assertRaises(ValueError):
                        inputs.parse_json(invalid.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
