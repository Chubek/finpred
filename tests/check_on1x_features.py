#!/usr/bin/env python3
"""Check C11 execution and compiler diagnostics for On1x language features."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/on1x_features_consumer/main.on1x"
EXPECTED = b"present=some:0\nmissing=none\npayload=$label ${label}\n{} {\n"


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    with tempfile.TemporaryDirectory(prefix="finpred-on1x-features-") as tmp:
        def build(source, exe):
            return subprocess.run([
                sys.executable, sdk / "on1x/tools/on1x-build.py", source,
                "--backend", "c11", "--on1xc", compiler, "--mulib-root", sdk, "-o", exe,
            ], cwd=tmp, capture_output=True, timeout=60)

        exe = Path(tmp) / "consumer"
        built = build(FIXTURE, exe)
        if built.returncode != 0:
            raise ValueError(f"consumer build exit {built.returncode}: {built.stdout!r} {built.stderr!r}")
        run = subprocess.run([exe], cwd=tmp, capture_output=True, timeout=15)
        if (run.returncode, run.stdout, run.stderr) != (0, EXPECTED, b""):
            raise ValueError(f"consumer exit {run.returncode}: {run.stdout!r} {run.stderr!r}")

        fixture = FIXTURE.read_text(encoding="ascii")
        for name, old, new, diagnostic in (
            ("unbound_interpolation", "$label=$zero", "$unbound_label=$zero",
             b"undefined variable: unbound_label"),
            ("nonexhaustive_option", '    None() => "none",\n', "", b"non-exhaustive match"),
        ):
            if fixture.count(old) != 1:
                raise ValueError(f"{name}: expected exactly one fixture substitution")
            source = Path(tmp) / f"{name}.on1x"
            source.write_text(fixture.replace(old, new), encoding="ascii")
            rejected = Path(tmp) / name
            built = build(source, rejected)
            if built.returncode <= 0 or diagnostic not in built.stderr or rejected.exists():
                raise ValueError(f"{name} build exit {built.returncode}: {built.stdout!r} {built.stderr!r}")
    print("on1x_features_ok=true executions=1 compiler_rejections=2")


if __name__ == "__main__":
    main()
