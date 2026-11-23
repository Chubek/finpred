#!/usr/bin/env python3
"""Freeze with the native producer; replay only from files in a fresh process."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
compiler = os.environ.get("ON1XC", sdk / "build/on1x/on1xc")

# Independent BLAKE3-256 fixtures from check_dag_replay.py; golden_id was
# computed with libblake3 over the exact ASCII manifest below (including LF).
hashes = [
    b"d7bba29d68d693f5bca94074acd372bef5a635e18dfce851724a58095d348f27",
    b"c378311fce28b1237559d877812fc1612368f81a6221f6085fc768a092794456",
    b"f7a555ef982f0fd0f70759fe01c84fdfc5e1ddd5b97edd6dbb550ced83feaa0b",
    b"eb7cb8ad7e64ee1259648335e032d61bf031485485d9ba68533699fb648536da",
    b"f3f59aede2d460f6e4c25363919556d703726661ec3d0acf6be7a3af42767967",
]
golden_id = b"e7fcc371e632492f6a007942aa0546fe74c5cf0072bf80ae27a85b5e24fd89b0"
golden_manifest = (
    b"scalar-run@1\nplan=automat.scalar-dag@1\nmode=analysis\nbudget=3\n"
    b"first=17\nsecond=42\noutput=spread\nnode=spread,distance@1,hi,lo\n"
    b"node=hi,maximum@1,first,second\nnode=lo,minimum@1,first,second\n"
    + b"".join(b"artifact=" + h + b"\n" for h in hashes) + b"root=" + hashes[-1] + b"\n"
)


def unpack(frames):
    header, *pairs, end = frames.split(b"END\n")
    assert end == b""
    run_id, manifest = header.split(b"\n", 1)
    return run_id, manifest, [p.split(b"\n", 1) for p in pairs]


def tree(directory):
    return {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
            for p in directory.iterdir()}


with tempfile.TemporaryDirectory(prefix="finpred-scalar-manifest-") as temp:
    work = Path(temp)
    exe = work / "consumer"
    subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                    ROOT / "tests/scalar_manifest_consumer/main.on1x", "--backend", "c11",
                    "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source",
                    "-o", exe], cwd=work, check=True)

    def invoke(directory, **settings):
        # No inherited plan, mode or input parameters in verifier processes.
        r = subprocess.run([exe], cwd=directory, env=settings, timeout=10,
                           capture_output=True, check=True)
        return r.stdout

    def produce(budget=3, mode="analysis", single=False, intermediate=False, duplicate=False, memo=False):
        return invoke(work, TASK="produce", BUDGET=str(budget), MODE=mode,
                      DUPLICATE_WORK="yes" if duplicate else "no", MEMOIZED="yes" if memo else "no",
                      SINGLE="yes" if single else "no", INTERMEDIATE="yes" if intermediate else "no")

    def check(case, snapshot, *, valid=False, rehash=False):
        run_id, manifest, items = snapshot
        directory = work / case
        directory.mkdir()
        (directory / "id").write_bytes(run_id)
        (directory / "manifest").write_bytes(manifest)
        for i, (digest, data) in enumerate(items):
            (directory / f"hash{i}").write_bytes(digest)
            (directory / f"data{i}").write_bytes(data)
        before = tree(directory)
        out = invoke(directory, TASK="rehashed" if rehash else "verify", COUNT=str(len(items)))
        assert out == (b"true\n" if valid else b"false\n"), (case, out)
        assert before == tree(directory), case

    frozen = produce()
    run_id, manifest, items = unpack(frozen)
    assert (run_id, manifest) == (golden_id, golden_manifest)
    assert [digest for digest, _ in items] == hashes
    assert produce() == frozen
    check("golden", (run_id, manifest, items), valid=True)
    # Verify a warmed calculation's bundle in a separate process with no cache.
    reused = produce(duplicate=True, memo=True)
    assert reused == produce(duplicate=True)
    check("from-memo", unpack(reused), valid=True)
    intermediate = unpack(produce(intermediate=True))
    assert intermediate[1].endswith(b"root=" + hashes[2] + b"\n")
    check("intermediate", intermediate, valid=True)
    for budget in range(1, 17):
        snapshot = unpack(produce(budget, single=True))
        assert f"budget={budget}\n".encode() in snapshot[1]
        check(f"budget-{budget}", snapshot, valid=True)
    for budget, mode in [(0, "analysis"), (17, "analysis"), (2, "analysis"), (3, "execution")]:
        assert produce(budget, mode) == b"failed\n", (budget, mode)

    check("wrong-id", (hashes[0], manifest, items))
    check("changed-budget", (run_id, manifest.replace(b"budget=3", b"budget=4"), items))
    check("missing", (run_id, manifest, items[:-1]))
    check("extra", (run_id, manifest, items + [items[0]]))
    check("swapped", (run_id, manifest, [items[1], items[0], *items[2:]]))
    check("digest", (run_id, manifest, [(hashes[1], items[0][1]), *items[1:]]))
    check("bytes", (run_id, manifest, [*items[:-1], (hashes[-1], items[-1][1] + b"\n")]))
    edits = {
        "leading-zero": (b"first=17", b"first=017"),
        "sign": (b"budget=3", b"budget=+3"),
        "budget-large": (b"budget=3", b"budget=17"),
        "overflow": (b"second=42", b"second=18446744073709551658"),
        "input-range": (b"second=42", b"second=1000000000001"),
        "crlf": (b"\n", b"\r\n"),
        "bad-order": (b"first=17\nsecond=42", b"second=42\nfirst=17"),
        "bad-plan": (b"dag@1", b"dag@2"),
        "bad-mode": (b"mode=analysis", b"mode=execution"),
        "extra-port": (b"spread,distance@1,hi,lo", b"spread,distance@1,hi,lo,lo"),
        "artifact-case": (hashes[0], hashes[0].upper()),
        "bad-root": (b"root=" + hashes[-1], b"root=" + hashes[2]),
        "wrong-hash": (b"artifact=" + hashes[0], b"artifact=" + hashes[1]),
        "wrong-input": (b"first=17", b"first=18"),
        "unknown-handler": (b"maximum@1", b"maximum@2"),
    }
    malformed = {case: manifest.replace(old, new) for case, (old, new) in edits.items()}
    malformed.update(no_lf=manifest[:-1], extra_lf=manifest + b"\n", oversized=manifest + b"x"*4096)
    for case, raw in malformed.items():
        assert raw != manifest
        check(case, (run_id, raw, items), rehash=True)

print(f"scalar_manifest_ok=true verified=19 rejected={7 + len(malformed)} failed_freezes=4")
