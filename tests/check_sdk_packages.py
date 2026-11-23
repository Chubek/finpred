#!/usr/bin/env python3
"""Cross-check independent On1x and installed C11 hosts against real manifests."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tests/sdk_packages_consumer"
LIMITS = """csv_rows bytes_per_input rooms_per_property maximum_rooms adults children
            search_budget_max runs_per_call data_rows columns output_bytes_max""".split()


def cases(manifest):
    m = manifest
    contracts = m["contracts"]
    if m["kind"] == "Source":
        scenario, output = contracts
        assert output == m["output"]
        inputs = [scenario, m["input_format"]]
    elif m["kind"] == "View":
        inputs, output = contracts, m["output"]
    else:
        assert m["kind"] == "Strategy"
        inputs, output = contracts[:-1], contracts[-1]
    deps = m.get("dependencies", [])
    effect, = m["effects"]
    assert m["host_capabilities"] == []
    limits = m["resource_limits"]
    assert limits.keys() <= set(LIMITS)
    base = dict(PACKAGE=m["name"], SDK=str(m["sdk"]), VERSION=m["version"], KIND=m["kind"],
                INPUTS=",".join(inputs), OUTPUT=output, MODE=m["mode"], EFFECT=effect, REQUESTED="",
                DEPS=",".join(deps), GRANTS="", **{k: str(limits.get(k, 0)) for k in LIMITS})
    yield base, 0
    # Extra host inventory/grants do not change requirements or grant authority.
    yield base | dict(DEPS=",".join(["host.other@1", *reversed(deps)]), GRANTS="network"), 0
    for changes, expected in [
        (dict(PACKAGE="external.unregistered"), 3), (dict(SDK="2"), 2),
        (dict(VERSION="1.0.1"), 2), (dict(KIND="Action"), 2),
        (dict(INPUTS=",".join(reversed(inputs))), 2), (dict(INPUTS=",".join(inputs[:-1])), 2),
        (dict(INPUTS=base["INPUTS"] + ",extra@1"), 2), (dict(OUTPUT=output + "0"), 2),
        (dict(EFFECT="write"), 4), (dict(EFFECT=""), 4), (dict(MODE=""), 4),
        (dict(REQUESTED="network"), 4), (dict(REQUESTED="network", GRANTS="network"), 4),
        (dict(GRANTS="a,a"), 1), (dict(GRANTS="a,"), 1),
        (dict(GRANTS="a"*128), 1), (dict(DEPS=",".join(map(str, range(17)))), 1),
    ]:
        yield base | changes, expected
    for i in range(len(inputs)):
        changed = list(inputs)
        changed[i] = changed[i].split("@")[0] + "@2"
        yield base | dict(INPUTS=",".join(changed)), 2
    for mode in ("analysis", "simulation", "recommendation", "execution", "publish"):
        if mode != base["MODE"]:
            yield base | dict(MODE=mode), 4
    for i, dep in enumerate(deps):
        yield base | dict(DEPS=",".join(deps[:i] + deps[i+1:])), 2
        yield base | dict(DEPS=",".join(deps[:i] + [dep.split("@")[0] + "@2"] + deps[i+1:])), 2
    for key, value in limits.items():
        yield base | {key: str(value - 1)}, 2
        yield base | {key: str(value + 1)}, 0


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    count = 0
    with tempfile.TemporaryDirectory(prefix="finpred-sdk-packages-") as tmp:
        work = Path(tmp)
        build, install = work / "build", work / "installed"
        native, on1x = work / "consumer-c", work / "consumer-on1x"

        def run(args):
            subprocess.run(args, cwd=work, check=True)

        run(["cmake", "-S", ROOT / "source/sdk", "-B", build, "-DBUILD_SHARED_LIBS=ON",
             f"-DCMAKE_INSTALL_PREFIX={install}", "-DCMAKE_INSTALL_LIBDIR=lib"])
        run(["cmake", "--build", build])
        run(["cmake", "--install", build])
        run([*shlex.split(os.environ.get("CC", "cc")), "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-pedantic", "-UNDEBUG", f"-I{install}/include", SRC / "main.c",
             f"-L{install}/lib", f"-Wl,-rpath,{install}/lib", "-lfinpred_sdk", "-o", native])
        run([sys.executable, mulib / "on1x/tools/on1x-build.py", SRC / "main.on1x",
             "--backend", "c11", "--on1xc", compiler, "--mulib-root", mulib, "-I", ROOT / "source", "-o", on1x])
        for pkg in ("dragnet", "yieldcraft", "poindexter"):
            manifest = json.loads((ROOT / "plugins" / pkg / "plugin.json").read_bytes())
            for env, expected in cases(manifest):
                for exe in (native, on1x):
                    proc = subprocess.run([exe], env=os.environ | env, cwd=work, capture_output=True, timeout=5)
                    if proc.returncode != expected or proc.stdout or proc.stderr:
                        raise ValueError(f"{exe.name}: {env} expected {expected}, got {proc.returncode}: "
                                         f"{proc.stdout!r} {proc.stderr!r}")
                count += 1
    print(f"sdk_packages_ok=true packages=3 cases_per_host={count} hosts=c11,on1x")


if __name__ == "__main__":
    main()
