#!/usr/bin/env python3
"""Check per-run scalar memoization against independent calls and byte expectations."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
compiler = os.environ.get("ON1XC", sdk / "build/on1x/on1xc")


def check(case, raw):
    plain, memo, repeated, snapshot, cached_snapshot, end = raw.split("NEXT\n")
    assert end == "" and memo == repeated and snapshot == cached_snapshot, case
    if case in ("budget", "denied"):
        assert plain == memo == f"{case}\n0\n0\n" and snapshot == f"{case}\n", case
        return

    first = 42 if case in ("equal", "zero") else 17
    spread = 0 if case == "equal" else 25
    nodes = [
        ("a", "maximum@1", "first", "second", 42),
        ("b", "maximum@1", "first", "second", 42),  # only hit
        ("c", "maximum@1", "second", "first", 42),  # reversed parents
        ("d", "minimum@1", "first", "second", first),
        ("e", "distance@1", "a", "first", spread),
        ("f", "distance@1", "b", "first", spread),  # same numbers as e, distinct parents
    ]
    calls, hits = 5, 1
    if case == "zero":
        nodes = [(n, "distance@1", "first", "second", 0) for n in "ab"]
        calls, hits = 1, 1
    if case == "limit":
        nodes = [(n, "maximum@1", "first", "second", 42) for n in "abcdefghijklmnop"]
        calls, hits = 1, 15

    def evidence(frame, invocations, memo_hits):
        status, c, h, rest = frame.split("\n", 3)
        assert (status, int(c), int(h)) == ("ok", invocations, memo_hits), case
        return rest

    expected = evidence(plain, len(nodes), 0)
    assert evidence(memo, calls, hits) == expected, case
    header, *artifacts, end = expected.split("END\n")
    assert not end and len(artifacts) == 2 + len(nodes)
    value, kind, root, trace = header.split("\n", 3)
    assert trace == "".join(f"{n}={op}({l},{r}):{v}\n" for n, op, l, r, v in nodes), case
    assert (value, kind) == (str(nodes[-1][-1]), "scalar.level@1" if case == "limit"
                             else "scalar.distance@1")

    digests = {}
    for frame, name in zip(artifacts, ["first", "second", *(n[0] for n in nodes)], strict=True):
        digest, data = frame.split("\n", 1)
        assert re.fullmatch("[0-9a-f]{64}", digest) and digest not in digests.values()
        if name in ("first", "second"):
            v = first if name == "first" else 42
            wanted = f"scalar-input@1\nname={name}\nkind=scalar.level@1\nvalue={v}\n"
        else:
            _, op, left, right, v = nodes[len(digests) - 2]
            k = "scalar.distance@1" if op == "distance@1" else "scalar.level@1"
            wanted = (f"scalar-node@1\nid={name}\nowner=finpred.core@1\nhandler={op}\n"
                      f"kind={k}\nleft={digests[left]}\nright={digests[right]}\nvalue={v}\n")
        assert data == wanted, (case, name)
        digests[name] = digest
    assert root == digests[nodes[-1][0]]

    meta, *frozen, end = snapshot.split("END\n")
    assert not end and frozen == artifacts
    status, run_id, manifest = meta.split("\n", 2)
    assert status == "ok" and re.fullmatch("[0-9a-f]{64}", run_id)
    assert manifest == (
        f"scalar-run@1\nplan=automat.scalar-dag@1\nmode=analysis\nbudget={len(nodes)}\n"
        f"first={first}\nsecond=42\noutput={nodes[-1][0]}\n"
        + "".join(f"node={n},{op},{l},{r}\n" for n, op, l, r, _ in nodes)
        + "".join(f"artifact={digest}\n" for digest in digests.values())
        + f"root={root}\n"
    ), case


with tempfile.TemporaryDirectory(prefix="finpred-scalar-memo-") as tmp:
    exe = Path(tmp) / "consumer"
    subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                    ROOT / "tests/scalar_memo_consumer/main.on1x", "--backend", "c11",
                    "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT,
                    "-o", exe], cwd=tmp, check=True)
    for case in ("siblings", "equal", "zero", "limit", "budget", "denied"):
        raw = subprocess.check_output([exe], cwd=tmp, env={"CASE": case}, timeout=20)
        check(case, raw.decode("ascii"))
print("scalar_memo_ok=true positive=4 rejected=2")
