#!/usr/bin/env python3
"""Check v2-only Yieldcraft publication and read-only v1 archive verification."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from check_store import ENV, FIXTURES, ROOT, invoke, replay, tree


V1_FIXTURE_SHA256 = "e1619f8ae3e9728f856f4180f70035105d101770abceafc1b01ba7aed92e4191"


def publish(home, args, price, **inputs):
    summary = invoke(home, *args, **inputs)
    values = dict(line.split("=", 1) for line in summary.decode("ascii").splitlines())
    if (values["recommendation_minor"], values["published"]) != (price, "false"):
        raise ValueError(f"{home}: unexpected recommendation: {summary!r}")
    run_id = values["run_id"]
    if not re.fullmatch(r"[0-9a-f]{64}", run_id):
        raise ValueError(f"{home}: malformed run ID: {run_id!r}")
    manifest = home / "runs" / f"{run_id}.txt"
    if list(manifest.parent.iterdir()) != [manifest]:
        raise ValueError(f"{home}: expected exactly one committed run")
    if not re.fullmatch(rb"finpred-run@2(?:,[0-9a-f]{64}){6}\n", manifest.read_bytes()):
        raise ValueError(f"{manifest}: new run did not write a canonical v2 manifest")
    return summary


def check_publication(root):
    # These guesses are deliberately not supported options. Neither should
    # change the format (or any published bytes) of a new run.
    guesses = {"run_format": "finpred-run@1", "run_version": "1"}
    for name, args, price, inputs in (
        ("default", (), "17100", {}),
        ("premium", ("run",), "19000", {"strategy": ROOT / "strategies/premium-p75.ottomat"}),
    ):
        clean, guessed = root / name, root / f"{name}-guessed"
        summary = publish(clean, args, price, **inputs)
        if (publish(guessed, args, price, **inputs, **guesses) != summary
                or tree(clean, metadata=False) != tree(guessed, metadata=False)):
            raise ValueError(f"{name}: guessed version variables changed persisted output")


def check_archive(home):
    raw = (FIXTURES / "replay_v1.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != V1_FIXTURE_SHA256:
        raise ValueError("the frozen v1 fixture bytes changed")
    fixture = json.loads(raw)
    for name, text in fixture["files"].items():
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("ascii"))

    absent = {key: home.parent / "absent" for key in ("scenario", "offers", "valuation", "strategy")}
    before = tree(home)
    for run_id, text in fixture["runs"].items():
        summary = text.encode("ascii")
        replay(home, summary)
        trace_digest = re.search(r"^trace_digest=([0-9a-f]{64})$", text, re.M)[1]
        trace = (home / "artifacts" / f"blake3-{trace_digest}.txt").read_bytes()
        expected = b"replay_ok=true\n" + summary + b"trace_begin\n" + trace + b"trace_end\n"
        if invoke(home, "explain", run_id, **absent) != expected or tree(home) != before:
            raise ValueError(f"{run_id}: archived explanation or store changed")

    # Only the version field changes; all artifact references are still valid.
    run_id = next(iter(fixture["runs"]))
    manifest = home / "runs" / f"{run_id}.txt"
    manifest.write_bytes(manifest.read_bytes().replace(b"finpred-run@1,", b"finpred-run@9,", 1))
    before = tree(home)
    env = {**ENV, "FINPRED_HOME": str(home),
           **{f"FINPRED_{key.upper()}": str(path) for key, path in absent.items()}}
    for mode in ("replay", "explain"):
        proc = subprocess.run([ROOT / "bin/finpred", mode, run_id], cwd=ROOT, env=env,
                              capture_output=True, timeout=60)
        if proc.returncode <= 0 or proc.stdout or b"unknown run format" not in proc.stderr:
            raise ValueError(f"{mode}: did not reject the unknown run format: {proc}")
        if tree(home) != before:
            raise ValueError(f"{mode}: rejecting the unknown run format modified the store")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="finpred-yieldcraft-formats-") as tmp:
        root = Path(tmp)
        check_publication(root)
        check_archive(root / "archive")
    print("yieldcraft_formats_ok=true v2_writes=4 v1_archives=2 unknown_format_rejections=2")
