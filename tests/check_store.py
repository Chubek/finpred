#!/usr/bin/env python3
"""Black-box checks on the compiled CLI and disposable local stores."""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from check_explain_cli import check as check_explain


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
ENV = {k: v for k, v in os.environ.items()
       if not k.startswith("FINPRED_") or k == "FINPRED_EXE"}


def invoke(home, *args, success=True, permit_contention=False, **inputs):
    proc = subprocess.run(
        [ROOT / "bin/finpred", *args], cwd=ROOT,
        env={**ENV, "FINPRED_HOME": str(home),
             **{f"FINPRED_{k.upper()}": str(v) for k, v in inputs.items()}},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    if (permit_contention and proc.returncode > 0
            and b"publication reservation unavailable" in proc.stdout + proc.stderr
            and b"recommendation_minor=" not in proc.stdout):
        return None
    if (proc.returncode == 0) != success:
        raise RuntimeError(f"{home} {args}: exit {proc.returncode}: {proc.stdout!r} {proc.stderr!r}")
    if not success and (proc.returncode < 0 or b"recommendation_minor=" in proc.stdout
                        or b"replay_ok=true" in proc.stdout):
        raise RuntimeError(f"{home} {args}: unexpected failure result {proc}")
    return proc.stdout


def tree(root, metadata=True):
    """Ignore atime; detect a same-byte write or replacement on read-only paths."""
    result = {}
    for path in [root, *root.rglob("*")]:
        st = path.lstat()
        data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        result[path.relative_to(root)] = ((st.st_ino, st.st_mode, st.st_ctime_ns,
                                           st.st_mtime_ns, data) if metadata else data)
    return result


def replay(home, summary):
    run_id = re.search(rb"^run_id=([a-f0-9]{64})$", summary, re.M)[1].decode("ascii")
    absent = {k: home.parent / "absent" for k in ("scenario", "offers", "valuation", "strategy")}
    before = tree(home)
    output = invoke(home, "replay", run_id, **absent)
    if output != b"replay_ok=true\n" + summary or tree(home) != before:
        raise ValueError(f"{run_id}: replay summary or store changed")


def legacy(home):
    fixture = json.loads((FIXTURES / "replay_v1.json").read_bytes())
    for name, text in fixture["files"].items():
        if not re.fullmatch(r"(artifacts/blake3-|runs/)[0-9a-f]{64}\.txt", name):
            raise ValueError(f"invalid v1 fixture path: {name}")
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("ascii"))
    if len(fixture["runs"]) != 2:
        raise ValueError("both v1 fixture summaries required")
    for run_id, text in fixture["runs"].items():
        if f"run_id={run_id}" not in text.splitlines():
            raise ValueError(f"invalid v1 summary for {run_id}")
        replay(home, text.encode("ascii"))
    check_explain(home, next(iter(fixture["runs"])))
    print("v1_replay_ok=true runs=2")


def simultaneous(home, reference, summaries):
    # Exercise create-on-first-use as well as multiple writers of common objects.
    # Clock scheduling is uncontrolled; this checks the observable final state.
    cases = ["", "_multiroom"] * 4
    ready = threading.Barrier(len(cases))

    def publish(case):
        ready.wait(timeout=30)
        return invoke(home, "run", permit_contention=True, scenario=FIXTURES / f"scenario{case}.csv",
                      offers=FIXTURES / f"offers{case}.csv")

    completed = []
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        for case, output in zip(cases, pool.map(publish, cases)):
            if output is None:
                continue
            if output != summaries[case]:
                raise ValueError(f"concurrent run differs from serial result: {case}")
            completed.append(output)
    if not completed:
        raise ValueError("all concurrent runs failed")
    serial_tree = tree(reference, metadata=False)
    for path, data in tree(home, metadata=False).items():
        if path not in serial_tree or serial_tree[path] != data:
            raise ValueError(f"unexpected or incomplete object after concurrent runs: {path}")
    for summary in set(completed):
        replay(home, summary)
    for case, summary in summaries.items():
        if invoke(home, "run", scenario=FIXTURES / f"scenario{case}.csv",
                  offers=FIXTURES / f"offers{case}.csv") != summary:
            raise ValueError("serial retry after concurrent runs disagrees with reference")
    if tree(home, metadata=False) != serial_tree:
        raise ValueError("store after concurrent runs differs from serial store")
    for summary in summaries.values():
        replay(home, summary)
    print(f"concurrent_store_ok=true writers={len(cases)} succeeded={len(completed)}")


def interrupted_set(home, reference, summary):
    # A partial publication has a conflicting output object, but no committed run.
    # Retry fails closed; explicit removal of bad data permits clean recovery.
    digest = re.search(rb"^recommendation_digest=([a-f0-9]{64})$", summary, re.M)[1].decode("ascii")
    name = Path("artifacts") / f"blake3-{digest}.txt"
    path = home / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"incomplete fixture\n")
    invoke(home, "run", success=False)
    if list((home / "runs").glob("*.txt")) or path.read_bytes() != b"incomplete fixture\n":
        raise ValueError("failed publication committed a run or rewrote the conflicting object")
    path.unlink()
    if invoke(home, "run") != summary or path.read_bytes() != (reference / name).read_bytes():
        raise ValueError("retry did not recover the fixture after removal of the conflict")
    replay(home, summary)
    print("failed_publication_recovery_ok=true")


def reservation_boundaries(root, reference, summary):
    run_id = re.search(rb"^run_id=([a-f0-9]{64})$", summary, re.M)[1].decode("ascii")
    root.mkdir()
    for case in ("abandoned", "symlink"):
        home = root / case
        shutil.copytree(reference, home)
        manifest = home / "runs" / f"{run_id}.txt"
        manifest.unlink()
        stage = manifest.with_suffix(".txt.pending")
        target = stage if case == "abandoned" else root / "outside"
        target.mkdir()
        (target / "payload").write_bytes(b"other publisher's staged bytes\n")
        if case == "symlink":
            stage.symlink_to(target, target_is_directory=True)
        before = tree(target)
        invoke(home, "run", success=False)
        if manifest.exists() or tree(target) != before:
            raise ValueError(f"{case} reservation reused or modified")
        invoke(home, "replay", run_id, success=False)
        if case == "symlink":
            stage.unlink()
        else:
            shutil.rmtree(stage)
        if invoke(home, "run") != summary:
            raise ValueError(f"manual reservation removal did not allow clean recovery: {case}")
    print("publication_reservation_boundaries_ok=true cases=2")


def directory_boundaries(root):
    for number, entry in enumerate((".", "artifacts", "runs")):
        home = root / str(number)
        blocker = home / entry
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_bytes(b"not a store directory\n")
        before = tree(blocker)
        invoke(home, "run", success=False)
        if tree(blocker) != before or list(home.glob("*/*.txt")):
            raise ValueError(f"regular file in place of store directory: {entry}")
    print("store_directory_boundaries_ok=true cases=3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="store from both serial fixture runs")
    parser.add_argument("main_summary", type=Path)
    parser.add_argument("multi_summary", type=Path)
    args = parser.parse_args()
    summaries = {"": args.main_summary.read_bytes(), "_multiroom": args.multi_summary.read_bytes()}
    with tempfile.TemporaryDirectory(prefix="finpred-store-") as tmp:
        root = Path(tmp)
        legacy(root / "legacy")
        simultaneous(root / "concurrent", args.reference, summaries)
        interrupted_set(root / "recover", args.reference, summaries[""])
        reservation_boundaries(root / "boundaries", args.reference, summaries[""])
        directory_boundaries(root / "directory-types")
