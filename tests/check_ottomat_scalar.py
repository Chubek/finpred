#!/usr/bin/env python3
"""Compile an independent Ottomat v3 consumer and pin parity with the native DAG."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TRACE = (
    b"hi=maximum@1(first,second):42\n"
    b"lo=minimum@1(first,second):17\n"
    b"spread=distance@1(hi,lo):25\n"
)


def golden():
    # Same independent `scalar-run@1` pins as check_scalar_manifest.py.
    run_id = b"e7fcc371e632492f6a007942aa0546fe74c5cf0072bf80ae27a85b5e24fd89b0"
    first = b"d7bba29d68d693f5bca94074acd372bef5a635e18dfce851724a58095d348f27"
    second = b"c378311fce28b1237559d877812fc1612368f81a6221f6085fc768a092794456"
    hi = b"f7a555ef982f0fd0f70759fe01c84fdfc5e1ddd5b97edd6dbb550ced83feaa0b"
    lo = b"eb7cb8ad7e64ee1259648335e032d61bf031485485d9ba68533699fb648536da"
    spread = b"f3f59aede2d460f6e4c25363919556d703726661ec3d0acf6be7a3af42767967"
    manifest = (
        b"scalar-run@1\nplan=automat.scalar-dag@1\nmode=analysis\nbudget=3\n"
        b"first=17\nsecond=42\noutput=spread\nnode=spread,distance@1,hi,lo\n"
        b"node=hi,maximum@1,first,second\nnode=lo,minimum@1,first,second\n"
        + b"".join(b"artifact=" + item + b"\n" for item in (first, second, hi, lo, spread))
        + b"root=" + spread + b"\n"
    )

    def input_entry(digest, name, value):
        return digest + b"\nscalar-input@1\nname=" + name + b"\nkind=scalar.level@1\nvalue=" + value + b"\n"

    def node_entry(digest, name, op, kind, left, right, value):
        return (digest + b"\nscalar-node@1\nid=" + name + b"\nowner=finpred.core@1\nhandler="
                + op + b"\nkind=scalar." + kind + b"@1\nleft=" + left + b"\nright=" + right
                + b"\nvalue=" + value + b"\n")

    return b"END\n".join((
        b"scalar.distance@1:25\n" + spread + b"\n" + TRACE,
        run_id + b"\n" + manifest,
        input_entry(first, b"first", b"17"),
        input_entry(second, b"second", b"42"),
        node_entry(hi, b"hi", b"maximum@1", b"level", first, second, b"42"),
        node_entry(lo, b"lo", b"minimum@1", b"level", first, second, b"17"),
        node_entry(spread, b"spread", b"distance@1", b"distance", hi, lo, b"25"),
        b"",
    ))


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    source = (ROOT / "strategies/scalar-spread.ottomat").read_bytes()
    lines = source.splitlines(keepends=True)

    def edit(old, new):
        assert source.count(old) == 1, old
        return source.replace(old, new)

    with tempfile.TemporaryDirectory(prefix="finpred-ottomat-scalar-") as tmp:
        work = Path(tmp)
        exe = work / "consumer"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-build.py",
            ROOT / "tests/ottomat_scalar_consumer/main.on1x", "--backend", "c11",
            "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT, "-o", exe,
        ], check=True, cwd=work)

        def run(raw=source, *, task="lower", mode="analysis", budget=3, first=17):
            (work / "strategy").write_bytes(raw)
            call = subprocess.run([exe], cwd=work, env={
                "TASK": task, "MODE": mode, "BUDGET": str(budget), "FIRST": str(first),
            }, capture_output=True, timeout=10)
            assert call.returncode == 0, (raw[:200], call.returncode, call.stderr)
            return call.stdout

        def accepted(raw=source, **settings):
            lower, frozen, digest, payload = run(raw, **settings).split(b"\n", 3)
            assert lower == frozen == b"ok 0 0", (lower, frozen)
            assert re.fullmatch(rb"[0-9a-f]{64}", digest), digest
            return digest, payload

        native = run(task="native")
        assert native == golden()
        digest, payload = accepted()
        assert payload == native
        reordered = b"".join([*lines[:4], lines[6], *lines[4:6], *lines[7:]])
        alternate, equivalent = accepted(reordered)
        assert alternate != digest and equivalent == native
        assert accepted() == (digest, native)

        # One import and one node are enough; node IDs may use all 32 bytes.
        name = b"a" * 32
        minimal = b"".join(lines[:5]) + b"let " + name + b" = maximum@1 first second\nemit " + name + b"\n"
        _, one = accepted(minimal, budget=1)
        head = one.split(b"END\n", 1)[0].splitlines()
        assert head[0] == b"scalar.level@1:42"
        assert head[2:] == [name + b"=maximum@1(first,second):42"]

        # A registered but unused import is legal. 16 nodes is the inclusive limit.
        declarations = [
            f"let {ident} = maximum@1 {parent} second\n".encode()
            for ident, parent in zip("abcdefghijklmnopq", ["first", *"abcdefghijklmnop"])
        ]
        prefix = b"".join(lines[:7])
        max_plan = prefix + b"".join(declarations[:16]) + b"emit p\n"
        _, chain = accepted(max_plan, budget=16)
        header = chain.split(b"END\n", 1)[0].splitlines()
        assert header[0] == b"scalar.level@1:42"
        assert header[2:] == [
            f"{ident}=maximum@1({parent},second):42".encode()
            for ident, parent in zip("abcdefghijklmnop", ["first", *"abcdefghijklmno"])
        ]

        rejections = [
            ("old syntax v1", edit(b"ottomat 3", b"ottomat 1"), "syntax 1 1"),
            ("old syntax v2", edit(b"ottomat 3", b"ottmat 2"), "syntax 1 1"),
            ("wrong input name", edit(lines[1], b"input second scalar.level@1\n"), "syntax 2 1"),
            ("wrong input type", edit(lines[2], b"input second scalar.distance@1\n"), "syntax 3 1"),
            ("wrong input version", edit(lines[2], b"input second scalar.level@2\n"), "syntax 3 1"),
            ("malformed equality", edit(lines[8], b"let hi == maximum@1 first second\n"), "syntax 9 1"),
            ("extra statement", source + b"emit hi\n", "syntax 12 1"),
            ("missing emit", b"".join(lines[:-1]), "syntax 11 1"),
            ("duplicate import", edit(lines[5], lines[4]), "duplicate_import 6 1"),
            ("unknown import", edit(lines[4], b"import maximum@2\n"), "unknown_handler 5 1"),
            ("missing import", edit(lines[5], b""), "undeclared_import 9 1"),
            ("no imports", b"".join(lines[:4] + lines[7:]), "syntax 5 1"),
            ("late import", b"".join(lines[:6] + lines[7:8] + lines[6:7] + lines[8:]), "undeclared_import 7 1"),
            ("no nodes", b"".join(lines[:7] + lines[-1:]), "syntax 8 1"),
            ("effect", edit(b"effect pure", b"effect network"), "denied 4 1"),
            ("incompatible edge", edit(lines[8], b"let hi = maximum@1 spread second\n"), "type_mismatch 11 1"),
            ("missing edge", edit(lines[8], b"let hi = maximum@1 absent second\n"), "missing_port 11 1"),
            ("cycle", edit(b"maximum@1 first second\nlet lo = minimum@1 first second",
                           b"maximum@1 lo second\nlet lo = minimum@1 hi second"), "cycle 11 1"),
            ("duplicate node", edit(b"let lo", b"let hi"), "duplicate 11 1"),
            ("invalid node ID", edit(b"let lo", b"let " + b"x" * 33), "invalid_node 11 1"),
            ("invalid output", edit(b"emit spread", b"emit first"), "missing_output 11 1"),
            ("CRLF", edit(lines[1], lines[1][:-1] + b"\r\n"), "syntax 2 27"),
            ("tab", edit(b"import minimum", b"import\tminimum"), "syntax 6 7"),
            ("non-ASCII", edit(b"import minimum", b"import m\xc3\xadnimum"), "syntax 6 9"),
            ("blank line", edit(lines[3], b"\n" + lines[3]), "syntax 4 1"),
            ("leading space", edit(lines[3], b" " + lines[3]), "syntax 4 1"),
            ("trailing space", edit(b"effect pure", b"effect pure "), "syntax 4 12"),
            ("double space", edit(b"effect pure", b"effect  pure"), "syntax 4 8"),
            ("missing LF", source[:-1], "syntax 11 12"),
            ("empty", b"", "syntax 1 1"),
            ("byte limit", source + b"x" * (4097 - len(source)), f"source_limit 12 {4097 - len(source)}"),
            ("line limit", b"emit a\n" * 38, "source_limit 38 1"),
            ("token count", edit(lines[7], lines[7][:-1] + b" a\n"),
             f"source_limit 8 {len(lines[7]) + 1}"),
            ("token width", edit(b"let lo", b"let " + b"x" * 65), "source_limit 10 69"),
            ("node count", prefix + b"".join(declarations) + b"emit q\n", "syntax 24 1"),
        ]

        def reject(case, raw, status, frozen=None, **settings):
            expected = f"{status}\n{frozen or status}\n".encode()
            actual = run(raw, **settings)
            assert actual == expected, (case, actual, expected)

        for case, raw, status in rejections:
            reject(case, raw, status)
        for budget in (-1, 0, 2):
            reject(f"budget {budget}", source, "budget 11 1", budget=budget)
        reject("execution", source, "denied 11 1", mode="execution")
        # Freezing also enforces artifact-profile budgets and concrete input values.
        reject("freeze budget", source, "ok 0 0", "budget 0 0", budget=17)
        reject("freeze input", source, "ok 0 0", "invalid_input 0 0", first=-1)
    print(f"ottomat_scalar_ok=true successful=5 rejected={len(rejections) + 6}")


if __name__ == "__main__":
    main()
