#!/usr/bin/env python3
"""Compare the compiled ordered-series backtest to an independent oracle."""
from collections import Counter
import csv
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MAX = 10**12
HEADER = b"period,price_minor\n"
ECB = ROOT / "research/ecb-fx/monthly-usd-per-eur-2022-2024.csv"


def ecb_rates():
    raw = ECB.read_bytes()
    source = raw.replace(b"\n", b"\r\n")  # Exact transfer bytes; checkout stores LF.
    assert sha256(source).hexdigest() == "e8fe31fccc7d53fb3ab772d38257dab60fb5f6d8b44ca987ee913325f84133a6"
    rows = list(csv.reader(io.StringIO(raw.decode("ascii"))))
    assert rows[0] == ["KEY", "FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE",
                       "EXR_SUFFIX", "TIME_PERIOD", "OBS_VALUE"]
    assert len(rows) == 37
    prices = []
    for i, row in enumerate(rows[1:]):
        assert row[:-1] == ["EXR.M.USD.EUR.SP00.A", "M", "USD", "EUR", "SP00", "A",
                            f"{2022 + i // 12}-{1 + i % 12:02d}"]
        ticks = Decimal(row[-1]) * 1_000_000
        prices.append(int(ticks.to_integral_value(rounding=ROUND_HALF_UP)))
    return prices


def series(prices):
    return HEADER + b"".join(f"{i},{v}\n".encode() for i, v in enumerate(prices))


def estimate(history, model, horizon, season):
    previous = history[-1]
    if model == "naive":
        return previous
    if model == "ema":
        level = history[0]
        for observation in history[1:]:
            level = (observation + level) / 2
        return level
    if model == "drift":
        return max(0, previous + horizon * (previous - history[0]) / (len(history) - 1))
    if model == "seasonal":
        return history[-season:][(horizon - 1) % season]
    if model == "holt":
        level, trend = history[0], history[1] - history[0]
        for observation in history[1:]:
            new_level = (observation + level + trend) / 2
            trend = (new_level - level + 4 * trend) / 5
            level = new_level
        return level + horizon * trend
    assert model == "ensemble", model
    weighted, weights = 0, 0
    for member in ("naive", "ema", "drift"):
        errors = [
            abs(estimate(history[:i], member, 1, 0) - value)
            for i, value in enumerate(history) if i >= 2
        ]
        weight = 1 / (sum(errors) / len(errors) + Fraction(1, 10**9))
        weighted += weight * estimate(history, member, horizon, 0)
        weights += weight
    return weighted / weights


def oracle_folds(prices, model, horizon, first, season):
    minimum = {"drift": 2, "holt": 2, "ensemble": 3, "seasonal": season}.get(model, 1)
    for target in range(first, len(prices)):
        origin = target - horizon
        count = origin + 1
        point = None
        if count < minimum:
            state = "insufficient_training"
        else:
            forecast = estimate(list(map(Fraction, prices[:count])), model, horizon, season)
            state = "model_rejected"
            if forecast >= 0:
                point = int(forecast + Fraction(1, 2))
                state = "scored"
        yield dict(target=target, origin=origin, training_count=count, state=state,
                   point_minor=point, actual_minor=prices[target], baseline_minor=prices[origin])


def oracle_metrics(folds, field):
    pairs = [(row[field], row["actual_minor"]) for row in folds if row["state"] == "scored"]
    if not pairs:
        return dict.fromkeys(("mae_minor", "mse_minor_squared", "rmse_minor", "wape", "bias_minor"))
    errors = [point - actual for point, actual in pairs]
    n = len(errors)
    absolute = sum(map(abs, errors))
    square = sum(error * error for error in errors)
    total_actual = sum(actual for _, actual in pairs)
    with localcontext() as ctx:
        ctx.prec = 80
        rmse = (Decimal(square) / n).sqrt().quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    def ratio(a, b):
        return {"numerator": str(a), "denominator": b}

    return dict(mae_minor=ratio(absolute, n), mse_minor_squared=ratio(square, n),
                rmse_minor=str(rmse), wape=ratio(absolute, total_actual) if total_actual else None,
                bias_minor=ratio(sum(errors), n))


def main():
    schema = json.loads((ROOT / "contracts/analysis.price-backtest@1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FINPRED_") or k in ("FINPRED_EXE", "FINPRED_BUILD_DIR")}
    tmp = Path(os.environ.get("TMPDIR") or (ROOT / "build/tmp")).resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finpred-price-backtest-", dir=tmp) as directory:
        work = Path(directory)
        history = work / "price history.csv"
        env |= {"FINPRED_HOME": str(work / "pricing"), "FINPRED_FORECAST_HOME": str(work / "forecast")}

        def invoke(*args):
            return subprocess.run([ROOT / "bin/finpred", "price-backtest", *args], cwd=work,
                                  env=env, capture_output=True, timeout=10)

        def check(prices, model, horizon, first, season=0):
            original = series(prices)
            history.write_bytes(original)
            args = [model, str(horizon), str(first), history.name] + ([str(season)] if season else [])
            result = invoke(*args)
            assert result.returncode == 0 and not result.stderr, result
            actual = json.loads(result.stdout)
            validator.validate(actual)
            folds = list(oracle_folds(prices, model, horizon, first, season))
            states = Counter(row["state"] for row in folds)
            assert actual == dict(
                kind="analysis.price-backtest", version=1, published=False, scope="ordered_series",
                model=model, baseline="naive", observations=len(prices), horizon=horizon, season=season,
                first_target=first, expected=len(folds), scored=states["scored"],
                insufficient_training=states["insufficient_training"],
                model_rejected=states["model_rejected"], folds=folds,
                metrics=oracle_metrics(folds, "point_minor"), baseline_metrics=oracle_metrics(folds, "baseline_minor"),
            ), actual
            assert result.stdout == (json.dumps(actual, separators=(",", ":")) + "\n").encode()
            assert invoke(*args).stdout == result.stdout
            assert list(work.iterdir()) == [history] and history.read_bytes() == original
            return actual

        data = [100, 132, 127, 160, 151, 178, 164, 204, 198]
        for model in ("naive", "ema", "drift", "seasonal", "holt", "ensemble"):
            for horizon in (1, 3):
                check(data, model, horizon, horizon, 2 if model == "seasonal" else 0)
        check([10, 0, 0], "holt", 1, 1)  # No paired metrics for entirely unscored folds.
        check([10, 0, 0, 20, 21], "holt", 1, 1)  # Partial coverage includes a model rejection.
        check([5, 0, 0], "naive", 1, 1)  # Nonzero error with undefined WAPE.
        check([0, 0], "naive", 1, 1)
        check([0, 0, 1, 1], "naive", 1, 2)  # Irrational RMSE (0.707).
        check([10, 12, 10], "naive", 1, 1)  # Signed bias cancellation.
        check([0, 1, 0], "ema", 1, 2)  # Score the same half-up rounded point as price-predict.
        assert int(check([0, MAX] * 128, "naive", 1, 1)["metrics"]["mse_minor_squared"]["numerator"]) > 2**63
        check([0, MAX] + [0] * 254, "drift", 254, 255)  # Very large prediction, square, and RMSE.
        empirical = check(ecb_rates(), "ema", 1, 24)
        assert empirical["scored"] == 12
        print("ecb_fx_diagnostic_ok=true empirical=true snapshot_vintage=single "
              f"scored=12 ema_mae={empirical['metrics']['mae_minor']['numerator']}/12 "
              f"naive_mae={empirical['baseline_metrics']['mae_minor']['numerator']}/12 unit=1e-6_USD/EUR")

        # Horizon leakage: for target 6 at h=3, periods 4 & 5 are not available.
        # The target/later suffix is not available either. Check ensemble (which
        # also fits weights), and contrast a mutation prior to that origin.
        for model in ("ema", "drift", "ensemble"):
            base = check(data, model, 3, 6)["folds"][0]
            gap = data[:4] + [9000, 15] + data[6:]
            assert check(gap, model, 3, 6)["folds"][0] == base
            future = data[:7] + [600, 500, 400]
            assert check(future, model, 3, 6)["folds"][0] == base
            target_only = data[:6] + [700] + data[7:]
            changed = check(target_only, model, 3, 6)["folds"][0]
            assert changed == (base | {"actual_minor": 700})
            earlier = [30] + data[1:]
            assert check(earlier, model, 3, 6)["folds"][0]["point_minor"] != base["point_minor"]
        # A held-out label can enter training at, but not before, its own period.
        before = check(data, "naive", 2, 4)["folds"]
        after = check(data[:4] + [999] + data[5:], "naive", 2, 4)["folds"]
        assert [a["point_minor"] != b["point_minor"] for a, b in zip(before, after)] == [False, False, True, False, False]

        def rejects(*args, err):
            result = invoke(*args)
            assert result.returncode and not result.stdout and err in result.stderr, result

        history.write_bytes(series(data))
        for model, horizon, first in (("bad", "1", "2"), ("naive", "0", "2"),
                                      ("naive", "3", "2"), ("naive", "1", "9"),
                                      ("naive", "1", "02"), ("naive", "1", "256"),
                                      ("naive", "365", "255")):
            rejects(model, horizon, first, history.name, err=b"invalid-request")
        rejects("seasonal", "1", "2", history.name, "1", err=b"invalid-request")
        rejects("seasonal", "1", "2", history.name, err=b"usage:")
        rejects("naive", "1", "2", history.name, "2", err=b"usage:")
        rejects("naive", "1", "2", "absent", err=b"history file missing")
        for bad in (HEADER, series(data)[:-1], HEADER + b"0,1\n2,2\n",
                    series(data) + b"9,0\0\n", series([MAX + 1] + data), series([0] * 257)):
            history.write_bytes(bad)
            rejects("naive", "1", "1", history.name,
                    err=b"NUL-free" if b"\0" in bad else b"invalid-history")
        assert list(work.iterdir()) == [history]
    print("price_backtest_ok=true independent_oracle=true horizon_leakage_checked=true")


if __name__ == "__main__":
    main()
