"""Independent selection/serialization oracle and deterministic live-mount process checks."""

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from process_death import await_checkpoint, expect, kill_paused_writer, TIMEOUT


CATALOG = b"finpred-temporal-catalog@1\n"
COMMIT = b"finpred-temporal-commit@1\n"


def canonical_catalog(rows):
    return CATALOG + b"".join((",".join(map(str, r)) + "\n").encode() for r in sorted(rows))


def oracle(catalog, effective, knowledge, keys, rows):
    records = [COMMIT.decode(), f"catalog={catalog}\n", f"effective={effective}\n",
               f"knowledge={knowledge}\n"]
    for key in keys:
        eligible = [r for r in rows if r[0] == key and r[1] <= effective and r[2] <= knowledge]
        if not eligible:
            records.append(f"selection={key},missing\n")
            continue
        rank = max(r[1:4] for r in eligible)
        winners = [r for r in eligible if r[1:4] == rank]
        if len(winners) != 1:
            raise ValueError("ambiguous")
        _, e, k, rev, state, parent = winners[0]
        records.append(f"selection={key},{state},{e},{k},{rev},{parent}\n")
    return "".join(records).encode()


class Store:
    def __init__(self, executable, root):
        self.executable = executable
        self.root = root
        root.mkdir(mode=0o700)
        root_parent = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(root_parent)
        finally:
            os.close(root_parent)
        self.call("provision", expected="")

    def hash(self, data):
        return subprocess.check_output([self.executable, "hash"], input=data, timeout=TIMEOUT).decode().strip()

    def path(self, digest):
        return self.root / "artifacts" / f"blake3-{digest}.txt"

    def seed(self, data):
        digest = self.hash(data)
        # Seed ordinary, complete files without deliberately syncing. The new
        # API must compare and sync them itself before installing a commit.
        self.path(digest).write_bytes(data)
        return digest

    @contextmanager
    def worker(self, mode, *args, pause=None, fail=None, trace=False):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("FP_TEST_PAUSE", "FP_TEST_FAIL_SYNC", "FP_TEST_TRACE")}
            if pause is not None:
                env["FP_TEST_PAUSE"] = pause
            if fail is not None:
                env["FP_TEST_FAIL_SYNC"] = str(fail)
            if trace:
                env["FP_TEST_TRACE"] = "1"
            child = subprocess.Popen([self.executable, str(fd), mode, *map(str, args)],
                                     pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     bufsize=0, env=env)
        finally:
            os.close(fd)
        with child:
            try:
                yield child
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=TIMEOUT)

    def call(self, mode, *args, expected, fail=None, trace=False):
        with self.worker(mode, *args, fail=fail, trace=trace) as child:
            out, _ = child.communicate(timeout=TIMEOUT)
            expect((child.returncode, out.decode().strip()), (0, expected))

    def names(self):
        expect(list((self.root / "runs").iterdir()), [])
        return {p.name: p.stat(follow_symlinks=False).st_ino for p in (self.root / "artifacts").iterdir()}


def check_oracle(executable, root):
    s = Store(executable, root)
    a = s.seed(b"")
    b = s.seed(b"abc")
    expect(a, "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262")
    expect(b, "6437b3ac38465133ffb63b75273a8db548c558465d79db03fd359c6cd5bd9d85")
    tombstone = s.seed(b"withdrawn\n")
    future = s.seed(b"not yet known\n")
    rows = [
        (1, 5, 7, 0, "present", a),
        (1, 5, 7, 0, "present", b),  # winning tie at (5, 7), obsolete at (5, 8)
        (1, 5, 8, 0, "present", a),
        (1, 5, 8, 1, "present", b),
        (1, 6, 10, 1, "withdrawn", tombstone),
        (1, 7, 11, 1, "present", a),
        (2, 8, 4, 1, "present", b),  # independent effective cutoff
        (2, 2, 99, 1, "present", future),  # independent knowledge cutoff
        (3, 1, 1, 1, "present", a),
        (UINT64_MAX, INT64_MAX, INT64_MAX, 2**32 - 1, "present", b),
    ]
    catalog = s.seed(canonical_catalog(rows))
    keys = [1, 2, 3, 4, UINT64_MAX]
    s.call("publish", catalog, 5, 7, *keys, expected="catalog conflict validate unchanged 0 0 -")
    for effective, knowledge in ((0, 0), (5, 8), (6, 10), (7, 11), (8, 8), (7, 99),
                                 (INT64_MAX, INT64_MAX)):
        expected = oracle(catalog, effective, knowledge, keys, rows)
        commit = s.hash(expected)
        s.call("publish", catalog, effective, knowledge, *keys,
               expected=f"commit ok dir-sync created 12 1 {commit}")
        expect(s.path(commit).read_bytes(), expected)
        s.call("replay", commit, expected=f"commit ok read existing 0 0 {commit}")
    last = s.names()
    s.call("publish", catalog, INT64_MAX, INT64_MAX, *keys,
           expected=f"commit ok dir-sync existing 12 0 {commit}")
    s.call("readonly-resume", commit, expected=f"parent denied validate unchanged 0 0 {commit}")
    expect(s.names(), last)

    baseline = oracle(catalog, 0, 0, keys, rows)
    baseline_id = s.hash(baseline)
    revised_rows = rows[:-1]
    revised_catalog = s.seed(canonical_catalog(revised_rows))
    revised = oracle(revised_catalog, 0, 0, keys, revised_rows)
    expect(revised, baseline.replace(catalog.encode(), revised_catalog.encode()))
    revised_id = s.hash(revised)
    expect(revised_id != baseline_id, True)
    s.call("publish", revised_catalog, 0, 0, *keys,
           expected=f"commit ok dir-sync created 12 1 {revised_id}")
    expect(s.path(revised_id).read_bytes(), revised)

    s.path(future).unlink()
    s.call("replay", baseline_id, expected=f"parent missing open unchanged 0 0 {baseline_id}")
    unpublished = s.hash(oracle(catalog, 0, 1, keys, rows))
    s.call("publish", catalog, 0, 1, *keys, expected=f"parent missing open unchanged 6 0 {unpublished}")
    expect(s.path(unpublished).exists(), False)
    s.path(future).write_bytes(b"forged parent\n")
    s.call("replay", baseline_id, expected=f"parent conflict read existing 0 0 {baseline_id}")
    s.path(future).write_bytes(b"not yet known\n")
    forged = s.seed(baseline.replace(b"selection=1,missing", b"selection=1,present"))
    s.call("replay", forged, expected=f"commit conflict validate unchanged 0 0 {baseline_id}")
    s.call("resume", forged, expected=f"commit conflict validate unchanged 0 0 {baseline_id}")
    s.path(baseline_id).write_bytes(b"changed")
    s.call("replay", baseline_id, expected="commit conflict read existing 0 0 -")

    for invalid_catalog in (
        CATALOG + b"1,00,1,0,present," + a.encode() + b"\n",
        canonical_catalog([rows[0], rows[0]]),
        canonical_catalog([(i, 0, 0, 0, "present", a) for i in range(1, 66)]),
        CATALOG + b"18446744073709551616,0,0,0,present," + a.encode() + b"\n",
        CATALOG + b"1,9223372036854775808,0,0,present," + a.encode() + b"\n",
        CATALOG + b"1,0,0,4294967296,present," + a.encode() + b"\n",
    ):
        catalog = s.seed(invalid_catalog)
        s.call("publish", catalog, 5, 7, *keys, expected="catalog invalid validate unchanged 0 0 -")
    empty = s.seed(CATALOG)
    cap = list(range(1, 33))
    expected = oracle(empty, 0, 0, cap, [])
    commit = s.hash(expected)
    s.call("publish", empty, 0, 0, *cap, expected=f"commit ok dir-sync created 4 1 {commit}")
    expect(s.path(commit).read_bytes(), expected)
    max_rows = [(i, 0, 0, 0, "present", a) for i in range(1, 65)]
    full = s.seed(canonical_catalog(max_rows))
    expected = oracle(full, 0, 0, cap, max_rows)
    commit = s.hash(expected)
    s.call("publish", full, 0, 0, *cap, expected=f"commit ok dir-sync created 6 1 {commit}")
    expect(s.path(commit).read_bytes(), expected)
    for ec, kc, ks in ((-1, 0, [1]), (0, -1, [1]), (0, 0, cap + [33]), (0, 0, [2, 1]),
                       (0, 0, [1, 1]), (0, 0, [0])):
        s.call("publish", empty, ec, kc, *ks, expected="query invalid validate unchanged 0 0 -")


UINT64_MAX = 2**64 - 1
INT64_MAX = 2**63 - 1


def process_case(executable, root, checkpoint=None, fail=None, visible=False):
    s = Store(executable, root)
    parent = s.seed(b"primary")
    future = s.seed(b"future")
    rows = [(1, 1, 2, 0, "present", parent), (1, 2, 9, 0, "present", future)]
    catalog = s.seed(canonical_catalog(rows))
    args = (catalog, 2, 2, 1)
    expected = oracle(*args[:3], [args[3]], rows)
    commit = s.hash(expected)
    initial = s.names()
    missing = "commit missing open unchanged 0 0 -"
    verified = f"commit ok read existing 0 0 {commit}"
    if checkpoint:
        with s.worker("publish", *args, pause=checkpoint) as child:
            await_checkpoint(child, checkpoint)
            s.call("replay", commit, expected=verified if visible else missing)
            while_paused = s.names()
            kill_paused_writer(child)
        expect(s.names(), while_paused)
    elif fail == 3:
        s.call("publish", *args, fail=fail, expected=f"parent io file-sync existing 3 0 {commit}")
    elif fail == 8:
        s.call("publish", *args, fail=fail, expected=f"commit io dir-sync created 8 1 {commit}")
    else:
        # Independently prove *which* prerequisites (including future rows)
        # and which directory are synced before the commit's own link.
        directory_inode = (root / "artifacts").stat().st_ino
        prerequisites = [
            event for digest in (parent, future, catalog)
            for event in (f"sync {s.path(digest).stat().st_ino}", f"sync {directory_inode}")
        ]
        with s.worker("publish", *args, trace=True) as writer:
            out, _ = writer.communicate(timeout=TIMEOUT)
        expect(writer.returncode, 0)
        commit_inode = s.path(commit).stat().st_ino
        expect(out.decode().splitlines(), prerequisites + [
            f"sync {commit_inode}", f"link {commit_inode}", f"sync {directory_inode}",
            f"commit ok dir-sync created 8 1 {commit}",
        ])
        s.call("replay", commit, expected=verified, trace=True)
        s.call("resume", commit, trace=True, expected="\n".join(prerequisites + [
            f"sync {commit_inode}", f"sync {directory_inode}", f"commit ok dir-sync existing 8 0 {commit}",
        ]))
        return
    s.call("replay", commit, expected=verified if visible else missing)
    pre_recovery = s.names()
    expect(set(pre_recovery), set(initial) | ({s.path(commit).name} if visible else set()))
    if visible:
        s.call("resume", commit, expected=f"commit ok dir-sync existing 8 0 {commit}")
    else:
        s.call("resume", commit, expected=missing)
        s.call("publish", *args, expected=f"commit ok dir-sync created 8 1 {commit}")
    expect(s.path(commit).read_bytes(), expected)
    s.call("replay", commit, expected=verified)
    final = s.names()
    expect(set(final), set(initial) | {s.path(commit).name})
    expect({p: final[p] for p in pre_recovery}, pre_recovery)


def main(executable):
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix="temporal-") as tmp:
        parent = Path(tmp)
        check_oracle(executable, parent / "oracle")
        for step, visible in (("before-sync-3", False), ("after-sync-7", False),
                              ("after-link", True), ("after-sync-8", True)):
            process_case(executable, parent / step, checkpoint=step, visible=visible)
        for sync, visible in ((3, False), (8, True)):
            process_case(executable, parent / f"fail-{sync}", fail=sync, visible=visible)
        process_case(executable, parent / "ordering")
    print("native_temporal_oracle_and_live_mount_recovery_ok")


if __name__ == "__main__":
    main(sys.argv[1])
