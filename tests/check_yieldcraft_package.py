#!/usr/bin/env python3
"""Compile an independent On1x host; check the package against frozen output bytes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
CASES = (
    ("", "2e9001180390d28e4ed18a299d12e0913d6b85e75af5d022921169e8513f1b46",
     "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"),
    ("_multiroom", "b45c4c20ade0ab1a8b01e3d6eb0fc0381eed9fb7c2cc480314c024364ded93b6",
     "7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b"),
)


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    archive = json.loads((FIX / "replay_v1.json").read_bytes())["files"]
    manifest = json.loads((ROOT / "plugins/yieldcraft/plugin.json").read_bytes())
    if (manifest["entry_point"], manifest["mode"], manifest["host_capabilities"]) != (
        "plugins.yieldcraft.entry.recommend", "recommendation", []
    ):
        raise ValueError("unexpected Yieldcraft entry point or authority")
    with tempfile.TemporaryDirectory(prefix="finpred-yieldcraft-package-") as tmp:
        exe = Path(tmp) / "consumer"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-build.py",
            ROOT / "tests/yieldcraft_package_consumer/main.on1x",
            "--backend", "c11", "--on1xc", compiler, "--mulib-root", sdk,
            "-I", ROOT / "source", "-I", ROOT, "-o", exe,
        ], check=True, cwd=tmp)
        cwd = Path(tmp) / "empty"
        cwd.mkdir()

        def invoke(env, *, expected=None, diagnostic=None):
            proc = subprocess.run([exe], cwd=cwd, env={**os.environ, **env, "FINPRED_HOME": str(cwd / "store")},
                                  capture_output=True, timeout=15)
            if expected is not None:
                ok = proc.returncode == 0 and proc.stdout == expected
            else:
                ok = (proc.returncode > 0 and diagnostic in proc.stdout + proc.stderr
                      and b'"price_minor"' not in proc.stdout)
            if not ok or list(cwd.iterdir()):
                raise ValueError(f"consumer exit {proc.returncode}: {proc.stdout!r} {proc.stderr!r}")

        for suffix, v1, v2 in CASES:
            _, sd, od, vd, td, rec, _ = archive[f"runs/{v1}.txt"].strip().split(",")
            env = dict(YC_SCENARIO=FIX / f"scenario{suffix}.csv", YC_OFFERS=FIX / f"offers{suffix}.csv",
                       YC_VALUATION=FIX / "valuation.csv", YC_MODE="recommendation",
                       YC_SD=sd, YC_OD=od, YC_VD=vd, YC_TD=td)
            # The recommendation envelope is shared across generations; only
            # its run ID changes. The expected bytes come from the v1 writer.
            frozen = archive[f"artifacts/blake3-{rec}.txt"]
            for run_id in (v1, v2):
                invoke({**env, "YC_RUN_ID": run_id}, expected=frozen.replace(v1, run_id).encode("ascii"))

        # Modes must be rejected even before malformed scenario parsing.
        for mode in ("execution", "publish", "analysis", "simulation", ""):
            invoke({**env, "YC_MODE": mode, "YC_SCENARIO": FIX / "invalid_scenario.csv"},
                   diagnostic=b"capability denied")
        invoke({**env, "YC_SCENARIO": FIX / "invalid_scenario.csv"}, diagnostic=b"scenario: invalid")
        few = Path(tmp) / "one-room.csv"
        few.write_bytes(b"".join(env["YC_OFFERS"].read_bytes().splitlines(keepends=True)[:2]))
        invoke({**env, "YC_OFFERS": few}, diagnostic=b"insufficient_evidence")
        oversized = Path(tmp) / "oversized.csv"
        oversized.write_bytes(b"x" * 2_000_001)
        for name in ("YC_SCENARIO", "YC_OFFERS", "YC_VALUATION"):
            invoke({**env, name: oversized}, diagnostic=b"source exceeds byte limit")
    print("yieldcraft_package_ok=true envelopes=4 denied_modes=5 invalid_inputs=5")


if __name__ == "__main__":
    main()
