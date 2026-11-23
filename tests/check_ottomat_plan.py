#!/usr/bin/env python3
"""Compile an independent consumer of the Ottomat frontend on the native graph."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    policies = {p.stem: p.read_text("ascii") for p in (ROOT / "strategies").glob("*.ottomat")}
    v1 = policies["yieldcraft"]
    v2 = policies["value-p40"]
    rows = v2.splitlines()
    invalid = {
        "", v2 + " " * (512 - len(v2)), v2 + " " * (513 - len(v2)),
        v2.replace("ottomat 2", "ottomat 1"), v1.replace("ottomat 1", "ottomat 2"),
        v2.replace("ottomat 2", "ottomat 02"), v2.replace("ottomat 2", "ottomat 3"),
        v2.replace("hospitality.", "hospitality.."), v2.replace("hospitality.", "hospitality/"),
        v2.replace("scenario@1", "scenario@01"), v2.replace("scenario@1", "scenario@2"),
        v2.replace("scenario@1", "offer@1"), v2.replace("gate pricing", "action pricing"),
        v2.replace("output pricing", "publish pricing"), v2 + "effect network\n",
        v2.replace("input ", "input  "), v2.replace("source ", "source\t"),
        v2.replace("pricing.", "přícing."), v2.replace("\n", "\r"), v2.rstrip("\n") + "\r",
        v2.replace("gate ", "\ngate "), v2 + "\n", v2.replace("\n", " \n"),
        v2.replace(rows[2], rows[1]), "\n".join(rows[:3] + [rows[4], rows[3]] + rows[5:]),
        v2.replace("value-p40@", "lead-linear@"), v2.replace("value-p40@1", "value-p40@2"),
        v2.replace("value-p40", "value-" + "p" * 33),
        v2.replace("target_bps 4000", "curve linear"), policies["lead-linear"].replace("curve linear", "curve quadratic"),
        v2.replace("4000", "04000"), v2.replace("4000", "+4000"), v2.replace("4000", "4000.0"),
        v2.replace("4000", "10001"), v2.replace("4000", "9" * 150), v2.replace("4000", "4000 publish"),
        v2.replace("profile ", "#profile "), v2.replace("profile ", "effect "),
    }
    for i in range(len(rows)):
        invalid.add("\n".join(rows[:i] + rows[i+1:]))

    with tempfile.TemporaryDirectory(prefix="finpred-ottomat-plan-") as tmp:
        exe = Path(tmp) / "plan"
        consumer = ROOT / "tests/ottomat_plan_consumer"

        def build(include):
            subprocess.run([
                sys.executable, sdk / "on1x/tools/on1x-build.py", consumer / "main.on1x",
                "--backend", "c11", "--on1xc", compiler, "--mulib-root", sdk, "-I", include, "-o", exe,
            ], check=True, cwd=tmp)

        def check(source, expected, graph_change=""):
            proc = subprocess.run([exe], cwd=tmp, env={**os.environ, "OTTOMAT_DECL": source,
                                  "OTTOMAT_GRAPH_CHANGE": graph_change},
                                  capture_output=True, timeout=10)
            if proc.returncode or proc.stdout != expected.encode("ascii"):
                raise ValueError(f"{source!r}: expected {expected!r}; got {proc}")

        build(ROOT / "source")
        for name, decl in policies.items():
            expected = "1:scenario" if name == "yieldcraft" else f"2:{name}"
            for text in (decl, decl.rstrip("\n"), decl.replace("\n", "\r\n"), decl.replace("\n", "\r\n", 1)):
                check(text, expected)
        for text in sorted(invalid):
            check(text, "invalid")

        # The same valid text must not gain an effect from trusted metadata
        # drifting under it. Build a test-only graph delegating to the native
        # API except for a single signature, effect, or admission decision.
        include = Path(tmp) / "include"
        shutil.copytree(ROOT / "source", include)
        (include / "reference").mkdir()
        (include / "automat/graph.on1x").rename(include / "reference/native.on1x")
        shutil.copy(consumer / "test_graph.on1x", include / "automat/graph.on1x")
        build(include)
        check(v1, "1:scenario")
        for change in ("root", "record", "network", "denied"):
            check(v1, "invalid", change)
    print(f"ottomat_plan_ok=true valid={4 * len(policies)} invalid={len(invalid)} incompatible_graphs=4")


if __name__ == "__main__":
    main()
