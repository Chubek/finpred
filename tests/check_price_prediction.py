#!/usr/bin/env python3
"""Exercise the main host's read-only MuLIB price prediction command."""
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = b"period,price_minor\n"


def series(prices):
    return HEADER + b"".join(f"{i},{price}\n".encode() for i, price in enumerate(prices))


def main():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("FINPRED_") or key in {"FINPRED_EXE", "FINPRED_BUILD_DIR"}}
    with tempfile.TemporaryDirectory(prefix="finpred-price-prediction-") as tmp:
        work = Path(tmp)
        history = work / "history prices.csv"
        absent = work / "store"
        env |= {"FINPRED_HOME": str(absent), "FINPRED_FORECAST_HOME": str(absent),
                "FINPRED_SCENARIO": str(absent), "FINPRED_OFFERS": str(absent),
                "FINPRED_VALUATION": str(absent)}

        def command(*args):
            return subprocess.run([ROOT / "bin/finpred", "price-predict", *args],
                                  cwd=work, env=env, capture_output=True, timeout=10)

        def positive(model, horizon, point, *, season=0, dispersion=None, count=4):
            args = [model, str(horizon), history.name] + ([str(season)] if season else [])
            result = command(*args)
            assert result.returncode == 0 and not result.stderr, result
            assert json.loads(result.stdout) == {
                "kind": "analysis.price-prediction", "version": 1, "published": False,
                "model": model, "observations": count, "horizon": horizon, "season": season,
                "point_minor": point, "dispersion_minor": dispersion,
            }, result
            assert command(*args).stdout == result.stdout

        def negative(*args, error):
            result = command(*args)
            assert result.returncode > 0 and not result.stdout and error in result.stderr, result

        history.write_bytes(series([100, 130, 125, 160]))
        positive("naive", 2, 160)
        positive("ema", 2, 140)
        positive("drift", 2, 200)
        positive("seasonal", 3, 125, season=2)
        positive("holt", 2, 216)

        # Independent arithmetic for two shared rolling one-step origins.
        points = [160, 140, 200]
        errors = [Decimal("20"), Decimal("25"), Decimal("28.75")]
        weights = [1 / (error + Decimal("1e-9")) for error in errors]
        mean = sum(x * w for x, w in zip(points, weights)) / sum(weights)
        sd = (sum(w * (x - mean)**2 for x, w in zip(points, weights)) / sum(weights)).sqrt()
        positive("ensemble", 2, round(mean), dispersion=round(sd))
        for model, horizon, extra in (("unknown", "1", []), ("naive", "0", []),
                                      ("naive", "366", []), ("naive", "01", []),
                                      ("naive", "-1", []), ("seasonal", "1", ["1"])):
            negative(model, horizon, history.name, *extra, error=b"invalid-request")
        negative("seasonal", "1", history.name, "5", error=b"model-rejected")
        negative("seasonal", "1", history.name, error=b"usage:")
        negative("ema", "1", history.name, "2", error=b"usage:")
        negative("naive", "1", "missing.csv", error=b"history file missing")

        history.write_bytes(series([0, 1]))
        positive("ema", 1, 1, count=2)  # +0.5 rounds up, not to even.
        negative("ensemble", "1", history.name, error=b"model-rejected")
        history.write_bytes(series([10, 0]))
        positive("drift", 2, 0, count=2)
        negative("holt", "2", history.name, error=b"model-rejected")
        history.write_bytes(series([0]))
        positive("naive", 1, 0, count=1)
        negative("drift", "1", history.name, error=b"model-rejected")
        history.write_bytes(series([100] * 3))
        positive("ensemble", 365, 100, dispersion=0, count=3)
        history.write_bytes(series([10**12] * 256))
        positive("naive", 365, 10**12, count=256)
        history.write_bytes(series([0, 10**12]))
        positive("drift", 365, 366 * 10**12, count=2)

        for invalid in (
            HEADER, b"price_minor\n0\n", HEADER + b"1,100\n", HEADER + b"0,100\n2,101\n",
            HEADER + b"0,100\n0,101\n", HEADER + b"0,100\n1,101", HEADER + b"0,100\r\n",
            HEADER + b"00,100\n", HEADER + b"0,01\n", HEADER + b"0,-1\n", HEADER + b"0,+1\n",
            HEADER + b"0,1000000000001\n", HEADER + b"0,18446744073709551616\n",
            HEADER + b"0,1,2\n", series(range(257)), HEADER + b"\n",
        ):
            history.write_bytes(invalid)
            negative("naive", "1", history.name, error=b"invalid-history")
        history.write_bytes(HEADER + b"0,1\0\n")
        negative("naive", "1", history.name, error=b"NUL-free")
        history.write_bytes(b"x" * 5001)
        negative("naive", "1", history.name, error=b"outside bounded profile")
        assert list(work.iterdir()) == [history]
    print("price_prediction_ok=true models=6")


if __name__ == "__main__":
    main()
