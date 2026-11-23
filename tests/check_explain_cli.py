#!/usr/bin/env python3
"""Verify an operator sees exactly the stored trace, only after integrity checks."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check(home, run_id):
    env = {**os.environ, "FINPRED_HOME": str(home)}
    for name in ("SCENARIO", "OFFERS", "VALUATION", "STRATEGY"):
        env[f"FINPRED_{name}"] = str(home / "absent")
    cmd = [ROOT / "bin/finpred"]
    summary = subprocess.check_output([*cmd, "replay", run_id], env=env)
    digest, = (s.removeprefix(b"trace_digest=").decode("ascii")
               for s in summary.splitlines() if s.startswith(b"trace_digest="))
    trace = Path("artifacts", f"blake3-{digest}.txt")
    expected = summary + b"trace_begin\n" + (home / trace).read_bytes() + b"trace_end\n"
    if subprocess.check_output([*cmd, "explain", run_id], env=env) != expected:
        raise ValueError("explain output differs from verified summary and stored trace")

    # Work on a copy: a missing trace must fail, not return a plausible explanation.
    with tempfile.TemporaryDirectory(prefix="finpred-explain-") as tmp:
        copy = Path(tmp) / "store"
        shutil.copytree(home, copy)
        (copy / trace).unlink()
        proc = subprocess.run([*cmd, "explain", run_id], env={**env, "FINPRED_HOME": str(copy)},
                              capture_output=True)
        if proc.returncode == 0 or b"trace_begin" in proc.stdout or b"replay_ok=true" in proc.stdout:
            raise ValueError("explain acknowledged an incomplete run")
    print("explain_ok=true", f"run_id={run_id}")


if __name__ == "__main__":
    check(Path(sys.argv[1]).resolve(), sys.argv[2])
