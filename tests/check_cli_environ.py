#!/usr/bin/env python3
"""Check the compiled host environment boundary: python3 tests/check_cli_environ.py PATH_TO_FINPRED."""
import argparse
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ID = b"28b145fb8f902a239e76502a40c138bd60c7ae6af98ca70e21faf0e0f06e85db"
MULTIROOM_ID = b"7b1f694eab8645b0a09ed431a1268619328da4833a417a22cacf66c68df4612b"


def snapshot(home):
    state = {}
    for path in sorted(home.rglob("*")):
        meta = path.stat()
        state[path.relative_to(home)] = (
            meta.st_ino, meta.st_mode, meta.st_mtime_ns, meta.st_ctime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    exe = parser.parse_args().executable.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="finpred-cli-environ-") as tmp:
        work = Path(tmp)
        for name in ("fixtures", "strategies"):
            (work / name).symlink_to(ROOT / name, target_is_directory=True)

        def run(*, error=None, **env):
            # Invoke the actual host, not the shell launcher which sets the mode.
            # Pass only the synthetic configuration under test.
            p = subprocess.run([exe], cwd=work, env=env, capture_output=True, timeout=30)
            if error is None:
                assert p.returncode == 0 and not p.stderr, p
            else:
                assert p.returncode == 73 and not p.stdout and error in p.stderr, p
            return p.stdout

        default = run()
        assert {b"run_id=" + DEFAULT_ID, b"recommendation_minor=17100",
                b"published=false"} <= set(default.splitlines()), default
        fallback_home = work / ".finpred"
        assert (fallback_home / "runs" / (DEFAULT_ID.decode() + ".txt")).is_file()
        before = snapshot(fallback_home)
        assert run(FINPRED_MODE="", FINPRED_HOME="", FINPRED_ENGINE="",
                   FINPRED_SCENARIO="", FINPRED_OFFERS="", FINPRED_VALUATION="",
                   FINPRED_STRATEGY="") == default
        assert snapshot(fallback_home) == before

        home = work / "custom home"
        multiroom = run(FINPRED_HOME=str(home),
                        FINPRED_SCENARIO="fixtures/scenario_multiroom.csv",
                        FINPRED_OFFERS="fixtures/offers_multiroom.csv")
        assert {b"run_id=" + MULTIROOM_ID, b"recommendation_minor=16000",
                b"published=false"} <= set(multiroom.splitlines()), multiroom
        assert (home / "runs" / (MULTIROOM_ID.decode() + ".txt")).is_file()
        saved = snapshot(home)
        missing_path = str(work / "absent")
        assert run(FINPRED_MODE="replay", FINPRED_HOME=str(home),
                   FINPRED_RUN_ID=MULTIROOM_ID.decode(), FINPRED_ENGINE="unknown",
                   FINPRED_SCENARIO=missing_path, FINPRED_OFFERS=missing_path,
                   FINPRED_VALUATION=missing_path, FINPRED_STRATEGY=missing_path
                   ) == b"replay_ok=true\n" + multiroom

        for selection in ({}, {"FINPRED_RUN_ID": ""}, {"FINPRED_RUN_ID": "short"}):
            run(FINPRED_MODE="replay", FINPRED_HOME=str(home), **selection,
                error=b"replay: FINPRED_RUN_ID must be a digest")
        for mode in ("execution", "unknown"):
            run(FINPRED_MODE=mode, FINPRED_HOME=missing_path, FINPRED_SCENARIO=missing_path,
                error=b"capability denied")
        run(FINPRED_ENGINE="unknown", FINPRED_HOME=missing_path, FINPRED_SCENARIO=missing_path,
            error=b"unknown engine")
        assert not Path(missing_path).exists()
        assert snapshot(home) == saved
        assert snapshot(fallback_home) == before

    print("cli_environ_ok=true positive=4 rejected=6")


if __name__ == "__main__":
    main()
