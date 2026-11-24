#!/usr/bin/env python3
"""Non-gating wall-clock benchmark for the compiled price-backtest CLI."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import median
import subprocess
import tempfile
from time import perf_counter_ns

from check_price_properties import ROOT, write_history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    options = parser.parse_args()
    if not 2 <= options.repeat <= 30:
        parser.error("--repeat must be in 2..30")
    cases = []
    with tempfile.TemporaryDirectory(prefix="finpred-price-benchmark-") as tmp:
        scratch = Path(tmp)
        history = scratch / "prices.csv"
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("FINPRED_") or key in ("FINPRED_EXE", "FINPRED_BUILD_DIR")}
        env["FINPRED_HOME"] = str(scratch / "pricing")
        env["FINPRED_FORECAST_HOME"] = str(scratch / "forecast")

        for model in ("naive", "ensemble"):
            for size in (64, 256):
                write_history(history, [9000 + 23 * i + (i * i * 13 % 331) for i in range(size)])
                args = [ROOT / "bin/finpred", "price-backtest", model, "7", "16", history]
                elapsed = []
                outputs = set()
                for sample in range(options.repeat + 1):
                    start = perf_counter_ns()
                    proc = subprocess.run(args, cwd=scratch, env=env, capture_output=True,
                                          check=True, timeout=60)
                    duration = perf_counter_ns() - start
                    if proc.stderr:
                        raise RuntimeError(proc.stderr.decode(errors="replace"))
                    outputs.add(sha256(proc.stdout).hexdigest())
                    if sample:  # First call warms filesystem and executable caches.
                        elapsed.append(duration)
                result = json.loads(proc.stdout)
                if len(outputs) != 1 or result["scored"] != size - 16 or result["published"] is not False:
                    raise RuntimeError("benchmark did not produce stable, fully scored results")
                if sorted(scratch.iterdir()) != [history]:
                    raise RuntimeError("benchmark operation wrote unexpected files")
                cases.append(dict(model=model, observations=size, scored=result["scored"],
                                  horizon=7, output_sha256=outputs.pop(), samples_ns=elapsed,
                                  median_ns=round(median(elapsed)), min_ns=min(elapsed)))
    print(json.dumps(dict(benchmark="finpred.price-backtest", version=1,
                          includes_process_startup=True, cases=cases), indent=2))


if __name__ == "__main__":
    main()
