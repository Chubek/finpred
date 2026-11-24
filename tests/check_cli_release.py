#!/usr/bin/env python3
"""Exercise the release producer, archive verifier and relocated CLI."""

import gzip
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.0.0"
NAME = f"finpred-cli-{VERSION}-linux-x86_64"
RUN_ID = "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"
CUBE_ID = "588f6bcfcf9128268cd1f81bcc11f0b855828edfd86804fc91c6a44217c211d2"


def main():
    parent = Path(os.environ.get("TMPDIR") or ROOT / "build/tmp").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cli-release-test-", dir=parent) as temporary:
        work = Path(temporary)
        command = [sys.executable, ROOT / "bin/release.py"]
        archives = []
        for suffix, salt, mask in (("one", "19", 0o022), ("longer-build-and-output", "29", 0o077)):
            target = work / suffix
            subprocess.run([*command, "build", VERSION, "--output", target], cwd=ROOT,
                           env=os.environ | {"TMPDIR": str(work / ("scratch-" + suffix)),
                                             "SOURCE_DATE_EPOCH": salt, "PYTHONHASHSEED": salt},
                           umask=mask, check=True, timeout=240)
            archives.append(target / f"{NAME}.tar.gz")
        bundle = archives[0]
        blob = bundle.read_bytes()
        assert blob == archives[1].read_bytes(), "release archives differ"
        digest = sha256(blob).hexdigest()
        sidecar = bundle.with_name(bundle.name + ".sha256")
        assert sidecar.read_text() == f"{digest}  {bundle.name}\n"

        def verify(path, diagnostic=None, **kwargs):
            proc = subprocess.run([*command, "verify", path, *kwargs.get("flags", ())],
                                  capture_output=True, text=True, timeout=10)
            if diagnostic is None:
                assert proc.returncode == 0 and "release_verified=true" in proc.stdout, proc
            else:
                assert proc.returncode == 2 and diagnostic in proc.stderr, proc

        verify(bundle, flags=["--sha256", digest])
        verify(bundle, "archive SHA-256 mismatch", flags=["--sha256", "0" * 64])

        def tamper(kind):
            result = work / f"{kind}.tar.gz"
            with tarfile.open(bundle, "r:gz") as original, tarfile.open(
                    result, "w:gz", format=tarfile.USTAR_FORMAT) as changed:
                for entry in original:
                    data = original.extractfile(entry).read()
                    if entry.name.endswith("/fixtures/offers.csv"):
                        if kind == "content":
                            data = b"!" + data[1:]
                        elif kind == "mode":
                            entry.mode = 0o777
                        elif kind == "traversal":
                            entry.name = f"{NAME}/fixtures/../../outside"
                        elif kind == "symlink":
                            entry.type, entry.linkname, entry.size = tarfile.SYMTYPE, "/etc/passwd", 0
                        elif kind == "duplicate":
                            changed.addfile(entry, io.BytesIO(data))
                    changed.addfile(entry, io.BytesIO(data))
            return result

        for kind, diagnostic in (("content", "file inventory mismatch"), ("mode", "archive metadata"),
                                 ("traversal", "invalid archive entry"), ("symlink", "invalid archive entry"),
                                 ("duplicate", "invalid archive entry")):
            verify(tamper(kind), diagnostic)
        tail = work / "tail.tar.gz"
        tail.write_bytes(gzip.compress(gzip.decompress(blob) + b"trailing-data", mtime=0))
        verify(tail, "noncanonical release tar")

        relocated = work / "relocated release"
        relocated.mkdir()
        subprocess.run(["tar", "-xzf", bundle, "-C", relocated], check=True)
        package = relocated / NAME
        cli = package / "bin/finpred"
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("FINPRED_", "ON1X")) and key != "MULIB_ROOT"}
        env["FINPRED_HOME"] = str(work / "demo-store")

        def run(*args, extra=None, code=0):
            proc = subprocess.run([cli, *args], cwd=work, env=env | (extra or {}),
                                  text=True, capture_output=True, timeout=5)
            assert proc.returncode == code, proc
            return proc.stdout if not code else proc.stderr

        assert "selftest_ok=true" in run("selftest").splitlines()
        price = run("run")
        assert set((f"run_id={RUN_ID}", "recommendation_minor=17100", "currency=EUR",
                    "published=false")) <= set(price.splitlines()), price
        assert "replay_ok=true" in run("replay", RUN_ID).splitlines()
        cube = json.loads(run("cube", "evaluate",
                              *(package / "fixtures/competitor" / f"{key}.csv"
                                for key in ("snapshots", "cells", "policies"))))
        assert cube["cube_id"] == CUBE_ID and cube["cube"]["published"] is False, cube
        assert json.loads(run("cube", "replay", CUBE_ID))["cube_id"] == CUBE_ID
        assert "capability denied" in run("selftest", extra={"FINPRED_MODE": "execution"}, code=2)
    print("cli_release_ok=true same_toolchain_rebuilds=2 malformed_archives=7 historical_ids=2")


if __name__ == "__main__":
    main()
