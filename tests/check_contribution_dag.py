#!/usr/bin/env python3
"""Compile the standalone contribution DAG and compare it to the current policy."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
SCENARIO = (FIX / "scenario.csv").read_bytes()
VALUATION = (FIX / "valuation.csv").read_bytes()
DEMAND = (FIX / "demand_contribution.csv").read_bytes()
CUTOFF = "2026-11-20T10:00:00Z"


def grid(*lines):
    return b"\n".join([*DEMAND.splitlines()[:4], *lines, b""])


def verify(raw, demand, valuation, expected_price):
    status, kind, *fields = raw.decode("ascii").splitlines()
    assert status == "ok" and kind == "pricing.contribution-decision-text@1"
    decision = {k: v for k, v in (field.split("=", 1) for field in fields if not field.startswith("candidate="))}
    meta = demand.splitlines()[2].decode("ascii").split(",")
    cost = int(meta[7])
    current, floor, cap, movement, _ = (int(x) for x in valuation.splitlines()[1].split(b",")[4:])
    low, high = max(floor, current - movement), min(cap, current + movement)
    expected = []
    candidates = []
    for row in demand.splitlines()[4:]:
        price, volume = map(int, row.split(b","))
        score = (price - cost) * volume
        feasible = low <= price <= high
        candidates.append(f"candidate={price},{volume},{score},{'feasible' if feasible else 'outside_guardrails'}")
        if feasible and score > 0:
            expected.append((score, -abs(price - current), -price, volume))
    score, _, negative_price, volume = max(expected)
    assert -negative_price == expected_price
    assert decision == {
        "currency": "EUR", "price_basis": "room_night", "published": "false",
        "price_minor": str(expected_price), "marginal_cost_minor": str(cost),
        "expected_room_nights_milli": str(volume), "expected_contribution_minor_milli": str(score),
        "scale": "1000", "feasible_floor_minor": str(low), "feasible_cap_minor": str(high),
        "method": meta[5], "evidence_blake3": meta[6], "observed_at": meta[1], "ingested_at": meta[2],
    }
    assert [field for field in fields if field.startswith("candidate=")] == candidates


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    with tempfile.TemporaryDirectory(prefix="finpred-contribution-dag-") as tmp:
        work = Path(tmp)
        exe = work / "contribution-dag"
        subprocess.run([
            sys.executable, mulib / "on1x/tools/on1x-build.py", ROOT / "tests/contribution_dag_consumer/main.on1x",
            "--backend", "c11", "--on1xc", compiler, "--mulib-root", mulib,
            "-I", ROOT / "source", "-I", ROOT / "strategies", "-o", exe,
        ], cwd=work, check=True)
        empty = work / "empty"
        empty.mkdir()

        def run(case, demand=DEMAND, valuation=VALUATION, scenario=SCENARIO, cutoff=CUTOFF):
            env = {**os.environ, "CASE": case, "CUTOFF": cutoff, "FINPRED_HOME": str(empty / "store")}
            for key, data in (("DEMAND", demand), ("VALUATION", valuation), ("SCENARIO", scenario)):
                path = work / f"{key}.csv"
                path.write_bytes(data)
                env[key] = str(path)
            result = subprocess.run([exe], cwd=empty, env=env, capture_output=True, timeout=15)
            assert result.returncode == 0 and not result.stderr and not list(empty.iterdir()), result
            return result.stdout

        narrow = VALUATION.replace(b",5000,500\n", b",300,500\n")
        large = VALUATION.replace(b",17500,16000,25000,5000,500\n", b",1000000000000,0,1000000000000,1000000000000,0\n")
        valid = [
            (DEMAND, VALUATION, 19000),
            (DEMAND.replace(b",8000\n", b",0\n"), VALUATION, 17500),
            (DEMAND.replace(b"19000,105000", b"19000,90000"), VALUATION, 17500),
            (DEMAND, narrow, 17500),
            (grid(b"16000,50000", b"18000,40000"), VALUATION, 18000),
            (grid(b"16500,21000", b"18500,17000"), VALUATION, 16500),
            (grid(b"0,1000000", b"1000000000000,1000000").replace(b",8000\n", b",0\n"), large, 10**12),
            (grid(*(f"{16000+i},1".encode() for i in range(64))), VALUATION, 16063),
            (DEMAND.replace(b"\n", b"\r\n"), VALUATION, 19000),
            (DEMAND.rstrip(b"\n"), VALUATION, 19000),
        ]
        for demand, valuation, optimum in valid:
            verify(run("parity", demand, valuation), demand, valuation, optimum)

        rejected_demand = [
            grid(b"17500,1000"),
            grid(b"15000,1000", b"22501,500"),
            grid(b"17500,0", b"19000,0"),
            grid(*(f"{16000+i},1".encode() for i in range(65))),
            DEMAND.replace(b",8000\n", b",25000\n"),
            DEMAND.replace(b"T09:30:00Z", b"T10:30:00Z"),
            DEMAND.replace(b"2026-11-20T08:30", b"2026-11-12T08:30"),
            DEMAND.replace(b"d29ce687", b"c29ce687"),
            DEMAND.replace(b"room_night", b"whole_stay", 1),
            DEMAND.replace(b"calibrated_booking_model", b"competitor_list_prices"),
            DEMAND.replace(b"17500,115000", b"16000,115000"),
            DEMAND.replace(b"17500,115000", b"17500,130000"),
            DEMAND.replace(b"15000,250000", b"15000,1000001"),
            DEMAND.replace(b"15000,250000", b"15000,0250000"),
            DEMAND.replace(b"15000,250000", b"15000,9223372036854775808"),
            DEMAND.replace(b"15000,250000", b"15000,\x01250000"),
            DEMAND.replace(b"15000,250000", b"15000,\"250000\""),
            DEMAND.replace(b"15000,250000", b"15000,250000,extra"),
            DEMAND.replace(b"15000,250000\n", b"15000,250000\r"),
            DEMAND.replace(b"marginal_cost_minor", b"cost_minor"),
        ]
        for demand in rejected_demand:
            assert run("reject", demand) == b"handler_failure\n", demand
        assert run("reject", b"x" * 8193) == b"input\n"
        assert run("reject", scenario=SCENARIO.replace(b"linear", b"other")) == b"handler_failure\n"
        assert run("reject", scenario=SCENARIO.replace(b"\n", b"\r\n")) == b"handler_failure\n"  # original digest
        assert run("reject", scenario=b"wrong\nshape\n") == b"handler_failure\n"
        conflict = VALUATION.replace(b",17500,16000,25000,5000,500\n", b",10000,16000,25000,300,500\n")
        assert run("reject", valuation=conflict) == b"handler_failure\n"
        assert run("reject", valuation=VALUATION.replace(b",500\n", b",9223372036854775808\n")) == b"handler_failure\n"
        assert run("reject", cutoff="2026-11-20T09:59:59Z") == b"handler_failure\n"
        assert run("reject", cutoff="not UTC") == b"input\n"
        assert run("analysis") == b"unknown_handler\n"
        assert run("disabled") == b"unknown_handler\n"
        assert run("wrong-pin") == b"handler_failure\n"
        assert run("budget") == b"budget\n"
    print(f"contribution_dag_ok=true parity={len(valid)} replay={len(valid)} rejects={len(rejected_demand)+11}")


if __name__ == "__main__":
    main()
