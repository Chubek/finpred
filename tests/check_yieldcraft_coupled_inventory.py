#!/usr/bin/env python3
"""Compare every small robust state and the offline baselines to a separate oracle."""
from fractions import Fraction as Q
from functools import lru_cache
from itertools import product
import csv
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
LEGS = {1: (1, 0), 2: (0, 1), 3: (1, 1)}


def input_csv(a, b, cost, salvage, baseline, periods):
    return (
        "pricing.coupled-inventory-input@1\n"
        "currency,first_night,second_night,stock_a,stock_b,cost_a_minor,cost_b_minor,"
        "terminal_a_minor,terminal_b_minor,baseline_product,baseline_price_minor\n"
        f"EUR,2028-02-29,2028-03-01,{a},{b},{cost[0]},{cost[1]},{salvage[0]},"
        f"{salvage[1]},{baseline[0]},{baseline[1]}\n"
        "period,product,price_minor,low_bps,nominal_bps,high_bps\n"
        + "".join(",".join(map(str, (t, *arm))) + "\n"
                  for t, arms in enumerate(periods, 1) for arm in arms)
    )


def oracle(a, b, cost, salvage, baseline, periods):
    """Exhaustively branch on all policies and endpoint distributions, with Fractions."""
    def terminal(a, b):
        return (a * salvage[0] + b * salvage[1]) * 1000

    def value(arm, no_sale, sale, objective):
        if arm is None:
            return Q(no_sale)
        k, price, low, mid, high = arm
        da, db = LEGS[k]
        sale += (price - da * cost[0] - db * cost[1]) * 1000
        probabilities = [mid] if objective == "nominal" else [low, high]
        return min(Q(sale * q + no_sale * (10000 - q), 10000) for q in probabilities)

    def quantize(v):
        return (-1 if v < 0 else 1) * int(abs(v) + Q(1, 2))

    def arms(t, a, b):
        for arm in periods[t]:
            da, db = LEGS[arm[0]]
            if a >= da and b >= db:
                yield arm, (a-da, b-db)

    @lru_cache(None)
    def possibilities(t, a, b, objective):
        if t == len(periods):
            return [(None, Q(terminal(a, b)))]
        unchanged = {quantize(v) for _, v in possibilities(t+1, a, b, objective)}
        payoffs = [(None, Q(h)) for h in unchanged]
        for arm, (na, nb) in arms(t, a, b):
            sold = {quantize(v) for _, v in possibilities(t+1, na, nb, objective)}
            payoffs.extend((arm, value(arm, h, s, objective)) for h, s in product(unchanged, sold))
        return payoffs

    def select(t, a, b, name):
        if name == "fixed":
            return next((arm for arm, _ in arms(t, a, b) if arm[:2] == baseline), None)
        return min(possibilities(t, a, b, name), key=lambda x: (-x[1], x[0] or ()))[0]

    @lru_cache(None)
    def evaluate(t, a, b, policy, metric):
        if t == len(periods):
            return terminal(a, b)
        arm = select(t, a, b, policy)
        unchanged = evaluate(t+1, a, b, policy, metric)
        if arm is None:
            return unchanged
        da, db = LEGS[arm[0]]
        return quantize(value(arm, unchanged, evaluate(t+1, a-da, b-db, policy, metric), metric))

    def summary(t, a, b, policy):
        return {metric + "_minor_milli": evaluate(t, a, b, policy, metric)
                for metric in ("nominal", "worst")}

    states = []
    for t, _ in enumerate(periods):
        for sa, sb in product(range(a+1), range(b+1)):
            arm = select(t, sa, sb, "worst")
            fields = ("product", "price_minor", "low_bps", "nominal_bps", "high_bps")
            states.append({"period": t+1, "stock_a": sa, "stock_b": sb,
                           "value": summary(t, sa, sb, "worst"),
                           "action": "hold" if arm is None else "offer",
                           "offer": None if arm is None else dict(zip(fields, arm))})
    initial = {p: summary(0, a, b, "worst" if p == "robust" else p)
               for p in ("robust", "nominal", "fixed")}
    initial["hold"] = dict.fromkeys(("nominal_minor_milli", "worst_minor_milli"), terminal(a, b))
    return {"kind": "pricing.coupled-inventory-policy", "version": 1, "published": False,
            "comparison": "modeled_not_observed", "currency": "EUR", "scale": 1000,
            "first_night": "2028-02-29", "second_night": "2028-03-01", "stock_a": a, "stock_b": b,
            "cost_a_minor": cost[0], "cost_b_minor": cost[1], "terminal_a_minor": salvage[0],
            "terminal_b_minor": salvage[1], "periods": len(periods),
            "baseline_product": baseline[0], "baseline_price_minor": baseline[1],
            "initial": initial, "robust_states": states}


def main():
    tmp = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1"}
    schema = json.loads((ROOT / "contracts/pricing.coupled-inventory-policy@1.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    mulib = Path(env.get("MULIB_ROOT") or ROOT / "third_party/mulib").resolve()
    compiler = Path(env.get("ON1XC") or ROOT / "build/mulib/on1x/on1xc").resolve()
    with tempfile.TemporaryDirectory(prefix="coupled-inventory-", dir=tmp) as directory:
        work = Path(directory)
        exe = work / "planner"
        source = work / "input.csv"
        subprocess.run([sys.executable, mulib / "on1x/tools/on1x-build.py",
                        ROOT / "plugins/yieldcraft/coupled_inventory_main.on1x",
                        "--backend", "c11", "--cc", env.get("CC", "cc"), "--on1xc", compiler,
                        "--mulib-root", mulib, "-I", ROOT / "source", "-I", ROOT / "strategies",
                        "-I", ROOT, "-o", exe],
                       check=True, cwd=work, env=env, timeout=120)

        def invoke(raw, error=None, mode="evaluate"):
            source.write_bytes(raw.encode("ascii"))
            before = set(work.iterdir())
            proc = subprocess.run([exe], cwd=work, env={**env,
                                  "YIELDCRAFT_INVENTORY_PLAN_INPUT": str(source),
                                  "YIELDCRAFT_INVENTORY_PLAN_MODE": mode},
                                  capture_output=True, timeout=20)
            assert set(work.iterdir()) == before
            assert source.read_bytes() == raw.encode("ascii")
            if error is not None:
                assert proc.returncode > 0 and error in proc.stdout + proc.stderr, proc
                assert not proc.stdout.startswith(b"{"), proc
                return None
            assert proc.returncode == 0 and proc.stdout.endswith(b"\n"), proc
            if mode == "compare-csv":
                rows = list(csv.reader(proc.stdout.decode("ascii").splitlines()))
                assert len(rows) == 5 and all(len(row) == 16 for row in rows)
                return list(csv.DictReader(proc.stdout.decode("ascii").splitlines()))
            return json.loads(proc.stdout)

        unit = (1, 120, 10000, 10000, 10000)
        # Early singleton consumes one leg of a more valuable later bundle.
        coupled = (1, 1, (20, 30), (0, 0), unit[:2],
                   [[unit], [unit, (3, 400, 10000, 10000, 10000)]])
        # Known tradeoff: higher nominal chance vs protection against low chance.
        risk = (1, 1, (0, 0), (0, 0), unit[:2],
                [[unit, (3, 400, 100, 9000, 10000)]])
        # Worst case for an unprofitable fixed sale is the HIGH endpoint (negative half).
        loss = (1, 0, (1, 0), (0, 0), (1, 0), [[(1, 0, 0, 4, 5)]])
        # A bundle cannot sell if either leg is sold out even with high demand.
        stockout = (1, 0, (0, 0), (0, 0), (3, 500), [[unit, (3, 500, 10000, 10000, 10000)]])
        # Exact ties prefer hold, then product order, then lower price.
        ties = (1, 1, (0, 0), (120, 0), unit[:2],
                [[unit, (2, 10, 10000, 10000, 10000), (2, 20, 5000, 5000, 5000),
                  (3, 130, 10000, 10000, 10000)]])
        cases = [coupled, risk, loss, stockout, ties]
        rng = random.Random(20281112)
        for _ in range(32):
            periods = []
            for _ in range(rng.randint(1, 3)):
                periods.append([(k, 45 if k == 1 else rng.randint(0, 150),
                                 *sorted(rng.choices(range(10001), k=3))) for k in (1, 2, 3)])
            cases.append((rng.randrange(3), rng.randrange(3), (rng.randrange(65), rng.randrange(65)),
                          (rng.randrange(25), rng.randrange(25)), (1, 45), periods))
        for index, fixture in enumerate(cases):
            raw = input_csv(*fixture)
            got = invoke(raw.replace("\n", "\r\n") if index % 2 else raw)
            validator.validate(got)
            assert got == oracle(*fixture), (index, got, oracle(*fixture))
            initial = got["initial"]
            assert initial["robust"]["worst_minor_milli"] == max(x["worst_minor_milli"] for x in initial.values())
            assert initial["nominal"]["nominal_minor_milli"] == max(x["nominal_minor_milli"] for x in initial.values())
        assert invoke(input_csv(*coupled))["robust_states"][3]["action"] == "hold"
        assert invoke(input_csv(*risk))["initial"]["robust"] == {
            "nominal_minor_milli": 120000, "worst_minor_milli": 120000}
        assert invoke(input_csv(*loss))["initial"]["fixed"] == {"nominal_minor_milli": 0, "worst_minor_milli": -1}
        for given in (risk, loss):
            raw = input_csv(*given).replace("\n", "\r\n")
            rows = invoke(raw, mode="compare-csv")
            assert [row["policy"] for row in rows] == ["robust", "nominal", "fixed", "hold"]
            expected = oracle(*given)["initial"]
            for row in rows:
                assert {k: int(row[k]) for k in expected[row["policy"]]} == expected[row["policy"]]
                assert row["evidence"] == "modeled_not_observed" and row["currency"] == "EUR"
                assert row["baseline_price_minor"] == str(given[4][1])

        money = 10**10
        largest = [(k, money-3+i, 10000, 10000, 10000) for k in (1, 2, 3) for i in range(4)]
        full = invoke(input_csv(6, 6, (0, 0), (money, money), (3, money), [largest] * 8))
        assert len(full["robust_states"]) == 392
        assert full["initial"]["robust"]["worst_minor_milli"] == 12 * money * 1000
        assert full["initial"]["fixed"]["worst_minor_milli"] == 6 * money * 1000

        valid = input_csv(*risk)
        malformed = [
            ("x" * 8193, b"outside byte profile"),
            (valid.replace("2028-02-29", "2027-02-29"), b"valid night dates"),
            (valid.replace("EUR,", "USD,"), b"requires EUR"),
            (valid.replace("120\nperiod", "121\nperiod"), b"exact support"),
            (valid.replace("120\nperiod", "0120\nperiod"), b"noncanonical"),
            (valid.replace("1,3,400", "2,3,400"), b"exact support"),
            (valid.replace("1,3,400", "3,3,400"), b"invalid period"),
            (valid.replace("100,9000,10000", "100,100,99"), b"unordered"),
            (valid.replace("100,9000,10000", "100,9000,10001"), b"out-of-range integer"),
            (valid + "1,1,120,0,0,0\n", b"unordered"),
            (valid + "1,3,401,101,9000,10000\n", b"unordered"),
            (valid.replace("1,1,120,10000,10000,10000", "1,0,120,10000,10000,10000"), b"invalid period"),
            (valid.replace("03-01,1,1", "03-01,7,1"), b"out-of-range integer"),
        ]
        for raw, error in malformed:
            invoke(raw, error)
        invoke(valid, b"unsupported mode", mode="publish")
    print(f"yieldcraft_coupled_inventory_ok=true exhaustive_cases={len(cases)} invalid_cases={len(malformed)+1}")


if __name__ == "__main__":
    main()
