#!/usr/bin/env python3
"""Exercise the build/launcher/suite path wiring without invoking a compiler."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def write(root, name, content, executable=False):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o700)


def main():
    scratch = os.environ.get("TMPDIR") or ROOT / "build/tmp"
    Path(scratch).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in (
        "MULIB_ROOT", "ON1XC", "FINPRED_STDPPX_DIR", "FINPRED_BUILD_DIR",
        "FINPRED_EXE", "FINPRED_DRAGNET_BUILD_DIR", "FINPRED_MODE", "MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES",
    ):
        env.pop(name, None)

    with tempfile.TemporaryDirectory(prefix="finpred-build-paths-", dir=scratch) as tmp:
        root = Path(tmp).resolve()
        shutil.copytree(ROOT / "bin", root / "bin", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "Makefile", root)
        write(root, "On1xfile", "")
        for source in (
            "source", "plugins/yieldcraft", "plugins/scalar_diagnostics", "plugins/poindexter/src",
            "strategies/yieldcraft",
        ):
            (root / source).mkdir(parents=True)
        write(root, "plugins/poindexter/On1xfile", "")
        write(root, "plugins/dragnet/On1xfile.m", "")
        write(root, "plugins/dragnet/dragnet_wire.on1x", "")
        write(root, "plugins/dragnet/guest_nights.on1x", "")
        write(root, "plugins/yieldcraft/cube_main.on1x", "")
        write(root, "source/cli/On1xfile.m", "")
        write(root, "source/main.on1x", "")
        write(root, "plugins/forecast_baselines/forecast_main.on1x", "")
        for file in ("date", "feed_snapshot", "format"):
            write(root, f"source/core/{file}.on1x", "")
        for file in ("price_prediction", "price_prediction_on1x"):
            write(root, f"source/core/{file}.c", "")
        write(root, "source/sdk/callable.on1x", "")
        write(root, "plugins/forecast_baselines/source/forecast_baselines/model.on1x", "")
        write(root, "third_party/mulib/on1x/tools/on1x-build.py", """
from pathlib import Path
import sys
args = sys.argv
assert '--cc' in args, 'FinPRED must explicitly select the host C toolchain'
source = Path(args[1])
assert source.is_file()
libraries = {args[n+1] for n, arg in enumerate(args) if arg == '--mulib'}
companions = [Path(args[n+1]) for n, arg in enumerate(args) if arg == '--extra-c']
exe = Path(args[args.index('-o') + 1])
if exe.name == 'finpred':
    assert source.name == 'main.on1x'
    assert libraries == {'histprice', 'price-forecast', 'price-ensemble'}
    assert {p.name for p in companions} == {'price_prediction.c', 'price_prediction_on1x.c'}
    assert all(p.is_file() for p in companions)
    body = 'printf "%s\\\\n" "$0"\\n'
else:
    assert exe.name == 'finpred-cube'
    assert source.name == 'cube_main.on1x'
    assert not libraries and not companions
    body = 'printf "%s\\\\n" "$0" "$FINPRED_MODE" "$FINPRED_CUBE_INPUT"\\n'
exe.parent.mkdir(parents=True, exist_ok=True)
exe.write_text('#!/bin/sh\\n' + body)
exe.chmod(0o700)
""")
        write(root, "third_party/mulib/on1x/tools/on1x-project.py", """
from pathlib import Path
import sys
assert '--cc' in sys.argv, 'FinPRED must explicitly select the host C toolchain'
out = Path(sys.argv[sys.argv.index('--output-dir') + 1])
out.mkdir(parents=True, exist_ok=True)
target = sys.argv[sys.argv.index('--target') + 1] if '--target' in sys.argv else 'finpred'
exe = out / target
exe.write_text('#!/bin/sh\\nprintf "%s\\\\n" "$0"\\n')
exe.chmod(0o700)
""")
        write(root, "target/dev/finpred", "#!/bin/sh\nexit 99\n", executable=True)
        write(root, "tests/run.sh", """#!/bin/sh
set -eu
test "$(./bin/finpred selftest)" = "$EXPECTED_EXE"
""", executable=True)
        for test in (
            "frozen_csv", "elvi", "public_feeds", "dispatch",
        ):
            write(root, f"tests/check_dragnet_{test}.py", "")
        write(root, "tests/check_crossref_replay.py", "")
        write(root, "tests/check_forecast_scores.py", 'print("forecast-score-stub-ran")\n')
        # If make test invokes this regression itself, don't recurse.
        write(root, "tests/check_build_paths.py", "")

        def run(*args, cwd=root, **overrides):
            return subprocess.run(
                args, cwd=cwd, env={**env, **overrides}, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, check=False,
            )

        stale = run("./bin/finpred", "selftest")
        assert stale.returncode == 2 and "FinPRED On1x executable absent" in stale.stdout, stale
        cube_missing = run("./bin/finpred", "cube", "replay", "fixture")
        assert cube_missing.returncode == 2 and "competitor cube host absent" in cube_missing.stdout
        missing = run("./bin/build.sh")
        assert missing.returncode == 2 and "Missing compiled On1x compiler" in missing.stdout, missing
        write(root, "build/mulib/on1x/on1xc", "#!/bin/sh\nexit 98\n", executable=True)
        missing_ppx = run("./bin/build.sh")
        assert missing_ppx.returncode != 0 and "Missing GrammarEmbed" in missing_ppx.stdout, missing_ppx
        write(root, "build/mulib/on1x/stdppx/category.schema.json", "{}")
        write(root, "build/mulib/on1x/stdppx/on1x-ppx-GrammarEmbed", "#!/bin/sh\nexit 97\n",
              executable=True)

        default = str(root / "build/dev/finpred")
        built = run("make")
        assert built.returncode == 0 and Path(default).is_file(), built.stdout
        tested = run("make", "test", EXPECTED_EXE=default)
        assert tested.returncode == 0, tested.stdout
        assert "forecast-score-stub-ran" in tested.stdout, tested.stdout

        custom = str(root / "build/custom CLI/finpred")
        tested = run("make", "test", FINPRED_BUILD_DIR="build/custom CLI", EXPECTED_EXE=custom,
                      FINPRED_EXE=str(root / "target/dev/finpred"))
        assert tested.returncode == 0, tested.stdout
        assert "forecast-score-stub-ran" in tested.stdout, tested.stdout
        outside = run(str(root / "bin/finpred"), "selftest", cwd=root / "tests",
                      FINPRED_BUILD_DIR="build/custom CLI")
        assert outside.returncode == 0 and outside.stdout.strip() == custom, outside
        forecast = run("./bin/finpred", "forecast", "replay", "fixture",
                       FINPRED_BUILD_DIR="build/custom CLI", FINPRED_EXE="target/dev/finpred")
        assert forecast.returncode == 0 and forecast.stdout.strip() == str(Path(custom).parent) + "-forecast/finpred-forecast", forecast
        for cube_args, mode, input_value in (
            (("replay", "fixture"), "cube-replay", "fixture"),
            (("evaluate", "snapshots", "cells", "policies"), "cube-evaluate", "snapshots"),
        ):
            cube = run("./bin/finpred", "cube", *cube_args,
                       FINPRED_BUILD_DIR="build/custom CLI", FINPRED_EXE="target/dev/finpred")
            assert cube.returncode == 0 and cube.stdout.splitlines() == [
                str(Path(custom).with_name("finpred-cube")), mode, input_value], cube
        dragnet_missing = run("./bin/finpred", "dragnet-inspect", "frame", "2026-11-24T00:00:00Z")
        assert dragnet_missing.returncode == 2 and "consumer absent" in dragnet_missing.stdout
        write(root, "build/custom Dragnet/finpred-dragnet",
              '#!/bin/sh\nprintf "%s\\n" "$0" "$FINPRED_DRAGNET_INPUT"\n', executable=True)
        dragnet = run(str(root / "bin/finpred"), "dragnet-inspect", "frame", "2026-11-24T00:00:00Z",
                      cwd=root / "tests", FINPRED_DRAGNET_BUILD_DIR="build/custom Dragnet",
                      FINPRED_EXE="target/dev/finpred")
        assert dragnet.returncode == 0 and dragnet.stdout.splitlines() == [
            str(root / "build/custom Dragnet/finpred-dragnet"), str(root / "tests/frame")], dragnet
        explicit = run("./bin/finpred", "selftest", FINPRED_EXE="target/dev/finpred")
        assert explicit.returncode == 99, explicit

        def git(cwd, *args):
            result = run("git", *args, cwd=cwd)
            assert result.returncode == 0, result.stdout
            return result.stdout.strip()

        def commit(cwd):
            git(cwd, "-c", "user.name=FinPRED test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgSign=false", "commit", "--allow-empty", "-qm", "Fixture")
            return git(cwd, "rev-parse", "HEAD")

        def pin(cwd, path, sha):
            git(cwd, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")
            return commit(cwd)

        write(root, "third_party/mulib/on1x/CMakeLists.txt", "")
        mulib = root / "third_party/mulib"
        libstone = mulib / "on1x/third_party/libstone"
        libstone.mkdir(parents=True)
        for repo in (root, mulib, libstone):
            git(repo, "init", "-q")
        commit(libstone)
        wrong = "1" * 40
        mulib_sha = pin(mulib, "on1x/third_party/libstone", wrong)
        pin(root, "third_party/mulib", wrong)
        outer = run("make", "mulib", "CMAKE=false")
        assert outer.returncode == 2 and f"Submodule pin mismatch at {mulib}:" in outer.stdout, outer
        pin(root, "third_party/mulib", mulib_sha)
        nested = run("make", "mulib", "CMAKE=false")
        assert nested.returncode == 2 and f"Submodule pin mismatch at {libstone}:" in nested.stdout, nested
    print("build_paths_ok=true default=1 custom=1 forecast_gate=2 cube_gate=3 dragnet_gate=2 "
          "stale_target_rejected=1 missing_toolchain=2 pin_mismatches=2")


if __name__ == "__main__":
    main()
