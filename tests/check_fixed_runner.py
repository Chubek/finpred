#!/usr/bin/env python3
"""Exercise the fixed runner with a typed test policy and no plugin search path."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    denied = ("algorithm_effect", "output_effect", "gate_edge", "gate_order", "unknown_profile", "execution")
    gated = ("out_of_range", "over_budget", "negative_search")
    with tempfile.TemporaryDirectory(prefix="finpred-fixed-runner-") as tmp:
        exe = Path(tmp) / "consumer"
        subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                        ROOT / "tests/fixed_runner_consumer/main.on1x", "--backend", "c11",
                        "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-o", exe],
                       cwd=tmp, check=True)
        empty = Path(tmp) / "empty"
        empty.mkdir()
        large = Path(tmp) / "large.csv"
        large.write_bytes(b"x" * 2000001)
        env = {**os.environ, "FINPRED_HOME": str(empty / "store"),
               **{f"RUNNER_{key.upper()}": str(ROOT / f"fixtures/{key}.csv")
                  for key in ("scenario", "offers", "valuation")}}
        for case in (*denied, *gated, "large_offers", "premium"):
            inputs = {"RUNNER_OFFERS": str(large)} if case == "large_offers" else {}
            result = subprocess.run([exe], env=env | {"RUNNER_CASE": case} | inputs, cwd=empty,
                                    capture_output=True, timeout=15)
            if case == "premium":
                ok = result.returncode == 0 and result.stdout == b"7500\n18888\n" and not result.stderr
            else:
                diagnostic = b"outside validated limits" if case in gated else b"invalid fixed plan or capability denied"
                if case == "large_offers":
                    diagnostic = b"offers: source exceeds byte limit"
                ok = result.returncode > 0 and not result.stdout and diagnostic in result.stderr
            if not ok or list(empty.iterdir()):
                raise AssertionError(f"{case}: {result}")
    print(f"fixed_runner_ok=true denied={len(denied)} gated={len(gated)} oversized=1 plugin_free=true")


if __name__ == "__main__":
    main()
