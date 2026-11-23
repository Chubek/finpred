#!/usr/bin/env python3
"""Exercise the linked midpoint handler through native, Ottomat, and replay hosts."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from ottomat_build import flags

ROOT = Path(__file__).resolve().parents[1]
V3 = b"scalar-run@3\n"
DAG3 = b"plan=automat.scalar-dag@3\n"
DECLARATIONS = (
    b"node=midpoint,midpoint@1,hi,lo\n"
    b"node=hi,maximum@1,first,second\n"
    b"node=lo,minimum@1,first,second\n"
)
LEVEL_MAX = 10**12

# Independent libblake3 golden for the canonical 17/42, budget-3 fixture.
HASHES = [
    b"d7bba29d68d693f5bca94074acd372bef5a635e18dfce851724a58095d348f27",
    b"c378311fce28b1237559d877812fc1612368f81a6221f6085fc768a092794456",
    b"f7a555ef982f0fd0f70759fe01c84fdfc5e1ddd5b97edd6dbb550ced83feaa0b",
    b"eb7cb8ad7e64ee1259648335e032d61bf031485485d9ba68533699fb648536da",
    b"fd8953f3efbab026e091c039a1affe4ffc7204ac78621e17ef84c691a0220503",
]
RUN_ID = b"8b5bf2d4db688b9b40f2921f3dbd835311af8fcaff264ea72ee5e370a896bd56"
SOURCE_ID = b"560ca9e2df55604d8b7f8fa18d942f0bba23e53435ddad6991faa8c8c6cd9529"


def unpack(payload):
    trace, header, *pairs, end = payload.split(b"END\n")
    assert end == b""
    run_id, manifest = header.split(b"\n", 1)
    return trace, (run_id, manifest, [tuple(pair.split(b"\n", 1)) for pair in pairs])


def expected(first, second, budget, digests):
    """Construct expected bytes without using the producer to determine semantics."""
    a, b, hi, lo, mid = digests
    high, low = max(first, second), min(first, second)
    value = (first + second) // 2

    def input_bytes(name, n):
        return f"scalar-input@1\nname={name}\nkind=scalar.level@1\nvalue={n}\n".encode()

    def node_bytes(name, owner, handler, left, right, n):
        return (f"scalar-node@1\nid={name}\nowner={owner}\nhandler={handler}\n"
                f"kind=scalar.level@1\n".encode()
                + b"left=" + left + b"\nright=" + right + f"\nvalue={n}\n".encode())

    entries = [
        input_bytes("first", first),
        input_bytes("second", second),
        node_bytes("hi", "finpred.core@1", "maximum@1", a, b, high),
        node_bytes("lo", "finpred.core@1", "minimum@1", a, b, low),
        node_bytes("midpoint", "scalar-diagnostics@1", "midpoint@1", hi, lo, value),
    ]
    manifest = (
        V3 + DAG3 + f"mode=analysis\nbudget={budget}\nfirst={first}\nsecond={second}\n".encode()
        + b"output=midpoint\n" + DECLARATIONS
        + b"".join(b"artifact=" + digest + b"\n" for digest in digests) + b"root=" + mid + b"\n"
    )
    trace = (
        f"scalar.level@1:{value}\n".encode() + mid + b"\n"
        + (f"hi=maximum@1(first,second):{high}\nlo=minimum@1(first,second):{low}\n"
           f"midpoint=midpoint@1(hi,lo):{value}\n").encode()
    )
    return trace, manifest, entries


def tree(directory):
    result = {}
    for p in [directory, *directory.iterdir()]:
        st = p.stat()
        result[p.name] = (st.st_ino, st.st_mode, st.st_mtime_ns, st.st_ctime_ns,
                          p.read_bytes() if p.is_file() else None)
    return result


def replace(raw, old, new):
    assert raw.count(old) == 1, old
    return raw.replace(old, new)


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    source = (ROOT / "strategies/scalar-midpoint.ottomat").read_bytes()
    midpoint_import = b"import midpoint@1\n"
    midpoint_node = b"let midpoint = midpoint@1 hi lo\n"
    with tempfile.TemporaryDirectory(prefix="finpred-scalar-registry-") as tmp:
        work = Path(tmp)
        exe = work / "consumer"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-build.py",
            ROOT / "tests/scalar_registry_consumer/main.on1x", "--backend", "c11",
            "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT,
            *flags(compiler, sdk, work), "-o", exe,
        ], check=True, cwd=work)

        def invoke(task, directory=work, **env):
            result = subprocess.run([exe], cwd=directory, env={"TASK": task, **env},
                                    capture_output=True, timeout=10)
            assert result.returncode == 0 and result.stderr == b"", (
                task, env, result.returncode, result.stderr, result.stdout)
            return result.stdout

        def producer(task, *, first=17, second=42, budget=3, mode="analysis", **env):
            return invoke(task, FIRST=str(first), SECOND=str(second), BUDGET=str(budget),
                          MODE=mode, **env)

        def dsl(raw=source, **settings):
            (work / "strategy").write_bytes(raw)
            return producer("dsl", **settings)

        def digest_of(raw):
            (work / "hash-input").write_bytes(raw)
            digest = invoke("hash").removesuffix(b"\n")
            assert re.fullmatch(rb"[0-9a-f]{64}", digest), digest
            return digest

        def accepted(raw=source, **settings):
            lower, freeze, version, digest, payload = dsl(raw, **settings).split(b"\n", 4)
            assert lower == freeze == b"ok 0 0", (lower, freeze)
            assert version == b"ottomat.scalar-lowering@3", version
            assert digest == digest_of(raw)
            return digest, payload

        def verify(case, snapshot, *, valid=True, decoded=None):
            run_id, manifest, items = snapshot
            directory = work / case
            directory.mkdir()
            (directory / "id").write_bytes(run_id)
            (directory / "manifest").write_bytes(manifest)
            for idx, (digest, raw) in enumerate(items):
                (directory / f"hash{idx}").write_bytes(digest)
                (directory / f"data{idx}").write_bytes(raw)
            before = tree(directory)
            grammar, replay = invoke("verify", directory, COUNT=str(len(items))).split()
            if decoded is not None:
                assert grammar == (b"true" if decoded else b"false"), (case, grammar)
            assert replay == (b"true" if valid else b"false"), (case, replay)
            assert tree(directory) == before, case

        snapshots = {}
        for case, first, second, budget in [
            ("golden", 17, 42, 3),
            ("swapped-inputs", 42, 17, 3),
            ("upper-odd", LEVEL_MAX - 1, LEVEL_MAX, 16),
            ("upper-equal", LEVEL_MAX, LEVEL_MAX, 16),
            ("lower-odd", 0, 1, 3),
        ]:
            settings = dict(first=first, second=second, budget=budget)
            digest, payload = accepted(**settings)
            native = producer("native", **settings)
            assert native == producer("native", MEMO="yes", **settings)
            assert native == b"ok ok ok\n" + payload, case
            trace, snapshot = unpack(payload)
            run_id, manifest, items = snapshot
            digests = [d for d, _ in items]
            if case == "golden":
                assert (run_id, digest, digests) == (RUN_ID, SOURCE_ID, HASHES)
            assert (trace, manifest, [raw for _, raw in items]) == expected(first, second, budget, digests)
            assert all(d == digest_of(raw) for d, raw in items)
            assert run_id == digest_of(manifest)
            verify(case, snapshot, decoded=True)
            snapshots[case] = snapshot

        _, manifest, items = snapshots["golden"]
        root, data = items[-1]
        for case, old, new in [
            ("owner", b"owner=scalar-diagnostics@1\n", b"owner=finpred.core@1\n"),
            ("handler", b"handler=midpoint@1\n", b"handler=maximum@1\n"),
            ("value", b"value=29\n", b"value=30\n"),
        ]:
            # Keep all digests consistent, then require semantic replay to reject.
            forged = replace(data, old, new)
            altered_root = digest_of(forged)
            altered_manifest = replace(manifest, b"artifact=" + root, b"artifact=" + altered_root)
            altered_manifest = replace(altered_manifest, b"root=" + root, b"root=" + altered_root)
            verify(case, (digest_of(altered_manifest), altered_manifest,
                          [*items[:-1], (altered_root, forged)]), valid=False, decoded=True)

        mixed = replace(manifest, V3, b"scalar-run@2\n")
        verify("mixed-version", (digest_of(mixed), mixed, items), valid=False, decoded=False)
        downgrade = replace(mixed, DAG3, b"plan=automat.scalar-dag@2\n")
        # A binary declaration still fits the old grammar; replay must reject it
        # because the old graph cannot resolve midpoint.
        verify("rehashed-v2-downgrade", (digest_of(downgrade), downgrade, items),
               valid=False, decoded=True)

        native_rejections = [
            (dict(SHAPE="legacy_one"), b"unknown_handler unknown_handler unknown_handler"),
            (dict(SHAPE="legacy_two"), b"unknown_handler unknown_handler unknown_handler"),
            (dict(SHAPE="unknown"), b"unknown_handler unknown_handler unknown_handler"),
            (dict(SHAPE="type"), b"type_mismatch type_mismatch type_mismatch"),
            (dict(mode="execution"), b"denied denied denied"),
            (dict(budget=2), b"budget budget budget"),
            (dict(first=-1), b"ok invalid_input invalid_input"),
            (dict(second=LEVEL_MAX + 1), b"ok invalid_input invalid_input"),
        ]
        for settings, expected_status in native_rejections:
            assert producer("native", **settings) == expected_status + b"\n", settings

        def reject(raw, status, *, freeze=None, **settings):
            result = dsl(raw, **settings)
            assert result == status + b"\n" + (freeze or status) + b"\n", (raw, settings, result)

        for version in (b"3", b"4"):
            old = replace(source, b"ottomat 5\n", b"ottomat " + version + b"\n")
            reject(old, b"unknown_handler 7 1")
            # Even an unused import is unavailable in a legacy dialect.
            unused = replace(replace(old, midpoint_node, b""), b"emit midpoint\n", b"emit hi\n")
            reject(unused, b"unknown_handler 7 1")

        reject(replace(source, midpoint_import, b""), b"undeclared_import 7 1")
        reject(replace(source, midpoint_import, b"import midpoint@2\n"), b"unknown_handler 7 1")
        bad_type = replace(source, b"import maximum@1\n", b"import distance@1\n")
        bad_type = replace(bad_type, b"let hi = maximum@1 first second\n",
                           b"let hi = distance@1 first second\n")
        reject(bad_type, b"type_mismatch 11 1")
        reject(replace(source, b"effect pure\n", b"effect action\n"), b"denied 4 1")
        reject(source, b"denied 11 1", mode="execution")
        reject(source, b"budget 11 1", budget=2)
        reject(source, b"ok 0 0", freeze=b"budget 0 0", budget=17)
        reject(source, b"ok 0 0", freeze=b"invalid_input 0 0", second=LEVEL_MAX + 1)

    print(f"scalar_registry_ok=true verified={len(snapshots)} native_rejected={len(native_rejections)} "
          "source_rejected=12 replay_rejected=5")


if __name__ == "__main__":
    main()
