#!/usr/bin/env python3
"""Check private-store failure diagnostics and recovery on the compiled CLI (POSIX)."""
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile

from check_store import ENV, ROOT, tree


def invoke(home, *args, **kwargs):
    return subprocess.run([ROOT / "bin/finpred", *args], cwd=ROOT,
                          env={**ENV, "FINPRED_HOME": str(home)}, capture_output=True,
                          timeout=60, **kwargs)


def reject(home, mode, key, diagnostic, **kwargs):
    args = [mode] if mode == "run" else [mode, key]
    proc = invoke(home, *args, **kwargs)
    if proc.returncode <= 0 or proc.stdout or diagnostic.encode() not in proc.stderr:
        raise AssertionError(f"{mode} expected {diagnostic!r}: {proc}")


def unchanged_failure(home, *args):
    before = tree(home.parent)
    reject(home, *args)
    if before != tree(home.parent):
        raise AssertionError(f"{args}: failed operation mutated store")


def layouts(root):
    key = "0" * 64
    home = root / "layout"
    unchanged_failure(home, "replay", key, f"run: directory unavailable: home; key={key}")
    for role in ("home", "runs", "artifacts"):
        path = home if role == "home" else home / role
        path.parent.mkdir(exist_ok=True)
        path.write_text("existing file")
        unchanged_failure(home, "run", key, f"store: expected directory: {role}")
        if role in ("home", "runs"):
            unchanged_failure(home, "replay", key, f"store: expected directory: {role}")
        path.unlink()
    unchanged_failure(home, "replay", key, f"run: directory unavailable: runs; key={key}")
    (home / "runs").mkdir()
    unchanged_failure(home, "replay", key, f"run: unknown id; key={key}")


def entry_types(home, run_id, manifest, snapshot, artifact_id):
    artifacts = snapshot.parent
    saved = home / "saved"
    artifacts.rename(saved)
    unchanged_failure(home, "replay", run_id, "artifact: directory unavailable: artifacts")
    artifacts.write_text("existing file")
    unchanged_failure(home, "replay", run_id, "store: expected directory: artifacts")
    artifacts.unlink()
    saved.rename(artifacts)

    for path, key, kind, diagnostic in (
        (manifest, run_id, "run", "replay: malformed run manifest: destination is a directory"),
        (snapshot, artifact_id, "artifact", "artifact: snapshot is a directory"),
    ):
        path.rename(saved)
        path.mkdir()
        unchanged_failure(home, "replay", run_id, f"{diagnostic}; key={key}")
        unchanged_failure(home, "run", run_id, f"{kind}: immutable path conflict: destination is a directory; key={key}")
        path.rmdir()
        saved.rename(path)


def visible_commit(home, run_id, manifest, summary):
    # Stopped after rename but before removing the empty reservation.
    stage = manifest.with_suffix(".txt.pending")
    stage.mkdir()
    before = tree(home)
    if (invoke(home, "replay", run_id, check=True).stdout != b"replay_ok=true\n" + summary
            or invoke(home, "run", check=True).stdout != summary or tree(home) != before):
        raise AssertionError("completed manifest was not reused read-only alongside its reservation")
    stage.rmdir()


def short_write(limit_signal):
    def limit():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        signal.signal(signal.SIGXFSZ, limit_signal)
        resource.setrlimit(resource.RLIMIT_FSIZE, (128, 128))
    return limit


def failed_writes(home, summary, run_id, manifest, snapshot, artifact_id):
    # Start with no manifest. A handled error attempting the first object
    # should identify that key and release its stage, leaving other bytes intact.
    expected = tree(home, metadata=False)
    manifest.unlink()
    snapshot.unlink()
    before = tree(home, metadata=False)
    reject(home, "run", run_id, f"artifact: staged write failed; key={artifact_id}",
           preexec_fn=short_write(signal.SIG_IGN))
    if tree(home, metadata=False) != before:
        raise AssertionError("handled object failure changed the published set or left a stage")
    if invoke(home, "run", check=True).stdout != summary or tree(home, metadata=False) != expected:
        raise AssertionError("retry after object write failure changed bytes")

    # Terminate a real writer during a manifest write. Do not manufacture or
    # depend on the contents of a crashed writer's userspace or kernel buffers.
    manifest.unlink()
    killed = invoke(home, "run", preexec_fn=short_write(signal.SIG_DFL))
    stage = manifest.with_suffix(".txt.pending")
    if killed.returncode != -signal.SIGXFSZ or killed.stdout or manifest.exists() or not stage.is_dir():
        raise AssertionError(f"expected writer death during staged manifest write: {killed}")
    unchanged_failure(home, "replay", run_id, f"run: publication reservation present; no published entry observed; key={run_id}")
    unchanged_failure(home, "run", run_id, f"run: publication reservation unavailable; key={run_id}")
    # The writer was reaped. Exercise the documented offline recovery using
    # only the specific payload and directory; a regular retry regenerates it.
    (stage / "payload").unlink(missing_ok=True)
    stage.rmdir()
    if invoke(home, "run", check=True).stdout != summary or tree(home, metadata=False) != expected:
        raise AssertionError("recovery after writer death changed the committed byte set")
    before = tree(home)
    if invoke(home, "replay", run_id, check=True).stdout != b"replay_ok=true\n" + summary or tree(home) != before:
        raise AssertionError("recovered run did not replay read-only")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="finpred-store-status-") as tmp:
        root = Path(tmp)
        layouts(root)
        home = root / "store"
        summary = invoke(home, "run", check=True).stdout
        run_id = re.search(rb"^run_id=([0-9a-f]{64})$", summary, re.M)[1].decode()
        manifest = home / "runs" / f"{run_id}.txt"
        artifact_id = manifest.read_text().split(",")[1]
        snapshot = home / "artifacts" / f"blake3-{artifact_id}.txt"
        entry_types(home, run_id, manifest, snapshot, artifact_id)
        visible_commit(home, run_id, manifest, summary)
        failed_writes(home, summary, run_id, manifest, snapshot, artifact_id)
    print("store_publication_status_ok=true handled_artifact_failure=1 interrupted_manifest=1")
