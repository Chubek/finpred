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
        "MULIB_ROOT", "ON1XC", "FINPRED_MULIB_BUILD_DIR", "FINPRED_STDPPX_DIR", "FINPRED_BUILD_DIR",
        "FINPRED_STAGE_PARENT",
        "FINPRED_EXE", "FINPRED_DRAGNET_BUILD_DIR", "FINPRED_MODE", "MAKEFLAGS",
        "MFLAGS", "MAKEOVERRIDES", "NATIVE_BUILD_DIR", "NATIVE_TEMPORAL_BUILD_DIR",
        "TUI_REVIEW_BUILD_DIR",
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
        for file in ("graph_main.on1x", "graph_check.on1x", "graph_input.c"):
            write(root, f"source/cli/{file}", "")
        write(root, "source/main.on1x", "")
        write(root, "plugins/forecast_baselines/forecast_main.on1x", "")
        for file in ("date", "feed_snapshot", "format"):
            write(root, f"source/core/{file}.on1x", "")
        for file in ("price_prediction", "price_prediction_on1x"):
            write(root, f"source/core/{file}.c", "")
        write(root, "source/sdk/callable.on1x", "")
        for module in ("evaluation", "holdout", "model", "score"):
            write(root, f"plugins/forecast_baselines/source/forecast_baselines/{module}.on1x", "")
        # Keep even synthetic dependencies outside third_party.
        mulib = root / "fixture-mulib"
        env["MULIB_ROOT"] = str(mulib)
        write(mulib, "on1x/tools/on1x-build.py", """
from hashlib import sha256
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
    assert not Path('source/cli/graph_identity.on1x').exists()
    assert libraries == {'histprice', 'price-forecast', 'price-ensemble'}
    assert {p.name for p in companions} == {'price_prediction.c', 'price_prediction_on1x.c'}
    assert all(p.is_file() for p in companions)
    body = 'printf "%s\\\\n" "$0"\\n'
elif exe.name == 'finpred-cube':
    assert source.name == 'cube_main.on1x'
    assert not libraries and not companions
    body = 'printf "%s\\\\n" "$0" "$FINPRED_MODE" "$FINPRED_CUBE_INPUT"\\n'
else:
    assert exe.name == 'finpred-graph'
    assert source == Path('source/cli/graph_main.on1x')
    assert args[args.index('--backend') + 1] == 'c11'
    assert args[args.index('--on1xc') + 1] == str(Path.cwd() / 'on1xc')
    assert not libraries and companions == [Path('source/cli/graph_input.c')]
    assert companions[0].is_file()
    assert Path('source/cli/On1xfile.m').read_text().endswith(
        'library "graph_check.on1x"\\nlibrary "graph_identity.on1x"\\n'
    )
    host_compiler = b'#!/bin/sh\\nexit 98\\n'
    fingerprint = sha256(host_compiler).hexdigest()
    assert Path('source/cli/graph_identity.on1x').read_text() == (
        f'fn compiler_id() -> string {{ return "sha256:{fingerprint}"; }}\\n'
    )
    body = 'printf "%s\\\\n" "$0" "$FINPRED_MODE" "$FINPRED_GRAPH_SOURCE"\\n'
exe.parent.mkdir(parents=True, exist_ok=True)
exe.write_text('#!/bin/sh\\n' + body)
exe.chmod(0o700)
""")
        write(mulib, "on1x/tools/on1x-project.py", """
from pathlib import Path
import sys
assert '--cc' in sys.argv, 'FinPRED must explicitly select the host C toolchain'
assert not (Path(sys.argv[2]) / 'source/cli/graph_identity.on1x').exists()
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
printf 'suite=%s\\n' "${1:-all}"
""", executable=True)

        def run(*args, cwd=root, **overrides):
            return subprocess.run(
                args, cwd=cwd, env={**env, **overrides}, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, check=False,
            )

        stale = run("./bin/finpred", "selftest")
        assert stale.returncode == 2 and "FinPRED On1x executable absent" in stale.stdout, stale
        cube_missing = run("./bin/finpred", "cube", "replay", "fixture")
        assert cube_missing.returncode == 2 and "competitor cube host absent" in cube_missing.stdout
        graph_missing = run("./bin/finpred", "graph", "validate", "fixture")
        assert graph_missing.returncode == 2 and "graph inspection host absent" in graph_missing.stdout
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
        default_graph = run("./bin/finpred", "graph", "validate", "fixture")
        assert default_graph.returncode == 0 and default_graph.stdout.splitlines() == [
            str(Path(default).with_name("finpred-graph")), "graph-validate", str(root / "fixture"),
        ], default_graph
        tested = run("make", "test", "CMAKE=true", "CTEST=true", EXPECTED_EXE=default)
        assert tested.returncode == 0, tested.stdout
        assert tested.stdout.splitlines().count("suite=all") == 1, tested.stdout
        assert "--test-dir \"build/native\"" in tested.stdout, tested.stdout
        assert "--test-dir \"build/native-temporal\"" in tested.stdout, tested.stdout
        assert "--test-dir \"build/poindexter-tui-review\"" in tested.stdout, tested.stdout

        custom = str(root / "build/custom CLI/finpred")
        tested = run("make", "test", "CMAKE=true", "CTEST=true",
                      FINPRED_BUILD_DIR="build/custom CLI", EXPECTED_EXE=custom,
                      FINPRED_EXE=str(root / "target/dev/finpred"))
        assert tested.returncode == 0, tested.stdout
        assert tested.stdout.splitlines().count("suite=all") == 1, tested.stdout
        for target, suite in (
            ("test-compiler", "compiler"), ("test-pricing", "pricing"),
            ("test-forecasting", "forecasting"), ("test-plugins", "plugins"),
            ("test-storage", "storage"), ("test-security", "security"),
            ("dragnet-test", "dragnet-legacy"), ("dragnet-search-test", "dragnet-search"),
            ("forecast-score-test", "forecast-score"),
        ):
            selected = run("make", target, "CMAKE=true", "CTEST=true",
                           FINPRED_BUILD_DIR="build/custom CLI", EXPECTED_EXE=custom)
            assert selected.returncode == 0, selected.stdout
            assert [line for line in selected.stdout.splitlines() if line.startswith("suite=")] == [
                f"suite={suite}"], selected.stdout
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
        for action, source in (("validate", str(root / "absolute")), ("inspect", "relative strategy")):
            graph = run(str(root / "bin/finpred"), "graph", action, source, cwd=root / "tests",
                        FINPRED_BUILD_DIR="build/custom CLI", FINPRED_EXE="target/dev/finpred")
            assert graph.returncode == 0 and graph.stdout.splitlines() == [
                str(Path(custom).with_name("finpred-graph")), "graph-" + action,
                str(root / "tests" / source),
            ], graph
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

        # Model the two Git pin mismatches without creating checkouts (or
        # writing gitlinks, symlinks, or any files under third_party).
        write(mulib, "on1x/CMakeLists.txt", "")
        write(root, "fake-bin/git", """#!/bin/sh
set -eu
test "$1" = -C
case "$2:$3:$4" in
  "$FAKE_PARENT:ls-tree:HEAD")
    test "$5:$6" = "--:$FAKE_GITLINK"
    printf '160000 commit 1111111111111111111111111111111111111111\\t%s\\n' "$6" ;;
  "$FAKE_CHECKOUT:rev-parse:--show-toplevel") printf '%s\\n' "$2" ;;
  "$FAKE_CHECKOUT:rev-parse:HEAD") printf '%s\\n' 2222222222222222222222222222222222222222 ;;
  *) exit 99 ;;
esac
""", executable=True)
        fake_path = str(root / "fake-bin") + os.pathsep + env.get("PATH", os.defpath)
        default_mulib = root / "third_party/mulib"
        outer = run("make", "mulib", "CMAKE=false", MULIB_ROOT="", PATH=fake_path,
                    FAKE_PARENT=str(root), FAKE_CHECKOUT=str(default_mulib), FAKE_GITLINK="third_party/mulib")
        assert outer.returncode == 2 and f"Submodule pin mismatch at {default_mulib}:" in outer.stdout, outer
        libstone = mulib / "on1x/third_party/libstone"
        nested = run("make", "mulib", "CMAKE=false", PATH=fake_path,
                     FAKE_PARENT=str(mulib), FAKE_CHECKOUT=str(libstone), FAKE_GITLINK="on1x/third_party/libstone")
        assert nested.returncode == 2 and f"Submodule pin mismatch at {libstone}:" in nested.stdout, nested
        assert not (root / "third_party").exists() and not libstone.parent.exists()
    print("build_paths_ok=true default=1 custom=1 verification_selectors=9 forecast_gate=2 cube_gate=3 "
          "graph_gate=4 dragnet_gate=2 stale_target_rejected=1 missing_toolchain=2 pin_mismatches=2")


if __name__ == "__main__":
    main()
