#!/usr/bin/env python3
"""Property CLI, synthetic pricing and real offline Kron replay."""

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/joe-litty-rooms"
SAMPLE = ROOT / "plugins/caravansary/examples/joe-litty-rooms/prediction.json"


def invoke(*args, status=0):
    result = subprocess.run([CLI, *args], cwd=ROOT, capture_output=True, timeout=15)
    if status is None:
        assert result.returncode != 0 and not result.stdout, (args, result)
    else:
        assert result.returncode == status, (args, result.stderr)
    return result.stdout


def predict(*args, **kwargs):
    return json.loads(invoke("predict", *args, **kwargs))


def main():
    assert invoke("-h") == invoke("--help")
    for option in (b"--algorithm", b"--poll-seconds", b"--every", b"--as-of", b"abstention"):
        assert option in invoke("--help"), option
    assert invoke("algorithms").splitlines() == [b"median", b"lower-quartile", b"percentile"]
    abstained = predict(SAMPLE)["position"]
    assert abstained["reason"] == "insufficient_distinct_comparables"
    assert "recommended_minor" not in abstained
    invoke("predict", SAMPLE, "--algorithm", "anything-else", status=None)
    invoke("predict", SAMPLE, "--as-of", "not-a-time", status=None)

    with TemporaryDirectory() as work:
        root = Path(work).resolve()
        state = root / "state"
        evidence = root / "fictional.json"
        data = json.loads(SAMPLE.read_text())
        data["policy"]["quantile_bps"] = 10000
        for i, minor in enumerate((9000, 13000, 15000)):
            data["comparables"].append({
                "property_id": f"test-prop-{i}", "candidate_id": f"test-candidate-{i}",
                "provider": "booking", "provider_property_id": f"test-provider-{i}",
                "observation_id": f"test-observation-{i}",
                "observed_at": "2026-11-26T09:00:00Z", "received_at": "2026-11-26T09:00:01Z",
                "ingested_at": "2026-11-26T09:00:02Z", "qualification": "fixture",
                "scope": data["policy"]["scope"], "amount_minor": minor,
            })
        evidence.write_text(json.dumps(data))
        default = invoke("predict", evidence)
        got = json.loads(default)
        assert got["algorithm"] == "median"
        assert got["position"]["recommended_minor"] == 13000
        assert got["publication_allowed"] is False
        assert got["input_sha256"] == hashlib.sha256(evidence.read_bytes()).hexdigest()
        digest = got.pop("artifact_digest")
        assert digest == hashlib.sha256(json.dumps(got, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert predict(evidence, "--algorithm", "lower-quartile")["position"]["recommended_minor"] == 9000
        assert predict(evidence, "--algorithm", "percentile")["position"]["recommended_minor"] == 15000
        assert predict(evidence, "--as-of", "2026-11-26T09:00:00Z")["position"]["counts"]["not_yet_known"] == 3
        assert predict(evidence, "--as-of", "2026-11-28T10:00:00Z")["position"]["counts"]["stale"] == 3

        invoke("init", "--state", state)
        lines = invoke("register", "--state", state, "Price", "Source1", evidence).splitlines()
        assert json.loads(lines[1])["runner"] == "joe-litty-rooms-v1"
        # Editing the caller's file after registration cannot change the frozen job.
        evidence.write_text("{}")
        admission = "2026-11-26T10:00:00Z"
        due = "2026-11-26T10:01:00Z"
        scheduled = json.loads(invoke("kronize", "--state", state, "Price", "--at", admission, "--every", "60"))
        job = scheduled["id"]
        assert scheduled["deadline"] == due
        assert json.loads(invoke("daemon", "--state", state, "--once", "--at", admission))["outcome"] == "idle"
        dispatched = json.loads(invoke("daemon", "--state", state, "--once", "--at", due))
        assert (dispatched["outcome"], dispatched["result_status"]) == ("ran", "committed"), dispatched
        assert invoke("jobs", "--state", state, "result-show", job, due) == default
        assert json.loads(invoke("jobs", "--state", state, "next"))["deadline"] == "2026-11-26T10:02:00Z"
        invoke("jobs", "--state", state, "cancel", job)
        once = json.loads(invoke("kronize", "--state", state, "Price", "--at", due, "--once", due))
        invoke("daemon", "--state", state, "--once", "--at", due)
        assert invoke("jobs", "--state", state, "result-show", once["id"], due) == default
        assert json.loads(invoke("jobs", "--state", state, "next"))["deadline"] is None
        invoke("daemon", "--state", state, "--poll-seconds", "0", status=None)

        # The foreground service can be stopped while waiting between dispatches.
        env = dict(os.environ, LC_ALL="C")
        with subprocess.Popen(
            [CLI, "daemon", "--state", state, "--poll-seconds", "60"], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        ) as daemon:
            try:
                ready, _, _ = select.select([daemon.stdout], [], [], 10)
                assert ready, "foreground daemon did not emit its first dispatch receipt"
                assert json.loads(daemon.stdout.readline())["outcome"] == "idle"
                daemon.send_signal(signal.SIGTERM)
                assert daemon.wait(timeout=5) == 0
            finally:
                if daemon.poll() is None:
                    daemon.kill()

    print("Joe Litty Rooms CLI and Kron prediction replay: OK")


if __name__ == "__main__":
    main()
