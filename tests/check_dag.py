#!/usr/bin/env python3
"""Exercise the native pure DAG entry point, including untrusted plan records."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib"))
compiler = os.environ.get("ON1XC", sdk / "build/on1x/on1xc")
with tempfile.TemporaryDirectory(prefix="finpred-dag-") as tmp:
    exe = Path(tmp) / "consumer"
    subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                    ROOT / "tests/dag_consumer/main.on1x", "--backend", "c11",
                    "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source",
                    "-o", exe], cwd=tmp, check=True)
    hi = "hi=maximum@1(first,second):42\n"
    lo = "lo=minimum@1(first,second):17\n"
    end = "spread=distance@1(hi,lo):25\n"
    for case, expected in [
        ("ok", "ok\nscalar.distance@1:25\n" + hi + lo + end),
        ("reverse", "ok\nscalar.distance@1:25\n" + lo + hi + end),
        ("ok", "ok\nscalar.distance@1:25\n" + hi + lo + end),
        ("short", "ok\nscalar.level@1:42\nlo=minimum@1(first,second):42\n"),
        ("limit", "ok\nscalar.level@1:42\n" + "".join(
            f"{name}=maximum@1({parent},second):42\n"
            for name, parent in zip("abcdefghijklmnop", ["first", *"abcdefghijklmno"]))),
        ("selectlimit", "ok\nscalar.level@1:42\na=distance@1(first,second):25\n" + "".join(
            f"{name}=select@1(a,{parent},first):42\n"
            for name, parent in zip("bcdefghijklmnop", ["second", *"bcdefghijklmno"]))),
        ("mode", "denied\n"), ("action", "unknown_handler\n"),
        ("version", "version\n"), ("unknown", "unknown_handler\n"),
        ("budget", "budget\n"), ("missing", "missing_port\n"),
        ("cycle", "cycle\n"), ("type", "type_mismatch\n"),
        ("duplicate", "duplicate\n"), ("malformed", "invalid_node\n"),
        ("output", "missing_output\n"), ("input", "invalid_input\n"),
        ("oversize", "budget\n"), ("nonlist", "invalid_plan\n"),
    ]:
        result = subprocess.check_output([exe], cwd=tmp, env={**os.environ, "DAG_CASE": case}, timeout=10)
        assert result == expected.encode("ascii"), (case, result, expected)
print("scalar_dag_ok=true executions=6 rejected=14")
