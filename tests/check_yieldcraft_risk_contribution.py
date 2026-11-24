#!/usr/bin/env python3
"""Exercise the planning CLI with real typed estimator output and endpoint enumeration."""
import csv
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "bin/yieldcraft-inventory"
ESTIMATOR = ROOT / "bin/yieldcraft-demand"


def row(values):
    return ",".join(map(str, values)) + "\n"


def oracle(cost, current, floor, cap, arms):
    candidates = []
    for p, lo, mid, hi in arms:
        candidates.append(dict(price_minor=p, low_room_nights_milli=lo, nominal_room_nights_milli=mid,
                               high_room_nights_milli=hi, nominal_minor_milli=(p-cost)*mid,
                               worst_minor_milli=min((p-cost)*amount for amount in (lo, hi)),
                               feasible=floor <= p <= cap))

    def pick(metric):
        feasible = [c for c in candidates if c["feasible"] and c[metric] > 0]
        if not feasible:
            return dict(action="hold", price_minor=None, nominal_minor_milli=0, worst_minor_milli=0)
        item = sorted(feasible, key=lambda x: (-x[metric], abs(x["price_minor"]-current), x["price_minor"]))[0]
        return {"action": "offer", **{k: item[k] for k in ("price_minor", "nominal_minor_milli", "worst_minor_milli")}}

    return candidates, pick("worst_minor_milli"), pick("nominal_minor_milli")


def main():
    tmp = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    schema = json.loads((ROOT / "contracts/pricing.contribution-stress@1.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    with tempfile.TemporaryDirectory(prefix="yieldcraft-risk-", dir=tmp) as directory:
        work = Path(directory)
        env = {**os.environ, "TMPDIR": str(tmp), "FINPRED_BUILD_DIR": str(work), "FINPRED_HOME": str(work / "unused")}

        def run(exe, *args, error=None):
            proc = subprocess.run([exe, *args], env=env, cwd=work, capture_output=True, timeout=120)
            if error is not None:
                assert proc.returncode != 0 and error in proc.stdout + proc.stderr, proc
                assert not proc.stdout.startswith(b"{"), proc
            else:
                assert proc.returncode == 0, proc
            return proc.stdout

        run(ESTIMATOR, "build")
        run(PLANNER, "build")
        scenario, valuation, demand, stress, exposure = (work / (n + ".csv") for n in
                                                         ("scenario", "valuation", "demand", "stress", "exposure"))
        scenario.write_text((ROOT / "fixtures/scenario.csv").read_text().replace("2026-12-18,2,0,2,", "2026-12-17,2,0,1,"))
        valuation.write_bytes((ROOT / "fixtures/valuation.csv").read_bytes())
        sd = run(ESTIMATOR, "scenario-digest", scenario).decode().strip()
        exposure.write_text(
            "pricing.first-party-exposure@1\n"
            "scenario_blake3,property,product,cohort,currency,price_basis,assignment,started_at,"
            "ended_at,finalized_at,ingested_at,target_exposures,available_room_nights,marginal_cost_minor\n"
            f"{sd},hotel-1,standard,lead-1,EUR,room_night,randomized,2026-11-15T08:00:00Z,"
            "2026-11-18T08:00:00Z,2026-11-19T09:00:00Z,2026-11-20T10:00:00Z,100,120,8000\n"
            "price_minor,assigned,kept,cancelled,nonpurchase,unavailable,unresolved\n"
            "7000,20,13,2,5,0,0\n16000,20,7,2,11,0,0\n17500,60,25,3,32,0,0\n19000,50,12,5,33,0,0\n"
        )
        demand.write_bytes(run(ESTIMATOR, "estimate", scenario, exposure))
        report = json.loads(run(ESTIMATOR, "evidence", scenario, exposure))
        dd = report["demand"][7:]
        point = [(int(p), int(q)) for p, q in list(csv.reader(demand.read_text().splitlines()))[4:]]
        assert point == [(7000, 65000), (16000, 40000), (17500, 40000), (19000, 24000)], point
        cutoff = "2026-11-20T10:00:00Z"
        header = ("pricing.demand-stress-input@1\n"
                  "demand_blake3,assumptions_as_of\n"
                  f"{dd},{cutoff}\n"
                  "price_minor,low_room_nights_milli,high_room_nights_milli\n")
        frozen = {f: f.read_bytes() for f in (scenario, valuation, demand, exposure)}

        def evaluate(raw, error=None):
            stress.write_bytes(raw.encode("ascii"))
            before = set(work.iterdir())
            out = run(PLANNER, "stress-contribution", scenario, valuation, demand, stress, error=error)
            assert before == set(work.iterdir()) and stress.read_bytes() == raw.encode("ascii")
            return json.loads(out) if error is None else None

        scenarios = [
            [(q, q) for _, q in point],
            [(40000, 100000), (35000, 60000), (20000, 50000), (10000, 40000)],
            [(0, q) for _, q in point],
        ]
        rng = random.Random(290622)
        for _ in range(25):
            lows = sorted([rng.randint(0, q) for _, q in point], reverse=True)
            highs = sorted([rng.randint(q, 1000000) for _, q in point], reverse=True)
            scenarios.append(list(zip(lows, highs)))
        for i, intervals in enumerate(scenarios):
            raw = header + "".join(row((p, lo, hi)) for (p, _), (lo, hi) in zip(point, intervals))
            out = evaluate(raw.replace("\n", "\r\n") if i % 2 else raw)
            validator.validate(out)
            candidates, robust, nominal = oracle(8000, 17500, 16000, 22500,
                                                  [(p, lo, q, hi) for (p, q), (lo, hi) in zip(point, intervals)])
            assert out["candidates"] == candidates and out["robust"] == robust and out["nominal"] == nominal
            assert out["kind"] == "pricing.contribution-stress" and out["version"] == 1 and out["published"] is False
            assert out["comparison"] == "modeled_not_observed" and out["scale"] == 1000
            assert out["demand"] == report["demand"] and out["scenario"] == report["scenario"]
            assert out["assumptions_as_of"] == out["decision_at"] == cutoff
            assert out["feasible_floor_minor"] == 16000 and out["feasible_cap_minor"] == 22500

        valid = header + "".join(row((p, q, q)) for p, q in point)
        rejected = [
            (valid.replace(dd, "0"*64), b"wrong demand digest"),
            (valid.replace(cutoff, "2026-11-20T10:00:01Z"), b"invalid assumption timestamp"),
            (valid.replace(cutoff, "2026-11-20T09:59:59Z"), b"invalid assumption timestamp"),
            (valid.replace("17500,", "17501,"), b"incompatible or unordered"),
            (valid.replace("19000,24000,24000", "19000,24000,23000"), b"incompatible or unordered"),
            (valid.replace("19000,24000,24000\n", ""), b"must cover every price"),
            (valid.replace("17500,40000,40000", "17500,40001,40001"), b"incompatible or unordered"),
            (valid.replace("7000,65000,65000", "7000,65000,1000001"), b"incompatible or unordered"),
        ]
        for raw, error in rejected:
            evaluate(raw, error)
        assert frozen == {p: p.read_bytes() for p in frozen}
        demand.write_bytes(frozen[demand] + b"\n")
        evaluate(valid, b"must cover every price")
        assert not (work / "unused").exists()
    print(f"yieldcraft_risk_contribution_ok=true oracle_cases={len(scenarios)} invalid_cases={len(rejected)+1}")


if __name__ == "__main__":
    main()
