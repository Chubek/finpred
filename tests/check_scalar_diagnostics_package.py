#!/usr/bin/env python3
"""Compile the package without FinPRED core modules, then check its boundary."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()

with tempfile.TemporaryDirectory(prefix="finpred-diagnostics-package-") as tmp:
    exe = Path(tmp) / "consumer"
    subprocess.run([
        sys.executable, sdk / "on1x/tools/on1x-build.py",
        ROOT / "tests/scalar_diagnostics_consumer/main.on1x", "--backend", "c11",
        "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT, "-o", exe,
    ], cwd=tmp, check=True, timeout=90)
    for case in ("valid", "negative", "oversize"):
        result = subprocess.run([exe], cwd=tmp, env={"DIAGNOSTIC_CASE": case},
                                capture_output=True, timeout=10)
        if case == "valid":
            assert (result.returncode, result.stdout, result.stderr) == (0, b"29\n29\n0\n1000000000000\n", b""), result
        else:
            assert result.returncode > 0 and not result.stdout, result
            assert b"scalar diagnostics: level outside input range" in result.stderr, result
print("scalar_diagnostics_package_ok=true results=4 rejected=2")
