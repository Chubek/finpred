#!/usr/bin/env python3
"""Build the standalone estimator, compare it to a min-max oracle, and optimize."""
import csv
import json
import os
import random
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
TMPDIR = Path(os.environ.get("TMPDIR") or ROOT / "build" / "tmp")
FIXTURES = ROOT / "fixtures"
ESTIMATOR = ROOT / "bin" / "yieldcraft-demand"
BASE = ((16000, 20, 7, 2, 11, 0, 0), (17500, 60, 25, 3, 32, 0, 0), (19000, 50, 12, 5, 33, 0, 0))


def csv_line(values):
    return ",".join(map(str, values)) + "\n"


def estimate_reference(arms, target):
    """Weighted decreasing isotonic min-max formula; no PAVA or block merging."""
    def rate(a, b):
        return Fraction(sum(row[2] for row in arms[a:b + 1]),
                        sum(row[1] for row in arms[a:b + 1]))

    fitted = [
        min(max(rate(a, b) for b in range(i, len(arms))) for a in range(i + 1))
        for i in range(len(arms))
    ]
    return [(row[0], int(q * target * 1000 + Fraction(1, 2))) for row, q in zip(arms, fitted)]


def main():
    TMPDIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="yieldcraft-demand-", dir=TMPDIR) as tmp:
        work = Path(tmp).resolve()
        env = {**os.environ, "TMPDIR": str(TMPDIR.resolve()),
               "FINPRED_BUILD_DIR": str(work), "FINPRED_HOME": str(work / "unused-store")}

        def invoke(*args, error=None, env_override=None, executable=ESTIMATOR):
            proc = subprocess.run([executable, *map(str, args)], cwd=work, capture_output=True,
                                  env={**env, **(env_override or {})}, timeout=120)
            if error:
                assert proc.returncode != 0 and error in proc.stdout + proc.stderr, proc
                assert b"pricing.demand@1" not in proc.stdout and b"demand_replay_ok" not in proc.stdout, proc
            else:
                assert proc.returncode == 0, proc
            return proc.stdout

        invoke("build")
        scenario = work / "scenario.csv"
        text = (FIXTURES / "scenario.csv").read_text()
        scenario.write_text(text.replace("2026-12-18,2,0,2,", "2026-12-17,2,0,1,"))
        scenario_hash = invoke("scenario-digest", scenario).decode().strip()
        exposure = work / "exposure.csv"
        demand = work / "demand.csv"
        evidence = work / "evidence.json"

        def text_of(arms, *, target=100, available=120):
            return (
                "pricing.first-party-exposure@1\n"
                "scenario_blake3,property,product,cohort,currency,price_basis,assignment,started_at,"
                "ended_at,finalized_at,ingested_at,target_exposures,available_room_nights,marginal_cost_minor\n"
                f"{scenario_hash},hotel-1,standard,lead-1,EUR,room_night,randomized,2026-11-15T08:00:00Z,"
                f"2026-11-18T08:00:00Z,2026-11-19T09:00:00Z,2026-11-20T10:00:00Z,{target},{available},8000\n"
                "price_minor,assigned,kept,cancelled,nonpurchase,unavailable,unresolved\n"
                + "".join(csv_line(row) for row in arms)
            )

        exposure.write_text(text_of(BASE))
        demand.write_bytes(invoke("estimate", scenario, exposure))
        evidence.write_bytes(invoke("evidence", scenario, exposure))
        report = json.loads(evidence.read_bytes())
        schema = json.loads((ROOT / "contracts/pricing.demand-estimation@1.schema.json").read_bytes())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
        assert report["scenario"] == f"blake3:{scenario_hash}"
        assert report["pools"] == [
            {"arm_start": 0, "arm_end_exclusive": 2, "kept": 32, "assigned": 80, "expected_room_nights_milli": 40000},
            {"arm_start": 2, "arm_end_exclusive": 3, "kept": 12, "assigned": 50, "expected_room_nights_milli": 24000},
        ]
        rows = list(csv.reader(demand.read_text().splitlines()))
        assert [(int(p), int(q)) for p, q in rows[4:]] == estimate_reference(BASE, 100)
        assert rows[2][0] == scenario_hash and rows[2][5:7] == ["first_party_price_experiment", report["id"][7:]]
        frozen = (scenario, exposure, demand, evidence, report["id"])
        snapshot = {p.name: p.read_bytes() for p in (scenario, exposure, demand, evidence)}
        assert invoke("replay", *frozen) == b"demand_replay_ok=true\n"
        assert snapshot == {p.name: p.read_bytes() for p in (scenario, exposure, demand, evidence)}
        assert not (work / "unused-store").exists()

        for path, changed in (
            (evidence, evidence.read_bytes().replace(b'"kept":32', b'"kept":33')),
            (demand, demand.read_bytes().replace(b"40000", b"40001")),
            (exposure, exposure.read_bytes().replace(b",25,3,32,", b",25,4,31,")),
        ):
            # Exposure mutation can leave every prediction unchanged; replay must still refuse it.
            path.write_bytes(changed)
            invoke("replay", *frozen, error=b"replay identity or bytes differ")
            path.write_bytes(snapshot[path.name])
        invoke("replay", *frozen[:-1], "blake3:" + "1" * 64, error=b"replay identity or bytes differ")
        changed = work / "scenario-changed.csv"
        changed.write_bytes(scenario.read_bytes().replace(b"\n1,", b"\n2,"))
        invoke("estimate", changed, exposure, error=b"scenario, currency or price basis mismatch")

        rng = random.Random(71222)
        # Two monotone controls at the ends make every random case nonflat.
        for case in range(25):
            arms = [(1000, 40, 40, 0, 0, 0, 0)]
            for i in range(rng.randint(1, 15)):
                assigned = rng.randint(20, 100)
                kept = rng.randint(0, assigned)
                cancelled = rng.randint(0, assigned - kept)
                arms.append((2000 + 1000*i, assigned, kept, cancelled, assigned - kept - cancelled, 0, 0))
            arms.append((25000, 40, 0, 0, 40, 0, 0))
            target = rng.randint(1, 1000)
            raw = text_of(arms, target=target, available=target)
            exposure.write_bytes(raw.replace("\n", "\r\n" if case % 2 else "\n").encode())
            out = invoke("estimate", scenario, exposure).decode().splitlines()[4:]
            assert out == [f"{p},{q}" for p, q in estimate_reference(arms, target)]

        # Exactly half a milli room-night rounds up; zero demand stays zero.
        edge = ((16000, 2000, 1, 0, 1999, 0, 0), (17000, 20, 0, 0, 20, 0, 0))
        exposure.write_text(text_of(edge, target=1))
        assert invoke("estimate", scenario, exposure).endswith(b"16000,1\n17000,0\n")
        # Trigger a 63-arm high-count pool and exercise bounded cross products.
        maximum = [(16000, 1000000, 0, 0, 1000000, 0, 0)] + [
            (16000 + i, 1000000, i * 15000, 0, 1000000 - i * 15000, 0, 0)
            for i in range(1, 63)
        ] + [(17000, 1000000, 0, 0, 1000000, 0, 0)]
        exposure.write_text(text_of(maximum, target=1000, available=1000))
        assert invoke("estimate", scenario, exposure).endswith(b"16062,465000\n17000,0\n")

        good = text_of(BASE)
        bad = [
            (good.replace("randomized", "observational"), b"requires declared randomized assignment"),
            (good.replace("10:00:00Z,100", "10:00:01Z,100"), b"future-dated cohort"),
            (good.replace("2026-11-15T08", "2026-11-12T08"), b"cohort is stale"),
            (good.replace("2026-11-19T09", "2026-11-17T09"), b"future-dated cohort"),
            (good.replace(",100,120,8000", ",100,99,8000"), b"target inventory"),
            (good.replace("20,7,2,11,0,0", "20,7,2,10,1,0"), b"unavailable or unresolved"),
            (good.replace("20,7,2,11,0,0", "20,7,2,10,0,1"), b"unavailable or unresolved"),
            (good.replace("20,7,2,11,0,0", "19,7,2,10,0,0"), b"each arm needs 20"),
            (good.replace("20,7,2,11,0,0", "20,7,2,10,0,0"), b"counts must reconcile"),
            (good.replace("17500,60", "16000,60"), b"prices must increase"),
            (good.replace("17500,60", "017500,60"), b"noncanonical"),
            (good.replace(",EUR,", ",USD,"), b"price basis mismatch"),
            (text_of(((16000, 20, 0, 0, 20, 0, 0), (17000, 20, 1, 0, 19, 0, 0))), b"no price response"),
            (text_of(BASE[:1]), b"requires 2..64 distinct price arms"),
        ]
        for raw, expected in bad:
            exposure.write_text(raw)
            invoke("estimate", scenario, exposure, error=expected)
        exposure.write_text(good)
        invoke("estimate", FIXTURES / "scenario.csv", exposure, error=b"single-room, single-night")

        # Real existing optimizer, no competitor input, unchanged v3 archive.
        optimizer_env = {
            "FINPRED_HOME": str(work / "recommendations"),
            "FINPRED_EXE": os.environ.get("FINPRED_EXE", str(ROOT / "build" / "dev" / "finpred")),
            "FINPRED_MODE": "recommendation",
            "FINPRED_STRATEGY": str(ROOT / "strategies" / "contribution.ottomat"),
            "FINPRED_OFFERS": str(work / "absent-offers.csv"),
        }
        summary = invoke("--scenario", scenario, "--valuation", FIXTURES / "valuation.csv",
                         "--demand", demand, executable=ROOT / "bin" / "yieldcraft",
                         env_override=optimizer_env)
        assert b"recommendation_minor=17500\n" in summary and b"published=false\n" in summary
        run_id = dict(line.split(b"=", 1) for line in summary.splitlines())[b"run_id"].decode()
        run = work / "recommendations" / "runs" / f"{run_id}.txt"
        assert run.read_bytes().startswith(b"finpred-run@3,")
        assert invoke("replay", run_id, executable=ROOT / "bin" / "finpred",
                      env_override=optimizer_env) == b"replay_ok=true\n" + summary
    print("yieldcraft_demand_ok=true oracle_cases=25 optimizer_handoff=true")


if __name__ == "__main__":
    main()
