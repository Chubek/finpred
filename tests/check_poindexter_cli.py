#!/usr/bin/env python3
"""Black-box read-only checks for the FinPRED host's Poindexter integration."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile

from check_store import ENV, FIXTURES, ROOT, invoke, tree


def check_view(home, summary, expected):
    fields = dict(line.split("=", 1) for line in summary.splitlines())
    run_id = fields["run_id"]
    absent = {k: home / "absent" for k in ("scenario", "offers", "valuation", "strategy")}
    before = tree(home)
    output = invoke(home, "poindexter", run_id, **absent)
    assert output == invoke(home, "poindexter", run_id, **absent) and tree(home) == before
    sheet, = csv.DictReader(output.decode("ascii").splitlines())
    assert sheet["source_run"] == "run:" + run_id
    assert sheet["view"] == "poindexter.pricing-sheet@1"
    assert sheet["source_recommendation"] == "blake3:" + fields["recommendation_digest"]
    # Resolve the reported artifact, independent of how the renderer obtained it.
    digest = sheet["source_valuation"].removeprefix("blake3:")
    valuation = json.loads((home / f"artifacts/blake3-{digest}.txt").read_bytes())
    assert valuation["kind"] == "pricing.valuation" and valuation["data"]["current_cents"] == 17500
    assert (sheet["currency"], sheet["price_basis"], sheet["published"]) == ("EUR", "room_night", "false")
    assert (sheet["current_minor"], sheet["recommended_minor"], sheet["change_minor"], sheet["reason"]) == expected
    return run_id, fields["recommendation_digest"]


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-poindexter-cli-") as tmp:
        home = Path(tmp) / "store"
        cases = [("", ("17500", "17100", "-400", "lower_percentile_shortcut")),
                 ("_multiroom", ("17500", "16000", "-1500", "guardrail_adjustment"))]
        for suffix, expected in cases:
            summary = invoke(home, "run", scenario=FIXTURES / f"scenario{suffix}.csv",
                             offers=FIXTURES / f"offers{suffix}.csv").decode("ascii")
            run_id, rec = check_view(home, summary, expected)
        fixture = json.loads((FIXTURES / "replay_v1.json").read_bytes())
        for path, content in fixture["files"].items():
            (home / path).write_bytes(content.encode("ascii"))
        for summary in fixture["runs"].values():
            expected = next(row for _, row in cases if f"recommendation_minor={row[1]}\n" in summary)
            check_view(home, summary, expected)
        # A damaged output must never be presented as a result, even if the
        # real inputs still permit an identical numerical recomputation.
        (home / f"artifacts/blake3-{rec}.txt").write_bytes(b"corrupted\n")
        before = tree(home)
        for invalid in (run_id, "0" * 64):
            proc = subprocess.run([ROOT / "bin/finpred", "poindexter", invalid],
                                  env={**ENV, "FINPRED_HOME": str(home)}, capture_output=True, timeout=60)
            assert proc.returncode > 0 and b"source_run" not in proc.stdout and b"poindexter.pricing-sheet@" not in proc.stdout
        assert before == tree(home)
    print("poindexter_cli_ok=true v1=2 v2=2 rejected=2")


if __name__ == "__main__":
    main()
