#!/usr/bin/env python3
"""Cross-check the On1x CLI against the frozen Python behavior without network."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/caravansary/examples"
NATIVE = (ROOT / "bin/caravansary",)
REFERENCE = (sys.executable, ROOT / "plugins/caravansary/caravansary.py")
CLOCK = "--as-of", "2026-11-26T23:30:00Z"


def booking_preflight():
    script = ROOT / "plugins/caravansary/examples/booking-sandbox/pilot.crs"
    env = dict(os.environ, CARAVANSARY_BOOKING_API_TOKEN="", CARAVANSARY_BOOKING_AFFILIATE_ID="")
    cases = (
        (script, (), "--confirm-authorized"),
        (script, ("--confirm-authorized",), "CARAVANSARY_BOOKING_API_TOKEN"),
        (script, ("--confirm-authorized", "--date", "0001-01-01"), "next 500 days"),
        (EXAMPLES / "riviera.crs", ("--confirm-authorized",), "exactly one matrix cell"),
    )
    for path, flags, diagnostic in cases:
        attempt = subprocess.run([*NATIVE, "pilot-booking", path, *flags], env=env, capture_output=True,
                                 text=True, timeout=15)
        assert attempt.returncode != 0 and not attempt.stdout and diagnostic in attempt.stderr, attempt


def run(tool, *args, ok=True):
    result = subprocess.run([*tool, *args], capture_output=True, text=True, timeout=90)
    if ok:
        assert result.returncode == 0, (args, result.stderr)
    else:
        assert result.returncode != 0 and not result.stdout, (args, result.returncode, result.stdout[:120])
    return result.stdout


def plan(tool, script, *args):
    return [json.loads(line) for line in run(tool, "plan", script, *args).splitlines()]


def compare_report(script, *args):
    actual_wire = run(NATIVE, "report", script, *CLOCK, *args)
    expected_wire = run(REFERENCE, "report", script, *CLOCK, *args)
    actual = json.loads(actual_wire)
    expected = json.loads(expected_wire)
    if actual != expected:
        for field in sorted(actual.keys() | expected.keys()):
            if actual.get(field) != expected.get(field):
                if field == "cells":
                    got, want = actual[field], expected[field]
                    assert len(got) == len(want), (len(got), len(want))
                    for i, (cell, ref) in enumerate(zip(got, want)):
                        assert cell == ref, (i, cell, ref)
                else:
                    raise AssertionError((field, actual.get(field), expected.get(field)))
    assert actual_wire == expected_wire, "canonical report bytes differ"
    return actual


def main():
    booking_preflight()
    large = EXAMPLES / "riviera.crs"
    assert "--observations" in run(NATIVE, "--help")
    run(NATIVE, "plan", large, "--observations", "never-opened.jsonl", ok=False)
    run(NATIVE, "plan", large, "--as-of", "2026-02-30T12:00:00Z", ok=False)
    run(NATIVE, "plan", large, "--date", "2026-11-31", ok=False)
    matrix = run(NATIVE, "plan", large, *CLOCK)
    assert matrix == run(REFERENCE, "plan", large, *CLOCK), "canonical matrix bytes differ"
    rows = [json.loads(line) for line in matrix.splitlines()]
    assert len(rows) == 8760 and rows[0]["checkin"] == "2026-11-27"
    full = compare_report(EXAMPLES / "riviera-metrics.crs")
    assert full["transformation"]["metrics"]["expected_cells"] == 8760

    with TemporaryDirectory() as work:
        base = Path(work)
        inputs = base / "inputs"
        shutil.copytree(EXAMPLES, inputs)
        script = inputs / "riviera.crs"
        raw = script.read_text().replace("horizon_days = 365", "horizon_days = 2")
        script.write_text(raw)
        expected = plan(NATIVE, script, *CLOCK)
        assert len(expected) == 48
        assert expected == plan(REFERENCE, script, *CLOCK)
        assert expected == plan(NATIVE, script, "--as-of=2026-11-26T23:30:00+00:00")
        renamed = raw.replace("Riviera Hotel", r"Riviera H\u00f4tel \ud83c\udf0a")
        script.write_text(renamed)
        assert plan(NATIVE, script, *CLOCK) == plan(REFERENCE, script, *CLOCK)
        script.write_text(raw)

        report = compare_report(script)
        assert report["counts_by_status"]["unsupported"] == 48
        assert not (inputs / "coverage.json").exists()
        assert not (inputs / "observations.jsonl").exists()

        script.write_text(raw + '\ncredentials { booking { cookies = "not-opened"; } }\n')
        assert plan(NATIVE, script, *CLOCK) == expected
        script.write_text(raw)
        rolled = plan(NATIVE, script, "--date", "2026-11-28")
        assert {row["cell_key"] for row in expected if row["checkin"] == "2026-11-28"} == {
            row["cell_key"] for row in rolled if row["checkin"] == "2026-11-28"
        }

        metrics = inputs / "riviera-metrics.crs"
        metrics_text = metrics.read_text().replace("horizon_days = 365", "horizon_days = 2")
        metrics.write_text(metrics_text)
        transformed = compare_report(metrics)
        assert transformed["transformation"]["metrics"] == {
            "booking_unsupported": 24, "eligible_cells": 0, "expected_cells": 48,
            "has_fresh_evidence": False, "metric_scope": "competitor coverage",
        }
        assert plan(NATIVE, metrics, *CLOCK) == expected
        metrics.write_text(metrics_text.replace('status_count("unsupported")', 'status_count("bogus")'))
        run(NATIVE, "report", metrics, *CLOCK, ok=False)
        metrics.write_text(metrics_text.replace('status_count("unsupported")', 'status_count(42)'))
        run(NATIVE, "plan", metrics, *CLOCK, ok=False)
        metrics.write_text(metrics_text.replace("total - unsupported", "total - -"))
        run(NATIVE, "plan", metrics, *CLOCK, ok=False)

        competitors = inputs / "riviera-comparables.json"
        document = json.loads(competitors.read_text())
        document["properties"][0]["providers"]["booking"] = {
            "provider_property_id": "synthetic-123", "mapping_status": "verified",
        }
        competitors.write_text(json.dumps(document))
        cell = plan(NATIVE, script, *CLOCK)[0]
        assert cell["status"] == "pending"
        observation = {
            "kind": "caravansary.observation@1",
            "observation_id": "synthetic-complete",
            "cell_key": cell["cell_key"],
            "provider_property_id": cell["provider_property_id"],
            "request_context": cell["request_context"],
            "received_at": "2026-11-25T23:30:00Z",
            "ingested_at": "2026-11-25T23:30:01Z",
            "adapter_version": "fixture",
            "extractor_version": "fixture",
            "complete": True,
            "authoritative": True,
            "outcome": "unavailable",
            "offers": [],
        }
        failure = dict(observation, observation_id="synthetic-failure", outcome="failed",
                       reason="transport_error", complete=False, authoritative=False,
                       received_at="2026-11-26T21:00:00Z", ingested_at="2026-11-26T21:00:01Z")
        log = base / "observations.jsonl"
        log.write_text("\n".join(map(json.dumps, (failure, observation))) + "\n")
        replay = compare_report(script, "--observations", log)
        first = replay["cells"][0]
        assert (first["status"], first["freshness"]) == ("failed", "stale")
        assert first["latest_success"]["outcome"] == "unavailable"

        for invalid in (json.dumps(dict(observation, authoritative=False)), '{"a":1,"a":2}', ""):
            log.write_text(invalid + "\n")
            run(NATIVE, "report", script, *CLOCK, "--observations", log, ok=False)
        log.write_bytes(b'{"a":"\xff"}\n')
        run(NATIVE, "report", script, *CLOCK, "--observations", log, ok=False)
        fifo = base / "unexpected-fifo"
        os.mkfifo(fifo)
        run(NATIVE, "report", script, *CLOCK, "--observations", fifo, ok=False)

        outside = base / competitors.name
        competitors.rename(outside)
        competitors.symlink_to(outside)
        run(NATIVE, "plan", script, *CLOCK, ok=False)
        assert plan(NATIVE, script, *CLOCK, "--input-root", base)[0] == cell
        script.write_text(raw.replace('start = "today"', 'start = "9999-12-31"'))
        run(NATIVE, "plan", script, *CLOCK, "--input-root", base, ok=False)

    print("caravansary On1x CLI: OK")


if __name__ == "__main__":
    main()
