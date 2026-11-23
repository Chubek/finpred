#!/usr/bin/env python3
"""Compile real hosts with policy entries disabled but their implementations linked."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ottomat_build import flags

ROOT = Path(__file__).resolve().parents[1]
MAIN_ID = "28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"


def execute(args, work, *, env=None, failure=None):
    p = subprocess.run(args, cwd=work, env=os.environ | (env or {}),
                       capture_output=True, timeout=30)
    if failure is None:
        assert p.returncode == 0 and not p.stderr, p
    else:
        assert p.returncode > 0 and not p.stdout and failure in p.stderr, p
    return p.stdout


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    env = {"MULIB_ROOT": str(sdk), "ON1XC": str(compiler)}
    with tempfile.TemporaryDirectory(prefix="finpred-plugin-registry-") as tmp:
        work = Path(tmp)
        project = work / "project"
        app, dragnet = work / "app", work / "dragnet"
        consumer = work / "consumer"
        project.mkdir()
        for directory in ("source", "bin"):
            shutil.copytree(ROOT / directory, project / directory)
        shutil.copy(ROOT / "On1xfile", project)
        for package in ("yieldcraft", "scalar_diagnostics", "dragnet", "forecast_baselines"):
            shutil.copytree(ROOT / "plugins" / package, project / "plugins" / package)
        sheet = project / "plugins/poindexter"
        shutil.copytree(ROOT / "plugins/poindexter/src", sheet / "src")
        shutil.copy(ROOT / "plugins/poindexter/On1xfile", sheet)
        shutil.copy(ROOT / "strategies/scalar-midpoint.ottomat", project / "midpoint.ottomat")

        # A disk manifest claiming a known handler is not registration.
        impostor = project / "plugins/external"
        impostor.mkdir()
        (impostor / "plugin.json").write_text(
            '{"name":"scalar-diagnostics@1","handler":"midpoint@1","enabled":true}\n')

        def compile_consumer():
            subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                            ROOT / "tests/plugin_registry_consumer/main.on1x", "--backend", "c11",
                            "--on1xc", compiler, "--mulib-root", sdk, "-I", project / "source",
                            *flags(compiler, sdk, work), "-I", project, "-o", consumer], check=True, cwd=work)

        def build_app():
            subprocess.run([project / "bin/build.sh"], cwd=project,
                           env=os.environ | env | {"FINPRED_BUILD_DIR": str(app)}, check=True)

        def run_consumer(case, **expected):
            return execute([consumer], project, env=cli_env | {"REGISTRY_CASE": case}, **expected)

        def run_dragnet(failure):
            scenario, offers = (ROOT / "fixtures" / f"{name}.csv" for name in ("scenario", "offers"))
            return execute(["sh", "-c", 'exec "$1" 3<"$2" 4<"$3"',
                            "dragnet", dragnet / "dragnet-frozen-csv", scenario, offers],
                           work, failure=failure)

        store = work / "store"
        cli_env = {"FINPRED_HOME": str(store), "FINPRED_RUN_ID": MAIN_ID, "FINPRED_ENGINE": "legacy",
                   "FINPRED_STRATEGY": str(ROOT / "strategies/yieldcraft.ottomat"),
                   **{f"FINPRED_{key.upper()}": str(ROOT / f"fixtures/{key}.csv")
                      for key in ("scenario", "offers", "valuation")}}

        def run_cli(mode, **expected):
            return execute([app / "finpred"], project,
                           env=cli_env | {"FINPRED_MODE": mode}, **expected)

        compile_consumer()
        assert run_consumer("lookup") == b""
        assert run_consumer("plan") == b"ok\n1\nok\n"
        assert run_consumer("invoke") == b"29\n"
        build_app()
        expected_run = run_cli("run")
        assert f"run_id={MAIN_ID}\n".encode() in expected_run
        assert b"recommendation_minor=17100\n" in expected_run
        assert b"17100,-400," in run_cli("poindexter")

        registry = project / "source/sdk/registry.on1x"
        original = registry.read_text()

        def disable(*entries):
            text = original
            for entry in entries:
                old = f'== {entry} {{ return binding(true,'
                assert text.count(old) == 1, entry
                text = text.replace(old, old.replace("true,", "false,"))
            registry.write_text(text)

        disable('"poindexter.sheet.render"', '"dragnet.frozen_csv.offers_as_of"',
                '"plugins.scalar_diagnostics.midpoint.midpoint"')
        compile_consumer()
        assert run_consumer("plan") == b"unknown_handler\n0\nunknown_handler\n"
        run_consumer("invoke", failure=b"dag: invocation denied")
        assert run_consumer("direct") == b"29\n"
        build_app()
        assert run_cli("replay") == b"replay_ok=true\n" + expected_run
        run_cli("poindexter", failure=b"sdk: incompatible pricing sheet")
        cli_env["FINPRED_HOME"] = str(work / "absent-store")
        run_cli("poindexter", failure=b"sdk: incompatible pricing sheet")
        assert not Path(cli_env["FINPRED_HOME"]).exists()
        cli_env["FINPRED_HOME"] = str(store)
        subprocess.run([project / "plugins/dragnet/build.sh", dragnet], cwd=project,
                       env=os.environ | env, check=True)
        run_dragnet(b"sdk: incompatible frozen CSV source")

        disable("yieldcraft_entry()")
        compile_consumer()
        assert run_consumer("direct_yieldcraft") == b"17100\n"
        build_app()
        run_cli("replay", failure=b"sdk: capability denied")
        blocked_store = work / "denied-store"
        cli_env["FINPRED_HOME"] = str(blocked_store)
        run_cli("run", failure=b"sdk: capability denied")
        # Removing the pricing package's binding must not disable scalar analysis.
        assert b"value=29\n" in execute([app / "finpred"], project, env=cli_env | {
            "FINPRED_MODE": "run", "FINPRED_ENGINE": "scalar",
            "FINPRED_STRATEGY": str(project / "midpoint.ottomat"),
        })
        assert not blocked_store.exists()
        subprocess.run([project / "plugins/dragnet/build.sh", dragnet], cwd=project,
                       env=os.environ | env, check=True)
        run_dragnet(b"sdk: incompatible frozen CSV source")

    print("plugin_registry_ok=true disabled_bindings=4 denied_dependency=1 direct_libraries=2")


if __name__ == "__main__":
    main()
