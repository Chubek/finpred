#!/usr/bin/env python3
"""Run the real offline sandbox on Linux; absent sandbox support is a failure."""

import argparse
import fcntl
import os
from pathlib import Path
import shlex
import signal
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRAME = b"finpred.offline-worker@1\n"
CC = shlex.split(os.environ.get("CC", "cc"))


def context():
    values = {name: Path(name).read_text().strip() if Path(name).exists() else "absent"
              for name in ("/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
                           "/proc/sys/kernel/unprivileged_userns_clone",
                           "/proc/sys/user/max_user_namespaces")}
    bwrap = Path("/usr/bin/bwrap")
    if bwrap.exists():
        version = subprocess.run([bwrap, "--version"], capture_output=True, text=True,
                                 timeout=5).stdout.strip()
    else:
        version = "missing /usr/bin/bwrap"
    return f"{version}; namespace policy: {values}"


def verify_probe(path):
    # Separate compiler/linker failure from a real sandbox startup failure.
    elf = path.read_bytes()
    assert elf[:6] == b"\x7fELF\x02\x01", "probe must be little-endian ELF64"
    assert struct.unpack_from("<HH", elf, 16) == (2, 62), "probe must be x86-64 ET_EXEC (not PIE)"
    offset, size, count = (struct.unpack_from("<Q", elf, 32)[0],
                           *struct.unpack_from("<HH", elf, 54))
    assert count and size == 56 and offset + size * count <= len(elf), "invalid probe headers"
    assert all(struct.unpack_from("<I", elf, offset + size * i)[0] != 3
               for i in range(count)), "probe must have no ELF interpreter"


def caller_signal_policy():
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGCHLD})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true",
                        help="check ELF type and one real sandbox round trip")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="finpred-offline-worker-") as tmp:
        work = Path(tmp)
        worker = work / "supervisor"
        probe = work / "probe"
        cflags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
        subprocess.run([*CC, *cflags, ROOT / "source/sdk/process/worker.c", "-o", worker],
                       check=True)
        probe_obj = work / "probe.o"
        subprocess.run([*CC, *cflags, "-fno-pie", "-c", ROOT / "tests/offline_worker_probe.c",
                        "-o", probe_obj], check=True)
        subprocess.run([*CC, "-static", "-Wl,-no-pie", probe_obj, "-o", probe], check=True)
        verify_probe(probe)

        def run(request, path=probe, **kw):
            return subprocess.run([worker, path], input=request, capture_output=True,
                                  timeout=5, **kw)

        request = FRAME + b"E\0\xff"
        p = run(request)
        assert (p.returncode, p.stdout, p.stderr) == (0, request, b""), (p, context())
        print("offline_worker_preflight_ok=true static_et_exec=true real_sandbox=true", flush=True)
        if args.preflight:
            return
        request = FRAME + b"E" * (65536 - len(FRAME))
        p = run(request, preexec_fn=caller_signal_policy)
        assert (p.returncode, p.stdout, p.stderr) == (0, request, b""), p

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
