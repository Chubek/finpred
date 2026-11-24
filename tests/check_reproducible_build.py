#!/usr/bin/env python3
"""Check app artifacts from two isolated builds with one installed toolchain."""

from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("finpred", "finpred-cube", "finpred-forecast")
V1_SUBJECT = "18cdedd7bb43f90a694537dc95a9da323822d8e52e2722dbd8f6df3032c535e1"


def historical_forecast_subject(work):
    source = work / "source"
    shutil.copytree(ROOT / "plugins/forecast_baselines/source/forecast_baselines",
                    source / "forecast_baselines")
    parents = (
        ("source/core/date.on1x", "core/date.on1x"),
        ("source/core/feed_snapshot.on1x", "core/feed_snapshot.on1x"),
        ("source/core/format.on1x", "core/format.on1x"),
        ("plugins/dragnet/guest_nights.on1x", "plugins/dragnet/guest_nights.on1x"),
        ("source/sdk/callable.on1x", "sdk/callable.on1x"),
    )
    for path, name in parents:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    compiler = work / "fixture-compiler"
    compiler.write_bytes(b"FinPRED forecast subject test input\n")
    args = [sys.executable, ROOT / "bin/forecast-subject.py", source, compiler]
    # Recorded at 85b8a0b using the same fixed test compiler bytes.
    before = subprocess.check_output(args, text=True)
    assert before == V1_SUBJECT + "\n", before
    (source / "forecast_baselines/unused.on1x").write_text("# not linked into v1\n", encoding="ascii")
    assert subprocess.check_output(args, text=True) == before


def main():
    parent = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finpred-repro-", dir=parent) as tmp:
        historical_forecast_subject(Path(tmp) / "history")
        hashes = []
        for suffix in ("first", "other-path"):
            directory = Path(tmp) / suffix
            output = directory / "out"
            env = os.environ | {"FINPRED_BUILD_DIR": str(output), "TMPDIR": str(directory / "scratch")}
            subprocess.run([ROOT / "bin/build.sh"], cwd=ROOT, env=env, check=True)
            paths = (output / ARTIFACTS[0], output / ARTIFACTS[1],
                     output.with_name("out-forecast") / ARTIFACTS[2])
            hashes.append(tuple(sha256(path.read_bytes()).hexdigest() for path in paths))
        assert hashes[0] == hashes[1], f"builds differ: {hashes}"
    print("reproducible_build_ok=true scope=same_host_toolchain " +
          " ".join(f"{name}={digest}" for name, digest in zip(ARTIFACTS, hashes[0])))


if __name__ == "__main__":
    main()
