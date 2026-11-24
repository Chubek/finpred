#!/usr/bin/env python3
"""Seeded black-box price checks with exact arithmetic and malformed CSV mutations."""

from fractions import Fraction
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = b"period,price_minor\n"
SEED = 630943


def write_history(path, prices):
    path.write_bytes(HEADER + b"".join(f"{i},{price}\n".encode("ascii")
                                        for i, price in enumerate(prices)))


def expected(history, model, horizon, season):
    if model == "naive":
        return history[-1]
    if model == "seasonal":
        return history[-season + (horizon - 1) % season]
    if model == "ema":
        # Closed form of the 1/2 exponential smoother, with initial weight 2^-n.
        level = Fraction(history[0], 2 ** (len(history) - 1))
        level += sum(Fraction(price, 2 ** age) for age, price in enumerate(reversed(history[1:]), 1))
    else:
        assert model == "drift"
        level = max(0, history[-1] + Fraction(horizon * (history[-1] - history[0]), len(history) - 1))
    return int(level + Fraction(1, 2))


def mutations(rng, prices):
    # Each mutation breaks a required invariant while leaving other rows valid.
    for index in rng.sample(range(len(prices)), min(8, len(prices))):
        for bad_row in (f"0{index},{prices[index]}\n", f"{index},-{prices[index]}\n",
                        f"{index},{prices[index]},1\n", f"{index + 1},{prices[index]}\n"):
            yield HEADER + b"".join(
                (bad_row if i == index else f"{i},{value}\n").encode("ascii")
                for i, value in enumerate(prices)
            )


def main():
    rng = random.Random(SEED)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("FINPRED_") or key in ("FINPRED_EXE", "FINPRED_BUILD_DIR")}
    with tempfile.TemporaryDirectory(prefix="finpred-price-properties-") as tmp:
        work = Path(tmp)
        path = work / "prices.csv"
        env["FINPRED_HOME"] = str(work / "pricing")
        env["FINPRED_FORECAST_HOME"] = str(work / "forecast")

        def invoke(*args):
            return subprocess.run([ROOT / "bin/finpred", *map(str, args)], cwd=work,
                                  env=env, capture_output=True, timeout=10)

        def checked(*args):
            result = invoke(*args)
            assert result.returncode == 0 and not result.stderr, (SEED, args, result)
            return json.loads(result.stdout)

        for trial in range(24):
            model = ("naive", "ema", "drift", "seasonal")[trial % 4]
            # Small integers keep EMA exact in binary64. An even prefix
            # length gives drift an odd denominator, excluding half-minor ties.
            n = rng.randrange(4, 18, 2)
            horizon = rng.randrange(1, 9)
            season = rng.randrange(2, n + 1) if model == "seasonal" else 0
            extra = (season,) if season else ()
            history = [2000 + rng.randrange(0, 30) for _ in range(n)]
            labels = [rng.randrange(0, 10000) for _ in range(horizon)]
            point = expected(history, model, horizon, season)
            write_history(path, history)
            forecast = checked("price-predict", model, horizon, path.name, *extra)
            assert forecast["point_minor"] == point, (SEED, trial, forecast, point)
            shift = rng.randrange(1, 10000)
            write_history(path, [price + shift for price in history])
            assert checked("price-predict", model, horizon, path.name, *extra)["point_minor"] == point + shift

            write_history(path, history + labels)
            target = n + horizon - 1
            backtest = checked("price-backtest", model, horizon, target, path.name, *extra)
            assert backtest["folds"] == [
                {"target": target, "origin": n - 1, "training_count": n, "state": "scored",
                 "point_minor": point, "actual_minor": labels[-1], "baseline_minor": history[-1]}
            ], (SEED, trial, backtest)

        invalid = list(mutations(rng, history))
        for mutant in invalid:
            path.write_bytes(mutant)
            for cmd, rest in (("price-predict", ()), ("price-backtest", (1,))):
                result = invoke(cmd, "naive", 1, *rest, path.name)
                assert result.returncode > 0 and not result.stdout and b"invalid-history" in result.stderr, (
                    SEED, cmd, mutant, result
                )
        assert sorted(work.iterdir()) == [path]
    print(f"price_properties_ok=true seed={SEED} generated=24 malformed={len(invalid)}")


if __name__ == "__main__":
    main()
