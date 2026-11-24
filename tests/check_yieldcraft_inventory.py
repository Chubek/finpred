#!/usr/bin/env python3
"""Compile the pure inventory policy and exhaustively enumerate small policy trees."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from fractions import Fraction


ROOT = Path(__file__).resolve().parents[1]


def csv_input(stock, cost, terminal, periods):
    return (
        "pricing.inventory-input@1\n"
        "initial_stock,unit_cost_minor,terminal_stock_value_minor\n"
        f"{stock},{cost},{terminal}\n"
        "period,price_minor,net_sale_bps\n"
        + "".join(f"{t},{p},{prob}\n" for t, arms in enumerate(periods, 1) for p, prob in arms)
    )


def exhaustive(stock, cost, terminal, periods):
    """Enumerate all continuation policy payoff values, not just the optimum."""

    def round_value(v):
        return int(v + Fraction(1, 2)) if v >= 0 else -int(-v + Fraction(1, 2))

    def options(t, s):
        if s == 0 or t == len(periods):
            yield (None, None), Fraction(s * terminal * 1000)
            return
        unchanged = {round_value(v) for _, v in options(t + 1, s)}
        spent = {round_value(v) for _, v in options(t + 1, s - 1)}
        for hi in unchanged:
            yield (None, None), Fraction(hi)
        for price, probability in periods[t]:
            q = Fraction(probability, 10000)
            for hi, lo in itertools.product(unchanged, spent):
                yield (price, probability), (1 - q) * hi + q * ((price - cost) * 1000 + lo)

    states = []
    for t, _ in enumerate(periods):
        for s in range(stock + 1):
            # The root tie rule does not depend on the ranking of continuations.
            (price, probability), value = min(options(t, s),
                                               key=lambda x: (-x[1], -1 if x[0][0] is None else x[0][0]))
            states.append({
                "period": t + 1, "stock": s, "expected_value_minor_milli": round_value(value),
                "action": "hold" if price is None else "offer", "price_minor": price,
                "net_sale_bps": probability,
            })
    return states


def main():
    tmp_root = Path(os.environ.get("TMPDIR") or ROOT / "build" / "tmp").resolve()
    tmp_root.mkdir(parents=True, exist_ok=True)
    sdk = Path(os.environ.get("MULIB_ROOT") or ROOT / "third_party" / "mulib").resolve()
    compiler = Path(os.environ.get("ON1XC") or ROOT / "build" / "mulib" / "on1x" / "on1xc").resolve()
    env = {**os.environ, "TMPDIR": str(tmp_root), "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="yieldcraft-inventory-", dir=tmp_root) as tmp:
        work = Path(tmp)
        exe = work / "consumer"
        empty = work / "no-files"
        empty.mkdir()
        subprocess.run([
            sys.executable, sdk / "on1x" / "tools" / "on1x-build.py",
            ROOT / "tests" / "yieldcraft_inventory_consumer" / "main.on1x",
            "--backend", "c11", "--cc", os.environ.get("CC", "cc"),
            "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT, "-o", exe,
        ], check=True, cwd=work, env=env, timeout=120)

        def invoke(raw, error=None):
            proc = subprocess.run([exe], cwd=empty, env={**env, "YIELDCRAFT_INVENTORY_INPUT": raw},
                                  capture_output=True, timeout=20)
            assert not list(empty.iterdir())
            if error is not None:
                assert proc.returncode > 0 and error in proc.stdout + proc.stderr, proc
                assert not proc.stdout.startswith(b"{"), proc
                return None
            assert proc.returncode == 0, proc
            assert proc.stdout.endswith(b"\n"), proc
            return json.loads(proc.stdout)

        tests = [
            (1, 0, 0, [[(120, 10000)], [(400, 10000)]]),  # Hold for later.
            (2, 0, 0, [[(120, 10000)], [(400, 10000)]]),  # Offer now only with enough stock.
            (1, 25, 200, [[(180, 10000), (225, 5000)], [(225, 10000)]]),  # Salvage ties hold.
            (1, 0, 0, [[(100, 10000), (200, 5000)]]),  # Offer tie favors lower price.
            (1, 0, 1, [[(2, 1)]]),  # Improvement just 0.1 milli: choose before rounding.
            (1, 5, 0, [[(1, 10000), (8, 0)]]),  # Negative and null margins never beat hold.
            (0, 2, 10, [[(50, 10000)], [(400, 10000)]]),  # Stockout is always hold.
            (1, 0, 0, [[(1, 5)]]),  # Exact positive half-up.
        ]
        rng = random.Random(15142)
        for _ in range(30):
            periods = [
                list(zip(sorted(rng.sample(range(0, 90), 2)),
                         sorted(rng.sample(range(0, 10001), 2), reverse=True)))
                for _ in range(rng.randint(1, 3))
            ]
            tests.append((rng.randint(1, 3), rng.randrange(10), rng.randrange(10), periods))
        for i, (s, c, v, periods) in enumerate(tests):
            raw = csv_input(s, c, v, periods)
            if i % 2:
                raw = raw.replace("\n", "\r\n")
            model = invoke(raw)
            want = exhaustive(s, c, v, periods)
            assert model == {
                "kind": "pricing.inventory-policy", "version": 1, "published": False, "scale": 1000,
                "initial_stock": s, "periods": len(periods), "unit_cost_minor": c,
                "terminal_stock_value_minor": v,
                "initial_expected_value_minor_milli": want[s]["expected_value_minor_milli"],
                "initial_expected_incremental_over_hold_minor_milli": want[s]["expected_value_minor_milli"] - s*v*1000,
                "states": want,
            }, (i, model, want)

        max_money = 10**10
        full = [[(max_money - k, 10000) for k in range(7, -1, -1)]] * 12
        out = invoke(csv_input(12, 0, 0, full))
        assert len(out["states"]) == 156
        assert out["initial_expected_value_minor_milli"] == 12 * max_money * 1000
        assert out["states"][12]["price_minor"] == max_money
        expensive = invoke(csv_input(12, max_money, max_money, [[(0, 10000)]] * 12))
        assert all(r["action"] == "hold" for r in expensive["states"])
        assert expensive["initial_expected_incremental_over_hold_minor_milli"] == 0

        invalid = [
            (csv_input(1, 0, 0, []), b"requires 1..12 periods"),
            (csv_input(13, 0, 0, [[(1, 0)]]), b"out-of-range integer"),
            (csv_input(1, 10**10+1, 0, [[(1, 0)]]), b"out-of-range integer"),
            (csv_input(1, 0, 0, [[(1, 10001)]]), b"out-of-range integer"),
            (csv_input(1, 0, 0, [[], [(1, 0)]]), b"periods must be contiguous"),
            (csv_input(1, 0, 0, [[(1, 0)], [], [(1, 0)]]), b"periods must be contiguous"),
            (csv_input(1, 0, 0, [[(i, 0) for i in range(9)]]), b"1..8 candidates"),
            (csv_input(1, 0, 0, [[(1, 2), (1, 1)]]), b"prices must increase"),
            (csv_input(1, 0, 0, [[(1, 1), (2, 2)]]), b"nonincreasing net-sale probabilities"),
            (csv_input(1, 0, 0, [[(1, 0)]] * 13), b"out-of-range integer"),
            (csv_input(1, 0, 0, [[(1, 0)]]).replace("1,1,0", "1,01,0"), b"noncanonical"),
            (csv_input(1, 0, 0, [[(1, 0)]]).replace("net_sale_bps", "competitor_percentile"), b"unexpected header"),
            ("x" * 8193, b"exceeds byte limit"),
        ]
        for raw, error in invalid:
            invoke(raw, error)
    print(f"yieldcraft_inventory_ok=true exhaustive_cases={len(tests)} invalid_cases={len(invalid)}")


if __name__ == "__main__":
    main()
