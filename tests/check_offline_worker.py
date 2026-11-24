#!/usr/bin/env python3
"""Run the real offline sandbox on Linux; absent sandbox support is a failure."""

import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRAME = b"finpred.offline-worker@1\n"
CC = shlex.split(os.environ.get("CC", "cc"))


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-offline-worker-") as tmp:
        work = Path(tmp)
        worker = work / "supervisor"
        probe = work / "probe"
        for source, out, flags in (
            ("source/sdk/process/worker.c", worker, []),
            ("tests/offline_worker_probe.c", probe, ["-static", "-fno-pie"]),
        ):
            subprocess.run([*CC, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                            *flags, ROOT / source, "-o", out], check=True)

        def run(request, path=probe, **kw):
            return subprocess.run([worker, path], input=request, capture_output=True,
                                  timeout=5, **kw)

        for request in (FRAME + b"E\0\xff", FRAME + b"E" * (65536 - len(FRAME))):
            p = run(request)
            assert (p.returncode, p.stdout, p.stderr) == (0, request, b""), p.stderr

        with (work / "private").open("wb+") as secret:
            secret.write(b"never visible")
            secret.flush()
            fd = fcntl.fcntl(secret.fileno(), fcntl.F_DUPFD_CLOEXEC, 57)
            try:
                assert fd == 57
                p = run(FRAME + b"R", pass_fds=(fd,),
                        env=os.environ | {"FINPRED_WORKER_TEST_SECRET": "unavailable to worker"})
            finally:
                os.close(fd)
            assert (p.returncode, p.stdout, p.stderr) == (0, FRAME + b"restricted\n", b""), p.stderr
            assert (work / "private").read_bytes() == b"never visible"

        for request in (b"wrong", FRAME + b"E" * 65536,
                        *(FRAME + case for case in (b"F", b"B", b"L", b"T"))):
            p = run(request)
            assert p.returncode > 0 and not p.stdout and p.stderr, (request[:40], p)

        alias = work / "alias"
        alias.symlink_to(probe)
        os.mkfifo(work / "fifo")
        for path in (alias, work / "fifo", Path("/usr/bin/true"), work, work / "missing"):
            p = run(FRAME + b"E", path)
            assert p.returncode == 2 and not p.stdout and b"invalid executable" in p.stderr
    print("offline_worker_ok=true namespace=linux syscall_allowlist=passed no_partial_output=passed")


if __name__ == "__main__":
    main()
