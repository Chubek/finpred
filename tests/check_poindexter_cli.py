#!/usr/bin/env python3
"""Black-box read-only checks for the FinPRED host's Poindexter integration."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile

from check_store import ENV, FIXTURES, ROOT, invoke, tree


PRICING_HEADER = (
    "view,source_run,source_recommendation,source_valuation,currency,price_basis,"
    "current_minor,recommended_minor,change_minor,reason,published"
)
CONTRIBUTION_HEADER = (
    PRICING_HEADER + ",source_demand,marginal_cost_minor,expected_room_nights_milli,"
    "expected_contribution_minor_milli,scale"
)
CONTRIBUTION_ID = "04d4a72d20e2a2b24f1e5bce75eed6eaa604cec87d485bf98b55e8b598f2663f"
CONTRIBUTION_INPUTS = {
    "demand": FIXTURES / "demand_contribution.csv",
    "strategy": ROOT / "strategies/contribution.ottomat",
}


def check_view(home, summary, expected, frozen_valuation):
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
    assert digest == frozen_valuation
    valuation = json.loads((home / f"artifacts/blake3-{digest}.txt").read_bytes())
    assert valuation["kind"] == "pricing.valuation" and valuation["data"]["current_cents"] == 17500
    assert (sheet["currency"], sheet["price_basis"], sheet["published"]) == ("EUR", "room_night", "false")
    assert (sheet["current_minor"], sheet["recommended_minor"], sheet["change_minor"], sheet["reason"]) == expected
    row = ",".join(("poindexter.pricing-sheet@1", f"run:{run_id}", sheet["source_recommendation"],
                    f"blake3:{digest}", "EUR", "room_night", *expected, "false"))
    assert output == f"{PRICING_HEADER}\n{row}\n".encode("ascii")
    return run_id, fields["recommendation_digest"]


def check_contribution(root):
    home = root / "contribution"
    summary = invoke(home, "run", **CONTRIBUTION_INPUTS)
    fields = dict(line.split("=", 1) for line in summary.decode("ascii").splitlines())
    run_id = fields["run_id"]
    assert run_id == CONTRIBUTION_ID
    assert fields["recommendation_digest"] == "5819505746c8b2b016378053ec9991ec221da4d85fd46464c612156c8ac39da2"
    assert fields["trace_digest"] == "3869ad29928861b83d3ee681a96d1f38b3852e4bcb1fccfae7a79d01f5ab9d9e"
    manifest = home / f"runs/{run_id}.txt"
    version, scenario, demand, valuation, policy, rec, trace = manifest.read_text().strip().split(",")
    assert version == "finpred-run@3" and rec == fields["recommendation_digest"]

    def artifact(digest):
        return home / f"artifacts/blake3-{digest}.txt"

    assert artifact(valuation).read_bytes() == (FIXTURES / "valuation.csv").read_bytes()
    assert artifact(demand).read_bytes() == CONTRIBUTION_INPUTS["demand"].read_bytes()
    row = (
        f"poindexter.contribution-sheet@1,run:{run_id},blake3:{rec},blake3:{valuation},EUR,room_night,"
        f"17500,19000,1500,max_expected_contribution,false,blake3:{demand},8000,105000,milli_minor:1155000000,1000"
    )
    expected = f"{CONTRIBUTION_HEADER}\n{row}\n".encode("ascii")
    absent = {k: root / "absent" for k in ("scenario", "demand", "offers", "valuation", "strategy")}
    before = tree(home)
    for _ in range(2):
        assert invoke(home, "poindexter", run_id, **absent) == expected
    assert invoke(home, "replay", run_id, **absent) == b"replay_ok=true\n" + summary
    assert tree(home) == before

    # Full replay must precede all CSV output, even for dependencies that do
    # not directly contribute a cell (the plan, lineage and trace).
    for path in (manifest, *(artifact(d) for d in (run_id, scenario, demand, valuation, policy, rec, trace))):
        original = path.read_bytes()
        path.write_bytes((b"finpred-run@3," + b"," * 389 + b"\n") if path == manifest else b"damaged\n")
        before = tree(home)
        stdout = invoke(home, "poindexter", run_id, success=False, **absent)
        assert b"source_run," not in stdout and b"poindexter.contribution-sheet@" not in stdout, path
        assert tree(home) == before
        path.write_bytes(original)

    # A different valid content-addressed trace is still not this run's
    # recomputed trace; checking only content digests would miss this.
    changed = root / "different-demand.csv"
    changed.write_bytes(CONTRIBUTION_INPUTS["demand"].read_bytes().replace(b"19000,105000", b"19000,104999"))
    other = invoke(home, "run", **dict(CONTRIBUTION_INPUTS, demand=changed)).decode("ascii")
    foreign_trace = dict(line.split("=", 1) for line in other.splitlines())["trace_digest"]
    assert foreign_trace != trace and artifact(foreign_trace).is_file()
    manifest.write_text(",".join((version, scenario, demand, valuation, policy, rec, foreign_trace)) + "\n")
    before = tree(home)
    stdout = invoke(home, "poindexter", run_id, success=False, **absent)
    assert b"source_run," not in stdout and b"poindexter.contribution-sheet@" not in stdout
    assert tree(home) == before


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-poindexter-cli-") as tmp:
        home = Path(tmp) / "store"
        fixture = json.loads((FIXTURES / "replay_v1.json").read_bytes())
        frozen_valuation, = (p.removeprefix("artifacts/blake3-").removesuffix(".txt")
                             for p, text in fixture["files"].items() if '"kind":"pricing.valuation"' in text)
        cases = [
            ("", ("17500", "17100", "-400", "lower_percentile_shortcut"),
             "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"),
            ("_multiroom", ("17500", "16000", "-1500", "guardrail_adjustment"),
             "7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b"),
        ]
        for suffix, expected, fixed_id in cases:
            summary = invoke(home, "run", scenario=FIXTURES / f"scenario{suffix}.csv",
                             offers=FIXTURES / f"offers{suffix}.csv").decode("ascii")
            run_id, rec = check_view(home, summary, expected, frozen_valuation)
            assert run_id == fixed_id
        for path, content in fixture["files"].items():
            (home / path).write_bytes(content.encode("ascii"))
        for fixed_id, summary in fixture["runs"].items():
            expected = next(row for _, row, _ in cases if f"recommendation_minor={row[1]}\n" in summary)
            assert check_view(home, summary, expected, frozen_valuation)[0] == fixed_id
        # A damaged output must never be presented as a result, even if the
        # real inputs still permit an identical numerical recomputation.
        (home / f"artifacts/blake3-{rec}.txt").write_bytes(b"corrupted\n")
        before = tree(home)
        for invalid in (run_id, "0" * 64):
            proc = subprocess.run([ROOT / "bin/finpred", "poindexter", invalid],
                                  env={**ENV, "FINPRED_HOME": str(home)}, capture_output=True, timeout=60)
            assert proc.returncode > 0 and b"source_run" not in proc.stdout and b"poindexter.pricing-sheet@" not in proc.stdout
        assert before == tree(home)
        check_contribution(Path(tmp))
    print("poindexter_cli_ok=true v1=2 v2=2 v3=1 rejected=11")


if __name__ == "__main__":
    main()
