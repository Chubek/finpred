#!/usr/bin/env python3
"""Exercise the development coordinator through its CLI and real Linux POSIX IPC."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
MESSAGE = 1024
SLOT = 65536
HEADER_SIZE = struct.calcsize("!8sQI32s")
TIMEOUT = 12


# No coordinator imports or call interception for conformance tests. The
# separate crash child below wraps one mmap write to target a precise boundary.
LIBC = C.CDLL("libc.so.6", use_errno=True)


def bind(name, *args):
    fn = getattr(LIBC, name)
    fn.argtypes = args
    fn.restype = C.c_int
    return fn


MQ_OPEN = bind("mq_open", C.c_char_p, C.c_int)
MQ_SEND = bind("mq_send", C.c_int, C.c_char_p, C.c_size_t, C.c_uint)
MQ_CLOSE = bind("mq_close", C.c_int)
SHM_OPEN = bind("shm_open", C.c_char_p, C.c_int, C.c_uint)


def syscall(fn, *args, error=None):
    result = fn(*args)
    if result == -1:
        got = C.get_errno()
        if got == error:
            return None
        raise OSError(got, f"{fn.__name__}: {os.strerror(got)}")
    if error is not None:
        raise AssertionError(f"{fn.__name__} succeeded, expected {os.strerror(error)}")
    return result


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def elapsed(until):
    time.sleep(max(0, until + 5 - (time.monotonic_ns() // 1_000_000)) / 1000)


class Session:
    def __init__(self, coordinator, workspace):
        self.coordinator = coordinator
        self.workspace = workspace
        self.name = "verify-" + secrets.token_hex(8)
        self.prefix = f"/fp8_{os.getuid()}_{self.name}_".encode("ascii")
        self.journal = workspace / "journal"
        self.base_args = [str(self.coordinator), "--journal", str(self.journal), self.name]

    def invoke(self, actor, *args, diagnostic=None, fault=None):
        suffix = [*self.base_args, str(actor), *map(str, args)]
        if fault is None:
            command = [sys.executable, *suffix]
        else:
            command = [sys.executable, "-c", CRASH_CHILD, fault, *suffix]
        proc = subprocess.run(command, cwd=self.workspace, capture_output=True, timeout=TIMEOUT)
        outcome = (proc.returncode, proc.stdout, proc.stderr)
        if fault is not None:
            assert outcome == (-signal.SIGKILL, b"", b""), (args, fault, outcome)
        elif diagnostic is not None:
            assert proc.returncode == 1 and not proc.stdout and diagnostic.encode() in proc.stderr, (
                actor, args, diagnostic, outcome
            )
        else:
            if args == ("init",) and proc.returncode != 0:
                # Linux can return EMFILE for RLIMIT_MSGQUEUE exhaustion,
                # distinct from ENOSPC for the namespace-wide queue limit.
                if any(message in proc.stderr for message in
                       (b"mq_open: Too many open files", b"mq_open: No space left")):
                    raise RuntimeError(
                        "cannot allocate eight test queues; if permitted, retry with "
                        "unshare -Uri, or wait until the broker closes its live session"
                    )
            assert proc.returncode == 0 and not proc.stderr, (actor, args, outcome)
            if proc.stdout:
                value = json.loads(proc.stdout)
                assert proc.stdout == json_bytes(value) + b"\n", (actor, args, outcome)
                return value
        return None

    def snapshot(self):
        return self.invoke(7, "snapshot")

    def resources_absent(self):
        syscall(SHM_OPEN, self.prefix + b"state", os.O_RDONLY, 0, error=errno.ENOENT)
        for actor in range(8):
            syscall(MQ_OPEN, self.queue(actor), os.O_WRONLY | os.O_NONBLOCK, error=errno.ENOENT)

    def queue(self, recipient):
        return self.prefix + str(recipient).encode("ascii")

    def inject(self, recipient, wire, *, priority=0, error=None):
        fd = syscall(MQ_OPEN, self.queue(recipient), os.O_WRONLY | os.O_NONBLOCK)
        try:
            syscall(MQ_SEND, fd, wire, len(wire), priority, error=error)
        finally:
            syscall(MQ_CLOSE, fd)

    def slots(self):
        fd = syscall(SHM_OPEN, self.prefix + b"state", os.O_RDONLY, 0)
        try:
            data = os.pread(fd, 2 * SLOT, 0)
            assert len(data) == 2 * SLOT
            return data
        finally:
            os.close(fd)

    def events(self):
        return [json.loads(row) for row in self.journal.read_bytes().splitlines()]

    def request(self, sender=1, recipient=2, lifetime=60_000):
        key = self.invoke(sender, "request", recipient, "candidate", "--lifetime", lifetime)
        assert type(key) is int and key > 0
        return key

    def grant(self, correlation, lifetime=60_000):
        self.invoke(0, "grant", correlation, "--lifetime", lifetime)

    def item(self, correlation):
        return self.snapshot()["exchanges"][str(correlation)]

    def message(self, correlation, payload):
        state = self.snapshot()
        item = state["exchanges"][str(correlation)]
        return dict(version=1, epoch=state["epoch"], correlation=correlation, payload=payload,
                    **{key: item[key] for key in ("sender", "recipient", "purpose", "until")})

    def send(self, sender, correlation, text, **kwargs):
        self.invoke(sender, "send", correlation, text, "--wait", 0, **kwargs)

    def receive(self, recipient, **kwargs):
        return self.invoke(recipient, "recv", "--wait", 0, **kwargs)


def test_envelopes(session):
    call = session.invoke
    call(2, "contract", "should not be set", diagnostic="only worker 0")
    call(2, "init", diagnostic="only worker 0")
    call(2, "cleanup", diagnostic="only worker 0")
    call(2, "request", 2, "candidate", diagnostic="invalid request recipient")
    correlation = session.request()
    call(1, "grant", correlation, diagnostic="only worker 0")
    session.send(1, correlation, "ungranted", diagnostic="no live granted")
    session.grant(correlation)
    session.send(3, correlation, "mismatch", diagnostic="sender is not admitted")
    session.send(1, correlation, "x" * 639, diagnostic="encoded text too large")
    session.inject(2, b"x" * (MESSAGE + 1), error=errno.EMSGSIZE)
    call(2, "recv", "--wait", 25, diagnostic="receive timed out")

    # Exercise the exact text cap, plus ASCII escaping and non-ASCII bytes.
    text = 'x' * 628 + '"\\é'
    assert len(json_bytes(text)) == 640
    expected = session.message(correlation, text)
    wire = json_bytes(expected)
    # None has an admitted send, including the otherwise canonical envelope.
    for malformed in (b"", b"\xff", b"[]", b'{"correlation":true,"recipient":2}', wire):
        session.inject(2, malformed)
        session.receive(2, diagnostic="rejected queued message")
    assert session.item(correlation)["phase"] == "granted"
    session.send(1, correlation, text)
    assert session.item(correlation)["digest"] == hashlib.sha256(wire).hexdigest()
    session.send(1, correlation, text, diagnostic="no live granted")

    session.inject(3, wire)
    session.receive(3, diagnostic="rejected queued message")
    session.inject(2, wire, priority=1)
    session.receive(2, diagnostic="rejected queued message")
    assert session.item(correlation)["phase"] == "sent"
    assert session.receive(2) == expected
    session.inject(2, wire)
    session.receive(2, diagnostic="rejected queued message")
    call(1, "ack", correlation, diagnostic="acknowledgement from wrong worker")
    call(2, "ack", correlation)
    call(2, "ack", correlation, diagnostic="no live received")
    return expected


def test_expiry_and_backpressure(session):
    # Let the recorded monotonic deadline expire without assuming CLI startup
    # latency. A queued frame and a grant are independent expiry cases.
    pair = [session.request(), session.request()]
    for correlation in pair:
        session.grant(correlation, lifetime=1_000)
    session.send(1, pair[0], "in queue but expired")
    for correlation in pair:
        elapsed(session.item(correlation)["until"])
    session.receive(2, diagnostic="rejected queued message")
    session.send(1, pair[1], "expired grant", diagnostic="no live granted")

    correlation = session.request(lifetime=1)
    elapsed(session.item(correlation)["until"])
    session.invoke(0, "grant", correlation, diagnostic="no live requested")

    keys = [session.request() for _ in range(3)]
    for key in keys:
        session.grant(key)
    for key in keys[:2]:
        session.send(1, key, f"frame-{key}")
    session.inject(2, b"third kernel frame", error=errno.EAGAIN)
    before = session.snapshot()
    session.invoke(1, "send", keys[2], "third", "--wait", 25, diagnostic="recipient queue full")
    assert session.snapshot() == before, "failed send advanced exchange or sequence"
    assert session.receive(2) == session.message(keys[0], f"frame-{keys[0]}")
    session.send(1, keys[2], "third")
    for key, text in zip(keys[1:], (f"frame-{keys[1]}", "third")):
        assert session.receive(2) == session.message(key, text)
    for key in keys:
        session.invoke(2, "ack", key)
    session.receive(2, diagnostic="receive timed out")


def test_concurrent_publication(session):
    before = session.snapshot()
    args = [(actor, "status", f"concurrent-{actor}") for actor in range(8)]
    args += [(actor, "request", 0, "candidate") for actor in range(1, 8) for _ in range(3)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda item: session.invoke(*item), args))
    after = session.snapshot()
    assert after["sequence"] == before["sequence"] + len(args)
    for actor in range(8):
        assert after["workers"][str(actor)]["status"] == f"concurrent-{actor}"
    keys = results[8:]
    assert len(set(keys)) == len(keys)
    for (actor, *_), key in zip(args[8:], keys):
        item = after["exchanges"][str(key)]
        assert (item["sender"], item["recipient"], item["purpose"], item["phase"]) == (
            actor, 0, "candidate", "requested"
        ), (key, item)
    events = session.events()
    tail = events[-len(args):]
    assert [event["sequence"] for event in tail] == list(
        range(before["sequence"] + 1, after["sequence"] + 1)
    )
    assert {event["correlation"] for event in tail if event["event"] == "request"} == set(keys)


# Use the real coordinator and mmap writes, but kill the child immediately
# before the writer fills the target slot's header. This is deterministic;
# it exercises kernel release of the flock rather than a synthetic exception.
CRASH_CHILD = """
import os
import runpy
import signal
import sys

fault = sys.argv.pop(1)
sys.argv.pop(0)
program = runpy.run_path(sys.argv[0])
cls = program["Session"]
original = cls.publish

class Window:
    def __init__(self, backing):
        self.backing = backing

    def __setitem__(self, key, value):
        if value.startswith(program["MAGIC"]) and len(value) == program["HEADER"].size:
            os.kill(os.getpid(), signal.SIGKILL)
        self.backing[key] = value

def publish(session, state):
    if (state["sequence"] == 0) != (fault == "init"):
        raise AssertionError("unexpected crash point")
    real = session.region
    try:
        session.region = Window(real)
        original(session, state)
    finally:
        session.region = real
    raise AssertionError("publication did not hit requested crash point")

cls.publish = publish
sys.exit(program["main"]())
"""


def test_writer_crash(session):
    before = session.snapshot()
    session.invoke(7, "status", "must-not-be-visible", fault="status")
    assert session.snapshot() == before
    expected = before["sequence"] + 1
    offset = (expected % 2) * SLOT
    raw = session.slots()
    assert raw[offset:offset + HEADER_SIZE] == bytes(HEADER_SIZE)
    assert b"must-not-be-visible" in raw[offset + HEADER_SIZE:offset + SLOT]
    session.invoke(7, "status", "post-crash")
    after = session.snapshot()
    assert after["sequence"] == expected and after["workers"]["7"]["status"] == "post-crash"


def test_queue_crashes(session):
    key = session.request()
    session.grant(key)
    message = "retry a send whose state was not published"
    session.invoke(1, "send", key, message, fault="send")
    assert session.item(key)["phase"] == "granted"
    session.receive(2, diagnostic="rejected queued message")
    session.send(1, key, message)
    assert session.receive(2) == session.message(key, message)
    session.invoke(2, "ack", key)

    key = session.request()
    session.grant(key)
    session.send(1, key, "not automatically redelivered")
    before = session.snapshot()
    session.invoke(2, "recv", "--wait", 0, fault="receive")
    assert session.snapshot() == before and session.item(key)["phase"] == "sent"
    session.receive(2, diagnostic="receive timed out")
    session.invoke(2, "revoke", key, diagnostic="only worker 0")
    session.invoke(0, "revoke", key)
    session.send(1, key, "must request a new grant", diagnostic="no live granted")

    replacement = session.request()
    assert replacement != key
    session.grant(replacement)
    session.send(1, replacement, "replacement")
    assert session.receive(2) == session.message(replacement, "replacement")
    session.invoke(2, "ack", replacement)


def test_new_epoch(session, old):
    session.invoke(0, "cleanup")
    session.resources_absent()
    session.invoke(0, "cleanup")  # Idempotent.
    session.invoke(0, "init")
    assert session.snapshot()["epoch"] != old["epoch"]
    correlation = session.request()
    assert correlation == old["correlation"], "test must distinguish epochs despite reused ID"
    session.grant(correlation)
    session.inject(2, json_bytes(old))
    session.send(1, correlation, old["payload"])
    session.receive(2, diagnostic="rejected queued message")
    assert session.receive(2) == session.message(correlation, old["payload"])


def test_crashed_initialization(session):
    session.resources_absent()
    try:
        session.invoke(0, "init", fault="init")
        raw = session.slots()
        assert raw[:HEADER_SIZE] == bytes(HEADER_SIZE)
        tentative, _ = json.JSONDecoder().raw_decode(raw[HEADER_SIZE:SLOT].decode("ascii"))
        session.invoke(7, "snapshot", diagnostic="no valid published session")
    finally:
        session.invoke(0, "cleanup")
    session.resources_absent()
    session.invoke(0, "init")
    try:
        state = session.snapshot()
        assert state["sequence"] == 0 and state["epoch"] != tentative["epoch"]
    finally:
        session.invoke(0, "cleanup")
    session.resources_absent()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coord", type=Path, default=ROOT / "bin/overhaul-coord.py",
                        help="path to the coordinator under test")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("requires Linux POSIX message queues and shared memory")
    if not __debug__:
        parser.error("run without -O or PYTHONOPTIMIZE")
    coord = args.coord.resolve(strict=True)
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-overhaul-", dir=scratch) as temporary:
        work = Path(temporary)
        first = work / "first"
        first.mkdir()
        session = Session(coord, first)
        session.resources_absent()
        try:
            session.invoke(0, "init")
            old = test_envelopes(session)
            test_expiry_and_backpressure(session)
            test_concurrent_publication(session)
            test_writer_crash(session)
            test_queue_crashes(session)
            test_new_epoch(session, old)
        finally:
            session.invoke(0, "cleanup")
            session.resources_absent()
        second = work / "second"
        second.mkdir()
        test_crashed_initialization(Session(coord, second))
    print("core_overhaul_ipc_ok=true linux_mqueue=true concurrent_updates=29 "
          "forced_sigkill=4 epoch_reset=true")


if __name__ == "__main__":
    main()
