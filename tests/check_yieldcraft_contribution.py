#!/usr/bin/env python3
"""Contribution strategy: own-demand evidence, constrained objective and replay."""
import json
import subprocess
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator

from check_store import ENV, FIXTURES, ROOT, tree


DEMAND = (FIXTURES / "demand_contribution.csv").read_bytes()
VALUATION = (FIXTURES / "valuation.csv").read_bytes()
POLICY = ROOT / "strategies/contribution.ottomat"
SCHEMA = ROOT / "contracts/pricing.contribution-recommendation@1.schema.json"


def command(home, *args, launcher="yieldcraft", cwd=ROOT, error=None, **variables):
    env = {**ENV, "FINPRED_HOME": str(home),
           **{f"FINPRED_{key.upper()}": str(val) for key, val in variables.items()}}
    proc = subprocess.run([ROOT / "bin" / launcher, *map(str, args)], cwd=cwd, env=env,
                          capture_output=True, timeout=60)
    if error is None:
        assert proc.returncode == 0, proc
    else:
        assert proc.returncode > 0 and error in proc.stdout + proc.stderr, proc
        assert b"recommendation_minor=" not in proc.stdout and b"replay_ok=true" not in proc.stdout, proc
    return proc.stdout


def fields(output):
    return dict(line.split("=", 1) for line in output.decode("ascii").splitlines())


def grid(lines):
    return b"\n".join(DEMAND.splitlines()[:4] + lines + [b""])


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-contribution-") as tmp:
        root = Path(tmp)
        home = root / "store"
        denied = root / "denied"
        demand = root / "demand.csv"
        demand.write_bytes(DEMAND)
        missing = root / "absent"
        # A good comparable-offer fixture is present but never a substitute.
        command(denied, error=b"insufficient_demand_evidence")
        command(denied, "--demand", missing, error=b"insufficient_demand_evidence")
        command(denied, "--market-positioning", "--demand", demand, error=b"separate strategies")
        command(denied, "--capture", missing, "--demand", demand, error=b"separate strategies")
        assert not denied.exists()

        summary = command(home, "--demand", demand.name, cwd=root, offers=missing)
        result = fields(summary)
        assert result["strategy"] == "yieldcraft.contribution@1"
        assert result["recommendation_minor"] == "19000"
        assert result["reason"] == "max_expected_contribution"
        assert result["published"] == "false"
        run_id = result["run_id"]
        assert command(home, "run", launcher="finpred", demand=demand,
                       strategy=POLICY, offers=missing) == summary
        manifest = home / "runs" / f"{run_id}.txt"
        version, s, d, v, p, rec, trace = manifest.read_text().rstrip("\n").split(",")
        assert version == "finpred-run@3" and manifest.stat().st_size == 404
        assert rec == result["recommendation_digest"] and trace == result["trace_digest"]

        def artifact(digest):
            return home / "artifacts" / f"blake3-{digest}.txt"

        assert artifact(s).read_bytes() == (FIXTURES / "scenario.csv").read_bytes()
        assert artifact(d).read_bytes() == DEMAND
        assert artifact(v).read_bytes() == VALUATION
        assert artifact(p).read_bytes() == POLICY.read_bytes()
        assert f"raw_demand={d}\n" in artifact(run_id).read_text()
        obj = json.loads(artifact(rec).read_bytes())
        Draft202012Validator(json.loads(SCHEMA.read_bytes())).validate(obj)
        assert obj["metadata"]["provenance"]["source_artifacts"] == [f"blake3:{h}" for h in (s, d, v)]
        assert obj["data"] == {
            "price_minor": 19000, "marginal_cost_minor": 8000, "expected_room_nights_milli": 105000,
            "expected_contribution_minor_milli": 1155000000, "scale": 1000,
            "reason": "max_expected_contribution", "published": False, "mode": "recommendation",
        }

        demand.unlink()
        frozen = {key: missing for key in ("scenario", "demand", "valuation", "strategy", "offers")}
        before = tree(home)
        replay = b"replay_ok=true\n" + summary
        assert command(home, "replay", run_id, launcher="finpred", **frozen) == replay
        explain = command(home, "explain", run_id, launcher="finpred", **frozen)
        assert explain == replay + b"trace_begin\n" + artifact(trace).read_bytes() + b"trace_end\n"
        evidence = command(home, "evidence", run_id, launcher="finpred", **frozen)
        assert evidence.startswith(replay + b"evidence_begin\nevidence_version=yieldcraft.demand-evidence@1\n")
        assert evidence.endswith(b"evidence_end\n")
        for witness in (b"candidate=15000,250000,1750000000,outside_guardrails\n",
                        b"candidate=19000,105000,1155000000,feasible\n",
                        b"candidate=23000,50000,750000000,outside_guardrails\n"):
            assert witness in explain and witness in evidence
        assert b"percentile" not in explain
        assert tree(home) == before
        artifact(d).write_bytes(DEMAND.replace(b"105000", b"104999"))
        before = tree(home)
        command(home, "replay", run_id, launcher="finpred", error=b"snapshot digest mismatch", **frozen)
        assert tree(home) == before
        artifact(d).write_bytes(DEMAND)

        valve = root / "valuation.csv"
        valve.write_bytes(VALUATION.replace(b",5000,500\n", b",300,500\n"))
        cases = (
            (DEMAND.replace(b",8000\n", b",0\n"), {}, "17500"),  # revenue-only would differ
            (DEMAND.replace(b"19000,105000", b"19000,90000"), {}, "17500"),
            (DEMAND, {"valuation": valve}, "17500"),  # do not clip to unsupported 17800
            (grid([b"16000,50000", b"18000,40000"]), {}, "18000"),  # tie: closer to current
            (grid([b"16500,21000", b"18500,17000"]), {}, "16500"),  # tie: lower
        )
        seen = {run_id}
        for raw, overrides, expected in cases:
            demand.write_bytes(raw)
            value = fields(command(home, demand=demand, **overrides))
            assert value["recommendation_minor"] == expected, value
            assert value["run_id"] not in seen
            seen.add(value["run_id"])

        valve.write_bytes(VALUATION.replace(b",17500,16000,25000,5000,500\n",
                                            b",1000000000000,0,1000000000000,1000000000000,0\n"))
        demand.write_bytes(grid([b"0,1000000", b"1000000000000,1000000"]).replace(b",8000\n", b",0\n"))
        maximum = fields(command(home, demand=demand, valuation=valve))
        assert maximum["recommendation_minor"] == "1000000000000"
        assert json.loads(artifact(maximum["recommendation_digest"]).read_bytes())["data"][
            "expected_contribution_minor_milli"] == 10**18

        bad_cases = (
            (grid([b"17500,1000"]), b"insufficient_demand_evidence"),
            (grid([b"15000,1000", b"22501,500"]), b"no priced demand point"),
            (grid([b"17500,0", b"19000,0"]), b"no_positive_expected_contribution"),
            (DEMAND.replace(b",8000\n", b",25000\n"), b"no_positive_expected_contribution"),
            (DEMAND.replace(b"T09:30:00Z", b"T10:30:00Z"), b"future-dated provenance"),
            (DEMAND.replace(b"2026-11-20T08:30", b"2026-11-12T08:30"), b"snapshot is stale"),
            (DEMAND.replace(b"d29ce687", b"c29ce687"), b"scenario, money or price basis mismatch"),
            (DEMAND.replace(b"room_night", b"whole_stay", 1), b"scenario, money or price basis mismatch"),
            (DEMAND.replace(b"calibrated_booking_model", b"competitor_list_prices"), b"unsupported method"),
            (DEMAND.replace(b"17500,115000", b"16000,115000"), b"strictly increasing"),
            (DEMAND.replace(b"17500,115000", b"17500,130000"), b"nonincreasing"),
            (DEMAND.replace(b"15000,250000", b"15000,1000001"), b"demand must be bounded"),
        )
        for raw, diagnostic in bad_cases:
            demand.write_bytes(raw)
            command(denied, demand=demand, error=diagnostic)
            assert not denied.exists()

        demand.write_bytes(DEMAND)
        valve.write_bytes(VALUATION.replace(b",17500,16000,25000,5000,500\n", b",10000,16000,25000,300,500\n"))
        command(denied, demand=demand, valuation=valve, error=b"guardrail_conflict")
        policy = root / "market-profile.ottomat"
        policy.write_bytes(POLICY.read_bytes().replace(b"\n", b"\r\n"))
        selected = fields(command(home, "--strategy", policy, demand=demand))
        assert selected["recommendation_minor"] == "19000" and selected["run_id"] != run_id
        policy.write_bytes(POLICY.read_bytes().replace(b"source pricing.demand@1", b"source hospitality.offer@1"))
        command(denied, "--strategy", policy, error=b"invalid graph or incompatible strategy")
        assert not denied.exists()

        market = fields(command(home, "--market-positioning"))
        assert market["run_id"] == "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"
        assert market["recommendation_minor"] == "17100"
    print("yieldcraft_contribution_ok=true")


if __name__ == "__main__":
    main()
