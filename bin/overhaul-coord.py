#!/usr/bin/env python3
"""Linux development coordination, never an engine runtime or auth boundary."""

import argparse
from contextlib import contextmanager
import ctypes as C
import errno
import fcntl
import hashlib
import json
import mmap
import os
import re
import secrets
import select
import stat
import struct
import sys
import time


VERSION = 1
WORKERS = 8
SLOT = 65536
MAX_PENDING = 64
MESSAGE = 1024
DEPTH = 2
HEADER = struct.Struct("!8sQI32s")
MAGIC = b"FP8 IPC1"
TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z", re.ASCII)


class ProtocolError(Exception):
    pass


class QueueAttr(C.Structure):
    # Linux/glibc struct mq_attr, including ABI-reserved longs.
    _fields_ = [(key, C.c_long) for key in ("flags", "maxmsg", "msgsize", "curmsg")] + [
        ("reserved", C.c_long * 4)
    ]


def bind(name, result, *args):
    fn = getattr(libc, name)
    fn.restype, fn.argtypes = result, args
    return fn


libc = C.CDLL("libc.so.6", use_errno=True)
shm_open = bind("shm_open", C.c_int, C.c_char_p, C.c_int, C.c_uint)
shm_unlink = bind("shm_unlink", C.c_int, C.c_char_p)
# mq_open is variadic. Linux takes the last two arguments only with O_CREAT.
mq_open = bind("mq_open", C.c_int, C.c_char_p, C.c_int)
mq_unlink = bind("mq_unlink", C.c_int, C.c_char_p)
mq_close = bind("mq_close", C.c_int, C.c_int)
mq_send = bind("mq_send", C.c_int, C.c_int, C.c_char_p, C.c_size_t, C.c_uint)
mq_receive = bind("mq_receive", C.c_ssize_t, C.c_int, C.c_void_p, C.c_size_t,
                  C.POINTER(C.c_uint))


def call(fn, *args, again=False, missing=False):
    deadline = time.monotonic() + 1
    while True:
        result = fn(*args)
        if result != -1:
            return result
        error = C.get_errno()
        if error == errno.EINTR and time.monotonic() < deadline:
            continue
        if (again and error == errno.EAGAIN) or (missing and error == errno.ENOENT):
            return None
        raise OSError(error, f"{fn.__name__}: {os.strerror(error)}")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def digest(data):
    return hashlib.sha256(data).digest()


def now():
    return time.monotonic_ns() // 1_000_000


def text(value, cap):
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ProtocolError("expected nonempty single-line text")
    if len(encoded(value)) > cap:
        raise ProtocolError("encoded text too large")
    return value


def check_owner(fd, label):
    st = os.fstat(fd)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or st.st_mode & 0o077):
        raise ProtocolError(f"{label} must be a private regular file owned by this UID")
    return [st.st_dev, st.st_ino]


class Session:
    def __init__(self, name, journal):
        if not TOKEN.fullmatch(name):
            raise ProtocolError("invalid session name")
        self.prefix = f"/fp8_{os.getuid()}_{name}_".encode("ascii")
        self.shm = self.prefix + b"state"
        self.journal = journal
        self.fd = None

    def queue_name(self, peer):
        return self.prefix + str(peer).encode("ascii")

    @contextmanager
    def lock(self):
        deadline = now() + 1000
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, InterruptedError):
                if now() >= deadline:
                    raise ProtocolError("shared-memory lock timed out")
                time.sleep(0.005)
        try:
            yield
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def journal_event(self, state, event, **fields):
        create = os.O_CREAT if state["journal"] is None else 0
        fd = os.open(self.journal, os.O_WRONLY | os.O_APPEND | create |
                     os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
        try:
            identity = check_owner(fd, "journal")
            if state["journal"] is None:
                state["journal"] = identity
            elif identity != state["journal"]:
                raise ProtocolError("wrong coordination journal")
            row = encoded(dict(version=VERSION, epoch=state["epoch"], at_ns=time.time_ns(),
                               sequence=state["sequence"], event=event, **fields)) + b"\n"
            if os.write(fd, row) != len(row):
                raise OSError(errno.EIO, "short journal write")
        finally:
            os.close(fd)

    @contextmanager
    def open_state(self, creating=False):
        flags = os.O_RDWR | (os.O_CREAT | os.O_EXCL if creating else 0)
        self.fd = call(shm_open, self.shm, flags, 0o600)
        created = []
        initialized = False
        try:
            with self.lock():
                check_owner(self.fd, "shared memory")
                if creating:
                    if not self.current_name():
                        raise ProtocolError("session initialization canceled")
                    os.ftruncate(self.fd, 2 * SLOT)
                if os.fstat(self.fd).st_size != 2 * SLOT:
                    raise ProtocolError("incomplete or incompatible session")
                region = mmap.mmap(self.fd, 2 * SLOT)
                self.region = region
                if creating:
                    attrs = QueueAttr(0, DEPTH, MESSAGE, 0)
                    for role in range(WORKERS):
                        queue = self.queue_name(role)
                        q = call(mq_open, queue, os.O_CREAT | os.O_EXCL | os.O_RDWR |
                                 os.O_NONBLOCK | os.O_CLOEXEC, C.c_uint(0o600), C.byref(attrs))
                        created.append(queue)
                        call(mq_close, q)
                    state = dict(version=VERSION, epoch=secrets.token_hex(16), sequence=0,
                                 journal=None, closed=False, contract=None, workers={},
                                 exchanges={})
                    self.journal_event(state, "init")
                    self.publish(state)
                    initialized = True
            yield
        finally:
            if creating and not initialized:
                # Only roll back names that this attempt created.
                with self.lock():
                    if self.current_name():
                        for name in created:
                            call(mq_unlink, name, missing=True)
                        call(shm_unlink, self.shm, missing=True)
            if hasattr(self, "region"):
                self.region.close()
            os.close(self.fd)
            self.fd = None

    def current_name(self):
        fd = call(shm_open, self.shm, os.O_RDONLY, 0o600, missing=True)
        if fd is None:
            return False
        try:
            return os.path.samestat(os.fstat(fd), os.fstat(self.fd))
        finally:
            os.close(fd)

    def read(self, *, closed=False):
        candidates = []
        for offset in (0, SLOT):
            tag, seq, n, checksum = HEADER.unpack_from(self.region, offset)
            if tag != MAGIC or seq % 2 != offset // SLOT or not 0 < n <= SLOT - HEADER.size:
                continue
            start = offset + HEADER.size
            payload = self.region[start:start + n]
            if digest(payload) != checksum:
                continue
            state = json.loads(payload)
            if state.get("version") == VERSION and state.get("sequence") == seq:
                candidates.append((seq, state))
        if not candidates:
            raise ProtocolError("no valid published session")
        _, state = max(candidates, key=lambda item: item[0])
        if state["closed"] and not closed:
            raise ProtocolError("session is closed")
        return state

    def publish(self, state):
        payload = encoded(state)
        if len(payload) > SLOT - HEADER.size:
            raise ProtocolError("shared-memory region capacity exceeded")
        seq = state["sequence"]
        offset = (seq % 2) * SLOT
        start = offset + HEADER.size
        self.region[offset:start] = b"\x00" * HEADER.size
        self.region[start:start + len(payload)] = payload
        self.region[offset:start] = HEADER.pack(MAGIC, seq, len(payload), digest(payload))

    def update(self, state, event, **fields):
        state["sequence"] += 1
        self.journal_event(state, event, **fields)
        self.publish(state)

    def cleanup(self):
        # Recover an unpublishable session left by SIGKILL during init as
        # well as a normally closed session. Serialize against live init.
        try:
            self.fd = call(shm_open, self.shm, os.O_RDWR, 0o600, missing=True)
            if self.fd is None:
                return
            with self.lock():
                check_owner(self.fd, "shared memory")
                if not self.current_name():
                    return
                if os.fstat(self.fd).st_size == 2 * SLOT:
                    with mmap.mmap(self.fd, 2 * SLOT) as self.region:
                        try:
                            state = self.read(closed=True)
                        except ProtocolError:
                            state = None
                        if state is not None and not state["closed"]:
                            state["closed"] = True
                            self.update(state, "close", actor=0)
                for role in range(WORKERS):
                    call(mq_unlink, self.queue_name(role), missing=True)
                call(shm_unlink, self.shm, missing=True)
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None

    def queue(self, peer, flags):
        return call(mq_open, self.queue_name(peer), flags | os.O_NONBLOCK | os.O_CLOEXEC)


def exchange(state, correlation, phase):
    item = state["exchanges"].get(str(correlation))
    if item is None or item["until"] <= now() or item["phase"] != phase:
        raise ProtocolError(f"no live {phase} exchange for correlation {correlation}")
    return item


def ensure_broker(actor):
    if actor != 0:
        raise ProtocolError("only worker 0 may perform this operation")


def process_state(session, args):
    actor, cmd = args.actor, args.command
    with session.lock():
        state = session.read()
        if cmd == "snapshot":
            # Snapshot exposes shared contracts, not queued messages.
            return {k: v for k, v in state.items() if k != "journal"}
        if cmd == "status":
            state["workers"][str(actor)] = dict(heartbeat_ms=now(), status=text(args.text, 512))
            session.update(state, "heartbeat", actor=actor)
        elif cmd == "contract":
            ensure_broker(actor)
            state["contract"] = text(args.text, 1024)
            session.update(state, cmd, actor=0, decision=state["contract"])
        elif cmd == "request":
            if args.peer == actor or not TOKEN.fullmatch(args.purpose):
                raise ProtocolError("invalid request recipient or purpose")
            pending = state["exchanges"]
            for key in tuple(pending):
                if pending[key]["until"] <= now() or pending[key]["phase"] in ("acked", "revoked"):
                    del pending[key]
            if len(pending) >= MAX_PENDING:
                raise ProtocolError("request capacity exhausted")
            correlation = state["sequence"] + 1
            pending[str(correlation)] = dict(sender=actor, recipient=args.peer,
                                             purpose=args.purpose, phase="requested",
                                             until=now() + args.lifetime)
            session.update(state, cmd, actor=actor, correlation=correlation, peer=args.peer,
                           purpose=args.purpose)
            return correlation
        elif cmd == "grant":
            ensure_broker(actor)
            item = exchange(state, args.id, "requested")
            item.update(phase="granted", until=now() + args.lifetime)
            session.update(state, cmd, actor=0, correlation=args.id, **item)
        elif cmd == "revoke":
            ensure_broker(actor)
            item = state["exchanges"].get(str(args.id))
            if item is None or item["phase"] not in ("requested", "granted", "sent", "received"):
                raise ProtocolError("no exchange to revoke")
            item["phase"] = "revoked"
            session.update(state, cmd, actor=0, correlation=args.id)
        elif cmd == "ack":
            item = exchange(state, args.id, "received")
            if item["recipient"] != actor:
                raise ProtocolError("acknowledgement from wrong worker")
            item["phase"] = "acked"
            session.update(state, cmd, actor=actor, correlation=args.id)
        else:
            raise AssertionError(cmd)
        return None


def message_for(state, item, correlation, payload):
    return dict(version=VERSION, epoch=state["epoch"], correlation=correlation,
                sender=item["sender"], recipient=item["recipient"], purpose=item["purpose"],
                until=item["until"], payload=payload)


def ready(queue, mask, deadline):
    remaining = deadline - now()
    if remaining <= 0:
        return False
    poller = select.poll()
    poller.register(queue, mask)
    return any(events & mask for _, events in poller.poll(remaining))


def send(session, args):
    payload = text(args.text, 640)
    deadline = now() + args.wait
    q = None
    try:
        while True:
            with session.lock():
                state = session.read()
                item = exchange(state, args.id, "granted")
                if item["sender"] != args.actor:
                    raise ProtocolError("sender is not admitted")
                if q is None:
                    q = session.queue(item["recipient"], os.O_WRONLY)
                wire = encoded(message_for(state, item, args.id, payload))
                if len(wire) > MESSAGE:
                    raise ProtocolError("oversized message")
                if call(mq_send, q, wire, len(wire), 0, again=True) is not None:
                    item.update(phase="sent", digest=digest(wire).hex())
                    session.update(state, "send", actor=args.actor, correlation=args.id,
                                   sha256=item["digest"])
                    return None
            if not ready(q, select.POLLOUT, deadline):
                raise ProtocolError("recipient queue full")
    finally:
        if q is not None:
            call(mq_close, q)


def receive(session, args):
    deadline = now() + args.wait
    buffer = C.create_string_buffer(MESSAGE)
    q = None
    try:
        while True:
            with session.lock():
                state = session.read()
                if q is None:
                    q = session.queue(args.actor, os.O_RDONLY)
                priority = C.c_uint()
                n = call(mq_receive, q, buffer, MESSAGE, C.byref(priority), again=True)
                if n is not None:
                    wire = buffer.raw[:n]
                    try:
                        msg = json.loads(wire)
                        if (not isinstance(msg, dict) or type(msg.get("correlation")) is not int
                                or msg.get("recipient") != args.actor or priority.value != 0):
                            raise ProtocolError("bad envelope")
                        correlation = msg["correlation"]
                        item = exchange(state, correlation, "sent")
                        if item["recipient"] != args.actor or digest(wire).hex() != item["digest"]:
                            raise ProtocolError("envelope does not match admitted send")
                        payload = msg.get("payload")
                        if (not isinstance(payload, str) or
                                encoded(message_for(state, item, correlation, text(payload, 640))) != wire):
                            raise ProtocolError("noncanonical or incorrectly bound envelope")
                    except (ValueError, ProtocolError, RecursionError):
                        session.update(state, "reject", actor=args.actor, sha256=digest(wire).hex())
                        raise ProtocolError("rejected queued message") from None
                    item["phase"] = "received"
                    session.update(state, "receive", actor=args.actor, correlation=correlation)
                    return msg
            if not ready(q, select.POLLIN, deadline):
                raise ProtocolError("receive timed out")
    finally:
        if q is not None:
            call(mq_close, q)


def bounded(lo, hi):
    def parse(value):
        number = int(value)
        if not lo <= number <= hi:
            raise argparse.ArgumentTypeError(f"expected integer in [{lo}, {hi}]")
        return number
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", required=True, help="private audit path (never send secrets)")
    parser.add_argument("session")
    role = bounded(0, WORKERS - 1)
    parser.add_argument("actor", type=role)
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("init", "cleanup", "snapshot"):
        sub.add_parser(cmd)
    for cmd in ("status", "contract"):
        sub.add_parser(cmd).add_argument("text")
    request = sub.add_parser("request")
    request.add_argument("peer", type=role)
    request.add_argument("purpose")
    grant = sub.add_parser("grant")
    for command in (request, grant):
        command.add_argument("--lifetime", type=bounded(1, 3_600_000), default=600_000,
                             help="validity in milliseconds")
    tx = sub.add_parser("send")
    rx = sub.add_parser("recv")
    for command in (tx, rx):
        command.add_argument("--wait", type=bounded(0, 10_000), default=100,
                             help="queue wait bound in milliseconds")
    for command in (grant, tx, sub.add_parser("ack"), sub.add_parser("revoke")):
        command.add_argument("id", type=bounded(1, 2**64 - 1))
    tx.add_argument("text")
    args = parser.parse_args()
    try:
        session = Session(args.session, args.journal)
        if args.command in ("init", "cleanup"):
            ensure_broker(args.actor)
            if args.command == "cleanup":
                session.cleanup()
            else:
                with session.open_state(creating=True):
                    pass
            return 0
        with session.open_state():
            if args.command == "send":
                result = send(session, args)
            elif args.command == "recv":
                result = receive(session, args)
            else:
                result = process_state(session, args)
        if result is not None:
            print(encoded(result).decode("ascii"))
        return 0
    except (ProtocolError, OSError) as exc:
        print(f"overhaul-coord: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
