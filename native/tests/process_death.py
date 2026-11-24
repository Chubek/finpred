"""Deterministic native-store process death, visibility and recovery on a live mount."""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time


TIMEOUT = 10
LEAVES = {
    "artifact": ("artifacts", "blake3-" + "a" * 64 + ".txt"),
    "run": ("runs", "b" * 64 + ".txt"),
}


def expect(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


@contextmanager
def worker(executable, root, *args):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        child = subprocess.Popen(
            [executable, str(fd), *args],
            pass_fds=(fd,),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
    finally:
        os.close(fd)
    with child:
        try:
            yield child
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=TIMEOUT)


def await_checkpoint(child, checkpoint):
    # No sleeps and no filesystem timing assumptions. Only continue once the
    # test-only wrapper has completed the named real syscall and paused.
    expected = checkpoint.encode("ascii") + b"\n"
    received = bytearray()
    deadline = time.monotonic() + TIMEOUT
    while len(received) < len(expected):
        ready, _, _ = select.select([child.stdout], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError(f"writer did not reach {checkpoint}")
        part = os.read(child.stdout.fileno(), len(expected) - len(received))
        if not part:
            raise AssertionError(f"writer exited before {checkpoint}: {received!r}")
        received.extend(part)
    expect(received, expected)


def finish(child, expected, resume=None):
    output, _ = child.communicate(input=resume, timeout=TIMEOUT)
    expect((child.returncode, output.decode("ascii").strip()), (0, expected))


def kill_paused_writer(child):
    child.kill()
    output, _ = child.communicate(timeout=TIMEOUT)
    expect((child.returncode, output), (-signal.SIGKILL, b""))


def call(executable, root, expected, *args):
    with worker(executable, root, *args) as child:
        finish(child, expected)


def new_store(executable, parent, name, kind):
    root = parent / name
    root.mkdir(mode=0o700)
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)  # Model the host's responsibility for anchoring the root.
    finally:
        os.close(fd)
    call(executable, root, "", "provision")
    # Only this synthetic test client is responsible for parent-before-run
    # ordering. The native library treats both payloads as opaque bytes.
    if kind == "run":
        call(executable, root, "created 1 1", "install", "artifact", "same")
    return root


def inodes(root, kinds):
    """Assert exactly the expected names, with no stage or recovery debris."""
    expect(sorted(p.name for p in root.iterdir()), ["artifacts", "runs"])
    result = {}
    for kind, (directory, leaf) in LEAVES.items():
        expect(sorted(p.name for p in (root / directory).iterdir()), [leaf] if kind in kinds else [])
        if kind in kinds:
            info = (root / directory / leaf).stat(follow_symlinks=False)
            result[kind] = (info.st_dev, info.st_ino)
    return result


def die_at(executable, parent, kind, checkpoint, visible):
    root = new_store(executable, parent, f"{kind}-{checkpoint}", kind)
    parents = {"artifact"} if kind == "run" else set()
    initial = inodes(root, parents)
    before_recovery = parents | ({kind} if visible else set())
    read_expected = "complete" if visible else "missing"
    with worker(executable, root, "install", kind, "same", checkpoint) as writer:
        await_checkpoint(writer, checkpoint)
        call(executable, root, read_expected, "read", kind, "same")
        while_paused = inodes(root, before_recovery)
        kill_paused_writer(writer)

    call(executable, root, read_expected, "read", kind, "same")
    expect(inodes(root, before_recovery), while_paused)
    if visible:
        call(executable, root, "conflict 0 0", "install", kind, "different")
        expect(inodes(root, before_recovery), while_paused)
    call(executable, root, "identical 1 1" if visible else "created 1 1", "install", kind, "same")
    call(executable, root, "complete", "read", kind, "same")
    if parents:
        call(executable, root, "complete", "read", "artifact", "same")
    recovered = inodes(root, parents | {kind})
    expect({k: recovered[k] for k in before_recovery}, while_paused)
    expect({k: recovered[k] for k in parents}, initial)


def link_race(executable, parent, kind):
    root = new_store(executable, parent, f"{kind}-race", kind)
    parents = {"artifact"} if kind == "run" else set()
    initial = inodes(root, parents)
    with ExitStack() as stack:
        # All three have staged different inodes and synced file data, and
        # none has linked the destination. The losers must take the actual
        # linkat EEXIST path, not the initial existing-name fast path.
        identical = stack.enter_context(worker(executable, root, "install", kind, "same", "file-synced"))
        conflict = stack.enter_context(worker(executable, root, "install", kind, "different", "file-synced"))
        # Start the winner only when both contenders have observed absence.
        await_checkpoint(identical, "file-synced")
        await_checkpoint(conflict, "file-synced")
        expect(inodes(root, parents), initial)
        call(executable, root, "missing", "read", kind, "same")
        winner = stack.enter_context(worker(executable, root, "install", kind, "same", "linked"))
        await_checkpoint(winner, "linked")
        linked = inodes(root, parents | {kind})
        call(executable, root, "complete", "read", kind, "same")
        finish(conflict, "conflict 1 0", resume=b"r")
        expect(inodes(root, parents | {kind}), linked)
        # The winner still has not synced the directory. The identical
        # contender must sync the winning inode and its directory itself.
        finish(identical, "identical 2 1", resume=b"r")
        kill_paused_writer(winner)
    expect(inodes(root, parents | {kind}), linked)
    expect({k: linked[k] for k in parents}, initial)
    call(executable, root, "complete", "read", kind, "same")
    if parents:
        call(executable, root, "complete", "read", "artifact", "same")


def main(executable):
    # CTest's configured build directory is deliberately on the test mount.
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="store-death-") as tmp:
        parent = Path(tmp)
        for kind in LEAVES:
            for checkpoint, visible in (
                ("partial-write", False),
                ("file-synced", False),
                ("linked", True),
                ("dir-synced", True),
            ):
                die_at(executable, parent, kind, checkpoint, visible)
                print(f"native_store_process_death_ok kind={kind} checkpoint={checkpoint}", flush=True)
            link_race(executable, parent, kind)
            print(f"native_store_link_race_ok kind={kind}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
