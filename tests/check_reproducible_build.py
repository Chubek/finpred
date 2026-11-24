#!/usr/bin/env python3
"""Check app artifacts from two isolated builds with one installed toolchain."""

from hashlib import sha256
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ("finpred", "finpred-cube", "finpred-forecast")


def main():
    parent = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finpred-repro-", dir=parent) as tmp:
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
