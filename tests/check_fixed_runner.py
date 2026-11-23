#!/usr/bin/env python3
"""Build a native On1x host and exercise the fixed runner without CLI prechecks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    denied = ("algorithm_effect", "output_effect", "gate_edge", "gate_order", "unknown_profile", "execution")
    with tempfile.TemporaryDirectory(prefix="finpred-fixed-runner-") as tmp:
        exe = Path(tmp) / "consumer"
        subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                        ROOT / "tests/fixed_runner_consumer/main.on1x", "--backend", "c11",
                        "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT, "-o", exe],
                       cwd=tmp, check=True)
        empty = Path(tmp) / "empty"
        empty.mkdir()
        env = {**os.environ, "FINPRED_HOME": str(empty / "store"),
               **{f"RUNNER_{key.upper()}": str(ROOT / f"fixtures/{key}.csv")
                  for key in ("scenario", "offers", "valuation")}}
        for case in (*denied, "premium"):
            result = subprocess.run([exe], env={**env, "RUNNER_CASE": case}, cwd=empty,
                                    capture_output=True, timeout=15)
            if case == "premium":
                ok = result.returncode == 0 and result.stdout == b"7500\n19000\n"
            else:
                ok = (result.returncode > 0 and not result.stdout
                      and b"invalid fixed plan or capability denied" in result.stderr)
            if not ok or list(empty.iterdir()):
                raise AssertionError(f"{case}: {result}")
    print(f"fixed_runner_ok=true denied={len(denied)} native_profile=premium-p75")


if __name__ == "__main__":
    main()
