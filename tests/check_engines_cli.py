#!/usr/bin/env python3
"""Exercise both engine routes through the launcher and the compiled host."""
import os
from pathlib import Path
import subprocess
import tempfile

from check_store import tree

ROOT = Path(__file__).resolve().parents[1]
MAIN_ID = b"28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"
# Independently computed for the same 17/42 spread as the native replay fixture.
SPREAD_DIGEST = b"f3f59aede2d460f6e4c25363919556d703726661ec3d0acf6be7a3af42767967"


def main():
    exe = Path(os.environ.get("FINPRED_EXE", ROOT / "target/dev/finpred")).resolve()
    launcher = ROOT / "bin/finpred"
    clean = {key: value for key, value in os.environ.items() if not key.startswith("FINPRED_")}

    with tempfile.TemporaryDirectory(prefix="finpred-engines-") as tmp:
        work = Path(tmp)
        legacy = work / "legacy"
        scalar = work / "scalar"
        absent = work / "absent"

        def run(*args, command=launcher, env=None, error=None):
            p = subprocess.run([command, *args], cwd=ROOT, capture_output=True, timeout=15,
                               env=clean | {"FINPRED_EXE": str(exe), "FINPRED_HOME": str(legacy)} | (env or {}))
            if error is None:
                assert p.returncode == 0 and not p.stderr, p
            else:
                assert p.returncode > 0 and not p.stdout and error in p.stderr, p
            return p.stdout

        default = run()
        assert b"run_id=" + MAIN_ID + b"\n" in default
        before = tree(legacy)
        assert run("run", "--engine", "legacy", env={"FINPRED_ENGINE": "scalar"}) == default
        assert run("replay", MAIN_ID.decode(), env={"FINPRED_ENGINE": "scalar"}) == b"replay_ok=true\n" + default

        analysis = {"FINPRED_HOME": str(scalar), **{f"FINPRED_{name}": str(absent)
                                                    for name in ("SCENARIO", "OFFERS", "VALUATION")}}
        spread = run("run", "--engine", "scalar", env=analysis)
        assert spread.startswith(b"engine=scalar\nmode=analysis\ngraph=automat.scalar-dag@1\n"
                                 b"output_kind=scalar.distance@1\nvalue=25\noutput_digest=" + SPREAD_DIGEST + b"\n")
        assert spread.endswith(b"published=false\ntrace_begin\nhi=maximum@1(first,second):42\n"
                               b"lo=minimum@1(first,second):17\nspread=distance@1(hi,lo):25\ntrace_end\n")
        selected = analysis | {"FINPRED_ENGINE": "scalar"}
        assert run("run", env=selected) == run(command=exe, env=selected) == spread
        assert run("run", env=selected | {"FINPRED_HOME": str(legacy)}) == spread
        assert tree(legacy) == before

        for strategy, version, value, trace in (
            ("scalar-select", "2", "42", b"picked=select@1(spread,hi,lo):42\n"),
            ("scalar-midpoint", "3", "29", b"midpoint=midpoint@1(hi,lo):29\n"),
        ):
            output = run("run", env=selected | {"FINPRED_STRATEGY": f"strategies/{strategy}.ottomat"})
            assert f"graph=automat.scalar-dag@{version}\noutput_kind=scalar.level@1\nvalue={value}\n".encode() in output
            assert trace in output, output
        extreme = run("run", env=selected | {"FINPRED_SCALAR_FIRST": "0", "FINPRED_SCALAR_SECOND": "1000000000000",
                                              "FINPRED_SCALAR_BUDGET": "3"})
        assert b"value=1000000000000\n" in extreme

        run("run", "--engine", "other", env=analysis | {"FINPRED_STRATEGY": str(absent)}, error=b"unknown engine")
        run("run", "--engine", error=b"usage:")
        run("replay", MAIN_ID.decode(), "--engine", "scalar", error=b"usage:")
        run(command=exe, env=selected | {"FINPRED_ENGINE": "other"}, error=b"unknown engine")
        run("run", env=selected | {"FINPRED_MODE": "execution"}, error=b"capability denied")
        run(command=exe, env=selected | {"FINPRED_MODE": "execution"}, error=b"capability denied")
        run("run", env=selected | {"FINPRED_STRATEGY": "strategies/yieldcraft.ottomat"}, error=b"syntax at 1:1")
        run("run", "--engine", "legacy", env={"FINPRED_HOME": str(scalar),
                                              "FINPRED_STRATEGY": "strategies/scalar-spread.ottomat"},
            error=b"invalid graph or incompatible strategy")
        forbidden = work / "forbidden.ottomat"
        forbidden.write_bytes((ROOT / "strategies/scalar-spread.ottomat").read_bytes().replace(
            b"effect pure", b"effect action"))
        run("run", env=selected | {"FINPRED_STRATEGY": str(forbidden)}, error=b"denied at 4:1")
        run("run", env=selected | {"FINPRED_SCALAR_BUDGET": "2"}, error=b"budget at ")
        run("run", env=selected | {"FINPRED_SCALAR_BUDGET": "17"}, error=b"FINPRED_SCALAR_BUDGET")
        for invalid in ("-1", "01", "1 ", "1000000000001", "99999999999999999999"):
            run("run", env=selected | {"FINPRED_SCALAR_FIRST": invalid}, error=b"FINPRED_SCALAR_FIRST")
        assert not scalar.exists(), scalar

    print("engines_cli_ok=true scalar_dialects=3 rejected=16")


if __name__ == "__main__":
    main()
