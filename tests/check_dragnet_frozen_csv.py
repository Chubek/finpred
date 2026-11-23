#!/usr/bin/env python3
"""Build the standalone On1x Source and exercise its inherited-input protocol."""
import csv
import json
import os
from pathlib import Path
import subprocess
import tempfile

from jsonschema import Draft202012Validator
from normalized_oracle import from_csv

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "fixtures"
FIXTURE_DIGEST = "blake3:6fb9b3039772b5e767dbfa4e2c1ba9435247447cde3a1d95f92affb2986ac688"


def main():
    manifest = json.loads((PKG / "plugin.json").read_text())
    assert (manifest["sdk"], manifest["kind"], manifest["name"], manifest["version"]) == (
        1, "Source", "dragnet.frozen_csv", "1.0.0")
    assert manifest["host_capabilities"] == [] and manifest["effects"] == ["pure"]
    assert manifest["contracts"] == ["hospitality.scenario@1", "hospitality.offer@1"]
    validator = Draft202012Validator(json.loads(
        (ROOT / "contracts/hospitality.offer@1.schema.json").read_text()))
    with tempfile.TemporaryDirectory(prefix="finpred-dragnet-") as tmp:
        work = Path(tmp)
        build = work / "build"
        subprocess.run([PKG / "build.sh", build], check=True)
        exe = build / "dragnet-frozen-csv"
        empty = work / "empty"
        empty.mkdir()
        scenario = FIX / "scenario.csv"
        offers = FIX / "offers.csv"
        selected = work / "offers selected.csv"
        # Poison ambient CLI defaults: valid paths should still give no read grant.
        env = {**os.environ, "FINPRED_SCENARIO": str(scenario), "FINPRED_OFFERS": str(offers),
               "FINPRED_HOME": str(empty / "forbidden-store")}

        def run(source=offers, question=scenario, error=None):
            # The shell opens only the two explicitly supplied paths, never input text.
            cmd = 'exec "$1" ' + ('3<"$2" ' if question else '3<&- ') + (
                '4<"$3"' if source else '4<&-')
            p = subprocess.run(["sh", "-c", cmd, "dragnet", exe, question or "", source or ""],
                               env=env, cwd=empty, capture_output=True, timeout=30)
            if error:
                assert p.returncode and not p.stdout and error.encode() in p.stderr, p
            else:
                assert p.returncode == 0 and not p.stderr, p
            return p.stdout

        first = run()
        contracts = [json.loads(line) for line in first.splitlines()]
        with offers.open() as f:
            rows = list(csv.DictReader(f))
        assert len(contracts) == 5  # final two observations are stale / nonbookable
        for contract, row in zip(contracts, rows):
            validator.validate(contract)
            data, times, units = from_csv("hospitality.offer", row)
            assert contract["id"] == f"property:{row['property_id']}:room:{row['room_id']}"
            assert contract["data"] == data
            assert contract["metadata"]["times"] == times and contract["metadata"]["units"] == units
            assert contract["metadata"]["provenance"]["source_artifacts"] == [FIXTURE_DIGEST]
        selected.write_bytes(offers.read_bytes())
        assert run(selected) == first  # different path, identical frozen content
        selected.write_bytes(offers.read_bytes().replace(b"\n", b"\r\n"))
        different = [json.loads(line) for line in run(selected).splitlines()]
        assert len(different) == len(contracts)
        for original, changed in zip(contracts, different):
            assert changed["metadata"].pop("provenance") != original["metadata"].pop("provenance")
            assert changed == original

        header, row, *_ = offers.read_bytes().splitlines(keepends=True)
        for modified in (
            row.replace(b"2026-11-19T18:00:00Z", b"2026-11-20T10:00:01Z")
               .replace(b"2026-11-20T08:00:00Z", b"2026-11-20T10:00:01Z"),
            row.replace(b"2026-11-20T08:00:00Z", b"2026-11-20T10:00:01Z"),
            row.replace(b"2027-01-01", b"2026-12-17"),  # validity doesn't cover departure
        ):
            selected.write_bytes(header + modified)
            assert run(selected) == b""  # well-formed source; no eligible observations
        selected.write_bytes(header + row.replace(b"2026-11-20T08:00:00Z", b"2026-11-20T10:00:00Z"))
        assert len(run(selected).splitlines()) == 1  # equality at the as-of cutoff

        for source, question in ((None, None), (None, scenario), (offers, None)):
            run(source, question, error="supply nonempty frozen CSVs")
        for content, diagnostic in (
            (header.replace(b"total_cents", b"nightly_cents") + row, "unexpected header"),
            (header + row + row, "duplicate bookable room"),
            (header + row + row.replace(b",EUR,", b",USD,"), "unsupported currency"),
            (header + row * (manifest["resource_limits"]["csv_rows"] + 1), "expected 1..512 rows"),
            (b"x" * (manifest["resource_limits"]["bytes_per_input"] + 1), "max 2000000 bytes"),
        ):
            selected.write_bytes(content)
            run(selected, error=diagnostic)
        assert list(empty.iterdir()) == []
    print("dragnet_frozen_csv_ok=true eligible_fixture_rows=5")


if __name__ == "__main__":
    main()
