#!/usr/bin/env python3
"""Compile a separate host for typed selection and frozen, read-only replay."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SELECT = b"node=picked,select@1,spread,hi,lo\n"
SPREAD = b"let spread = distance@1 hi lo\n"
PICK = b"let picked = select@1 spread hi lo\n"
V2 = b"scalar-run@2\n"
DAG2 = b"plan=automat.scalar-dag@2\n"

# Computed independently with libblake3, including LF in every payload.
FIRST = b"d7bba29d68d693f5bca94074acd372bef5a635e18dfce851724a58095d348f27"
SECOND = b"c378311fce28b1237559d877812fc1612368f81a6221f6085fc768a092794456"
HI = b"f7a555ef982f0fd0f70759fe01c84fdfc5e1ddd5b97edd6dbb550ced83feaa0b"
LO = b"eb7cb8ad7e64ee1259648335e032d61bf031485485d9ba68533699fb648536da"
DISTANCE = b"f3f59aede2d460f6e4c25363919556d703726661ec3d0acf6be7a3af42767967"
PICKED = b"1b2480d32ecf278e2abc4c3c4fa52a93dc79c7c0489f3635045c2fec4368cb72"
RUN_ID = b"396debcfd132cb40dcd87f42e5bcdf5dfe5150a6f3ebd45282e2925f8ee6ae78"
SOURCE_ID = b"bac312b6b3bb32b3b678004391e479cc578adb7f0088337371263057122b56a9"
HI_TRACE = b"hi=maximum@1(first,second):42\n"
LO_TRACE = b"lo=minimum@1(first,second):17\n"
SPREAD_TRACE = b"spread=distance@1(hi,lo):25\n"
POSITIVE_TRACE = b"picked=select@1(spread,hi,lo):42\n"


def golden():
    def binary(node, handler, kind, left, right, value):
        return (b"scalar-node@1\nid=" + node + b"\nowner=finpred.core@1\nhandler=" + handler
                + b"\nkind=scalar." + kind + b"@1\nleft=" + left + b"\nright=" + right
                + b"\nvalue=" + value + b"\n")

    items = [
        (FIRST, b"scalar-input@1\nname=first\nkind=scalar.level@1\nvalue=17\n"),
        (SECOND, b"scalar-input@1\nname=second\nkind=scalar.level@1\nvalue=42\n"),
        (HI, binary(b"hi", b"maximum@1", b"level", FIRST, SECOND, b"42")),
        (LO, binary(b"lo", b"minimum@1", b"level", FIRST, SECOND, b"17")),
        (DISTANCE, binary(b"spread", b"distance@1", b"distance", HI, LO, b"25")),
        (PICKED, b"scalar-select@1\nid=picked\nowner=finpred.core@1\nhandler=select@1\n"
                 b"kind=scalar.level@1\ncondition=" + DISTANCE + b"\npositive=" + HI
                 + b"\nzero=" + LO + b"\nvalue=42\n"),
    ]
    manifest = (
        V2 + DAG2 + b"mode=analysis\nbudget=4\nfirst=17\nsecond=42\noutput=picked\n"
        + SELECT + b"node=spread,distance@1,hi,lo\nnode=hi,maximum@1,first,second\n"
        + b"node=lo,minimum@1,first,second\n"
        + b"".join(b"artifact=" + digest + b"\n" for digest, _ in items)
        + b"root=" + PICKED + b"\n"
    )
    trace = b"scalar.level@1:42\n" + PICKED + b"\n" + HI_TRACE + LO_TRACE + SPREAD_TRACE + POSITIVE_TRACE
    return trace, (RUN_ID, manifest, items)


def unpack(payload):
    trace, header, *pairs, end = payload.split(b"END\n")
    assert end == b""
    run_id, manifest = header.split(b"\n", 1)
    entries = [tuple(pair.split(b"\n", 1)) for pair in pairs]
    return trace, (run_id, manifest, entries)


def tree(directory):
    return {p.name: (p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes())
            for p in directory.iterdir()}


def replace(raw, old, new):
    assert raw.count(old) == 1, old
    return raw.replace(old, new)


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    source = (ROOT / "strategies/scalar-select.ottomat").read_bytes()
    with tempfile.TemporaryDirectory(prefix="finpred-scalar-selection-") as tmp:
        work = Path(tmp)
        exe = work / "consumer"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-build.py",
            ROOT / "tests/scalar_selection_consumer/main.on1x", "--backend", "c11",
            "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT, "-o", exe,
        ], check=True, cwd=work)

        def invoke(task, directory=work, **env):
            run = subprocess.run([exe], cwd=directory, env={"TASK": task, **env},
                                 capture_output=True, timeout=10)
            assert run.returncode == 0 and run.stderr == b"", (task, env, run.stderr, run.stdout)
            return run.stdout

        def native(shape="default", *, budget=4, mode="analysis", first=17, second=42, memo=False):
            return invoke("native", SHAPE=shape, MODE=mode, BUDGET=str(budget),
                          FIRST=str(first), SECOND=str(second), MEMO="yes" if memo else "no")

        def dsl(raw=source, *, budget=4, mode="analysis", first=17, second=42):
            (work / "strategy").write_bytes(raw)
            return invoke("dsl", MODE=mode, BUDGET=str(budget), FIRST=str(first), SECOND=str(second))

        def accepted(raw=source, **settings):
            lower, freeze, version, digest, payload = dsl(raw, **settings).split(b"\n", 4)
            assert lower == freeze == b"ok 0 0", (lower, freeze)
            assert version == b"ottomat.scalar-lowering@2"
            assert re.fullmatch(rb"[0-9a-f]{64}", digest), digest
            return digest, payload

        def digest_of(raw):
            (work / "hash-input").write_bytes(raw)
            digest = invoke("hash").removesuffix(b"\n")
            assert re.fullmatch(rb"[0-9a-f]{64}", digest), digest
            return digest

        def check(case, snapshot, *, valid=True, decoded=True):
            run_id, manifest, items = snapshot
            directory = work / case
            directory.mkdir()
            (directory / "id").write_bytes(run_id)
            (directory / "manifest").write_bytes(manifest)
            for idx, (digest, raw) in enumerate(items):
                (directory / f"hash{idx}").write_bytes(digest)
                (directory / f"data{idx}").write_bytes(raw)
            before = tree(directory)
            assert invoke("decode", directory) == (b"true\n" if decoded else b"false\n"), case
            assert invoke("verify", directory, COUNT=str(len(items))) == (b"true\n" if valid else b"false\n"), case
            assert tree(directory) == before, case

        positive = native()
        assert positive.startswith(b"ok ok ok\n")
        default_payload = positive.removeprefix(b"ok ok ok\n")
        assert unpack(default_payload) == golden()
        assert accepted() == (SOURCE_ID, default_payload)
        assert native(memo=True) == positive == native()
        _, snapshot = golden()
        check("golden", snapshot)

        # Distance comes from graph inputs, not the branch producers, so either
        # branch can be unselected with distinct values and must still execute.
        for shape, bindings, distance, value in [
            ("zero", b"first first", b"0", b"17"),
            ("positive", b"first second", b"25", b"42"),
        ]:
            raw = replace(source, SPREAD, b"let spread = distance@1 " + bindings + b"\n")
            _, payload = accepted(raw)
            assert native(shape) == native(shape, memo=True) == b"ok ok ok\n" + payload
            trace, result = unpack(payload)
            root, selected = result[2][-1]
            assert trace == (
                b"scalar.level@1:" + value + b"\n" + root + b"\n"
                + b"spread=distance@1(" + bindings.replace(b" ", b",") + b"):" + distance + b"\n"
                + HI_TRACE + LO_TRACE + b"picked=select@1(spread,hi,lo):" + value + b"\n"
            )
            spread, hi, lo = (d for d, _ in result[2][2:5])
            assert b"\ncondition=" + spread + b"\npositive=" + hi + b"\nzero=" + lo + b"\n" in selected
            check(shape, result)

        # Only "again" may reuse "picked". "reroute" changes only the zero
        # parent digest (lo and first both equal 17), and still produces 42.
        memo = native("memo_roles", budget=6)
        assert memo == native("memo_roles", budget=6, memo=True)
        trace, memo_snapshot = unpack(memo.removeprefix(b"ok ok ok\n"))
        assert trace == (b"scalar.level@1:42\n" + PICKED + b"\n" + HI_TRACE + LO_TRACE
                         + SPREAD_TRACE + POSITIVE_TRACE + b"reroute=select@1(spread,hi,first):42\n"
                         b"again=select@1(spread,hi,lo):42\n")
        check("memo-roles", memo_snapshot)

        # Equal branch values, but different parent artifacts. Swap the role
        # digests and recompute ALL affected hashes so the mutation cannot be
        # detected just by rehashing, or by comparing the numeric result.
        _, payload = accepted(first=42)
        assert native(first=42) == b"ok ok ok\n" + payload
        _, equal = unpack(payload)
        _, manifest, items = equal
        assert all(raw.endswith(b"\nvalue=42\n") for _, raw in items[2:4])
        hi, lo = (d for d, _ in items[2:4])
        assert hi != lo
        original, selected = items[-1]
        swapped = replace(selected, b"positive=" + hi + b"\nzero=" + lo,
                          b"positive=" + lo + b"\nzero=" + hi)
        forged = digest_of(swapped)
        changed = manifest.replace(original, forged)
        swapped_items = [*items[:-1], (forged, swapped)]
        check("equal", equal)
        check("role-swap", (digest_of(changed), changed, swapped_items), valid=False)
        # The exact same role-swapped artifact is valid under a plan that
        # explicitly swaps the roles; that plan has a different identity.
        legitimate = replace(changed, SELECT, b"node=picked,select@1,spread,lo,hi\n")
        _, reversed_program = accepted(replace(source, PICK, b"let picked = select@1 spread lo hi\n"), first=42)
        assert unpack(reversed_program)[1] == (digest_of(legitimate), legitimate, swapped_items)
        check("rebound-roles", unpack(reversed_program)[1])

        native_rejections = [
            ("condition_type", "type_mismatch"),
            ("positive_type", "type_mismatch"),
            ("zero_type", "type_mismatch"),
            ("missing", "missing_port"),
            ("cycle", "cycle"),
            ("arity", "invalid_node"),
            ("legacy", "invalid_node"),
            ("legacy_binary", "unknown_handler"),
            ("action_handler", "unknown_handler"),
        ]
        for shape, reason in native_rejections:
            assert native(shape) == f"{reason} {reason} {reason}\n".encode(), shape
        assert native(budget=3) == b"budget budget budget\n"
        assert native(mode="execution") == b"denied denied denied\n"

        ir_rejections = [
            (PICK, b"let picked = select@1 hi hi lo\n", b"type_mismatch 13 1"),
            (PICK, b"let picked = select@1 spread spread lo\n", b"type_mismatch 13 1"),
            (PICK, b"let picked = select@1 spread hi spread\n", b"type_mismatch 13 1"),
            (PICK, b"let picked = select@1 spread hi absent\n", b"missing_port 13 1"),
            (PICK, b"let picked = select@1 spread hi\n", b"syntax 9 1"),
            (b"import select@1\n", b"", b"undeclared_import 8 1"),
            (b"effect pure\n", b"effect action\n", b"denied 4 1"),
            (b"import select@1\n", b"import publish@1\n", b"unknown_handler 8 1"),
        ]
        for old, new, expected in ir_rejections:
            assert dsl(replace(source, old, new)) == (expected + b"\n") * 2, (new, expected)
        # Only the unselected zero port closes this cycle.
        cyclic = replace(source, SPREAD, b"let spread = distance@1 first second\n")
        cyclic = replace(cyclic, b"minimum@1 first second\n", b"minimum@1 picked second\n")
        assert dsl(cyclic) == b"cycle 13 1\n" * 2
        v3 = replace(source, b"ottomat 4\n", b"ottomat 3\n")
        assert dsl(v3) == b"source_limit 9 33\n" * 2  # v3 retains its six-token lexer
        assert dsl(replace(v3, PICK, b"let picked = select@1 spread hi\n")) == b"unknown_handler 8 1\n" * 2
        assert dsl(budget=3) == b"budget 13 1\n" * 2
        assert dsl(mode="execution") == b"denied 13 1\n" * 2

        _, manifest, items = snapshot
        old_header = replace(manifest, V2, b"scalar-run@1\n")
        old_plan = replace(manifest, DAG2, b"plan=automat.scalar-dag@1\n")
        downgrade = replace(old_header, DAG2, b"plan=automat.scalar-dag@1\n")
        short = b"node=picked,select@1,spread,hi\n"
        strict = {
            "header-only": old_header, "plan-only": old_plan, "downgrade": downgrade,
            "downgrade-short": replace(downgrade, SELECT, short),
            "v2-missing-role": replace(manifest, SELECT, short),
            "v2-extra-role": replace(manifest, SELECT, SELECT[:-1] + b",lo\n"),
            "v2-empty-role": replace(manifest, SELECT, SELECT[:-3] + b"\n"),
        }
        for case, bad in strict.items():
            check(case, (digest_of(bad), bad, items), valid=False, decoded=False)

    print("scalar_selection_ok=true golden_runs=1 branch_runs=2 memo_runs=1 "
          f"verified=6 native_rejected={len(native_rejections) + 2} "
          f"source_rejected={len(ir_rejections) + 5} replay_rejected={len(strict) + 1}")


if __name__ == "__main__":
    main()
