"""Limit a real manifest write; retry must not require offline stage removal."""
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def limit_writer():
    # Make fwrite/fclose report EFBIG rather than terminating the process.
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (128, 128))


def check(home):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("FINPRED_") or k == "FINPRED_EXE"}
    env["FINPRED_HOME"] = str(home)

    def run(*args, **kwargs):
        return subprocess.run([ROOT / "bin/finpred", *args], cwd=ROOT, env=env,
                              capture_output=True, timeout=60, **kwargs)

    summary = run("run", check=True).stdout
    run_id = re.search(rb"^run_id=([a-f0-9]{64})$", summary, re.M)[1].decode()
    manifest = home / "runs" / (run_id + ".txt")
    expected = manifest.read_bytes()
    manifest.unlink()
    failed = run("run", preexec_fn=limit_writer)
    if (failed.returncode <= 0 or b"staged write failed" not in failed.stderr
            or b"run_id=" in failed.stdout or list(manifest.parent.iterdir())):
        raise AssertionError(f"failed write left a final or staged file, or bad diagnostic: {failed}")
    if run("run", check=True).stdout != summary or manifest.read_bytes() != expected:
        raise AssertionError("retry failed to reproduce the original manifest")
    if run("replay", run_id, check=True).stdout != b"replay_ok=true\n" + summary:
        raise AssertionError("recovered run did not replay")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="finpred-short-write-") as tmp:
        check(Path(tmp) / "store")
    print("owned_stage_short_write_recovery_ok=true")
