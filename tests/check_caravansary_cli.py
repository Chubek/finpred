#!/usr/bin/env python3
"""Exercise the standalone planner, file authority and report boundary."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs/caravansary/examples"
CLI = ROOT / "plugins/caravansary/caravansary.py"
CLOCK = "2026-11-26T23:30:00Z"


def run(*args, ok=True):
    proc = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                          capture_output=True, text=True, check=False)
    assert (proc.returncode == 0) == ok, (args, proc.stderr)
    if not ok:
        assert not proc.stdout, proc.stdout
    return proc


with TemporaryDirectory() as tmp:
    work = Path(tmp)
    inputs = work / "inputs"
    shutil.copytree(EXAMPLES, inputs)
    script = inputs / "riviera.crs"
    text = script.read_text(encoding="utf-8").replace("horizon_days = 365", "horizon_days = 2")
    script.write_text(text, encoding="utf-8")
    output = run("plan", script, "--as-of", CLOCK).stdout
    rows = [json.loads(line) for line in output.splitlines()]
    assert len(rows) == 48
    assert rows[0]["checkin"] == "2026-11-27"  # Paris after midnight
    assert len({row["cell_key"] for row in rows}) == len(rows)
    assert run("plan", script, "--as-of", CLOCK).stdout == output
    original_report = run("report", script, "--as-of", CLOCK).stdout
    declared = text.replace(
        "  property {",
        '  credentials { booking { cookies = "not-readable.json"; }'
        ' agoda { environment = ["AGODA_TEST_KEY"]; dotenv = ".not-readable.env"; } }\n'
        "  property {",
    )
    script.write_text(declared, encoding="utf-8")
    assert run("plan", script, "--as-of", CLOCK).stdout == output
    assert run("report", script, "--as-of", CLOCK).stdout == original_report
    script.write_text(text, encoding="utf-8")
    rolled = run("plan", script, "--date", "2026-11-28").stdout
    shared = {row["cell_key"] for row in rows if row["checkin"] == "2026-11-28"}
    assert shared == {row["cell_key"] for row in map(json.loads, rolled.splitlines())
                      if row["checkin"] == "2026-11-28"}

    report = json.loads(original_report)
    assert report["kind"] == "caravansary.coverage@1"
    assert len(report["cells"]) == 48
    assert all(row["status"] == "unsupported" and row["freshness"] == "none"
               for row in report["cells"])
    assert not (inputs / "coverage.json").exists()
    assert not (inputs / "observations.jsonl").exists()
    log = work / "log.jsonl"
    log.write_text('{"kind": "observation", "kind": "other"}\n', encoding="utf-8")
    assert "duplicate JSON field" in run("report", script, "--observations", log, ok=False).stderr

    competitors_path = inputs / "riviera-comparables.json"
    competitors = json.loads(competitors_path.read_text(encoding="utf-8"))
    competitors["properties"][0]["providers"]["booking"] = {
        "provider_property_id": "synthetic-123", "mapping_status": "verified",
    }
    competitors["properties"][1]["providers"]["booking"] = {
        "provider_property_id": "synthetic-456", "mapping_status": "unverified",
    }
    competitors_path.write_text(json.dumps(competitors), encoding="utf-8")
    updated = [json.loads(line) for line in run("plan", script, "--as-of", CLOCK).stdout.splitlines()]
    assert updated[0]["status"] == "pending"
    assert updated[0]["config_id"] != rows[0]["config_id"]
    assert any(row["reason"] == "mapping_unverified" for row in updated)

    cell = updated[0]
    record = {
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
    failure = dict(record, observation_id="synthetic-failure", outcome="failed",
                   reason="transport_error", complete=False, authoritative=False,
                   received_at="2026-11-26T21:00:00Z", ingested_at="2026-11-26T21:00:01Z")
    log.write_text("\n".join(map(json.dumps, (failure, record))) + "\n", encoding="utf-8")
    replay = json.loads(run("report", script, "--as-of", CLOCK, "--observations", log).stdout)
    folded = replay["cells"][0]
    assert replay["counts_by_status"]["failed"] == 1
    assert replay["counts_by_freshness"]["stale"] == 1
    assert replay["capacity"]["booking"]["eligible_cells"] == 12
    assert (folded["status"], folded["freshness"]) == ("failed", "stale")
    assert folded["latest_success"]["outcome"] == "unavailable"
    assert folded["latest_attempt"]["reason"] == "transport_error"
    log.write_text(json.dumps(dict(record, authoritative=False)) + "\n", encoding="utf-8")
    assert "unavailable requires" in run(
        "report", script, "--as-of", CLOCK, "--observations", log, ok=False,
    ).stderr

    outside = work / "comparables.json"
    competitors_path.rename(outside)
    competitors_path.symlink_to(outside)
    denied = run("plan", script, "--as-of", CLOCK, ok=False)
    assert "outside the host-approved directories" in denied.stderr
    allowed = run("plan", script, "--as-of", CLOCK, "--input-root", work)
    assert list(map(json.loads, allowed.stdout.splitlines())) == updated

    script.write_text(text.replace('start = "today"', 'start = "9999-12-31"'), encoding="utf-8")
    overflow = run("plan", script, "--input-root", work, ok=False)
    assert "checkout exceeds" in overflow.stderr

print("caravansary CLI: OK")
