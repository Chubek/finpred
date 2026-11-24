#!/usr/bin/env python3
"""Reproduce a single-vintage ECB German long-term yield diagnostic offline."""

import csv
from fractions import Fraction
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

from check_price_backtest import ROOT, oracle_folds, oracle_metrics, series

DATA = ROOT / "research/ecb-de-yield/monthly-de-long-term-yield-2023-2025.csv"
TRANSFER_SHA = "f094f09753355aeb1b6f9215254c9f60deb1698f536dce738b2e16f523937a8d"
DIMS = ["IRS.M.DE.L.L40.CI.0000.EUR.N.Z", "M", "DE", "L", "L40", "CI", "0000", "EUR", "N", "Z"]


def inputs():
    local = DATA.read_bytes()
    assert sha256(local.replace(b"\n", b"\r\n")).hexdigest() == TRANSFER_SHA
    reader = csv.reader(io.StringIO(local.decode("ascii")))
    assert next(reader) == ["KEY", "FREQ", "REF_AREA", "IR_TYPE", "TR_TYPE", "MATURITY_CAT",
                            "BS_COUNT_SECTOR", "CURRENCY_TRANS", "IR_BUS_COV", "IR_FV_TYPE",
                            "TIME_PERIOD", "OBS_VALUE"]
    result = []
    for i, row in enumerate(reader):
        assert row[:-1] == DIMS + [f"{2023 + i // 12}-{1 + i % 12:02d}"]
        ticks = Fraction(row[-1]) * 1000
        assert ticks >= 0 and ticks.denominator == 1
        result.append(int(ticks))
    assert len(result) == 36
    return result


def main():
    prices = inputs()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("FINPRED_") or key in ("FINPRED_EXE", "FINPRED_BUILD_DIR")}
    with tempfile.TemporaryDirectory(prefix="finpred-ecb-yield-") as tmp:
        work = Path(tmp)
        history = work / "rates.csv"
        frozen = series(prices)
        history.write_bytes(frozen)
        env["FINPRED_HOME"] = str(work / "pricing")
        env["FINPRED_FORECAST_HOME"] = str(work / "forecast")
        reports = []
        for horizon in (1, 3):
            result = subprocess.run([ROOT / "bin/finpred", "price-backtest", "ema",
                                     str(horizon), "24", history],
                                    cwd=work, env=env, capture_output=True, timeout=10, check=True)
            assert not result.stderr
            actual = json.loads(result.stdout)
            folds = list(oracle_folds(prices, "ema", horizon, 24, 0))
            assert actual["folds"] == folds
            assert actual["scored"] == 12 and actual["published"] is False
            assert actual["metrics"] == oracle_metrics(folds, "point_minor")
            assert actual["baseline_metrics"] == oracle_metrics(folds, "baseline_minor")
            reports.append(dict(horizon_months=horizon, scored=actual["scored"],
                                ema_mae_ticks=actual["metrics"]["mae_minor"],
                                naive_mae_ticks=actual["baseline_metrics"]["mae_minor"]))
        assert list(work.iterdir()) == [history] and history.read_bytes() == frozen
    print("ecb_de_yield_study_ok=true " + json.dumps(dict(
        unit="0.001 percentage point", vintage_scope="single", matched_2025=reports), separators=(",", ":")))


if __name__ == "__main__":
    main()
