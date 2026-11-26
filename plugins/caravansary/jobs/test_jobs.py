"""Offline subprocess tests: each CLI call reopens registry and Kron storage."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TMP = ROOT / "build/caravansary/W5/tmp"
RUNNER = "finpred-caravansary-jobs-runner-v1"
MARKET_RUNNER = "finpred-caravansary-jobs-runner-market-v1"
MARKET = "finpred-caravansary-market"
MARKET_PROBE = "finpred-caravansary-market-probe-v1"
OPTIONS = None


class Jobs(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        work = tempfile.TemporaryDirectory(dir=TMP)
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.state = self.work / "state"
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.exe = self.bin / OPTIONS.binary.name
        shutil.copy2(OPTIONS.binary, self.exe)
        for name in (RUNNER, MARKET_RUNNER):
            shutil.copy2(OPTIONS.binary.with_name(name), self.bin / name)
        self.call("init")

    def run_cli(self, *args, data=None, state=None, code=0):
        p = subprocess.run(
            [self.exe, "--state", self.state if state is None else state, *args],
            input=data,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(p.returncode, code, (args, p.stdout, p.stderr))
        return p

    def call(self, *args, **kw):
        p = self.run_cli(*args, **kw)
        if kw.get("code", 0):
            self.assertEqual(p.stdout, b"")
            self.assertTrue(p.stderr)
            return None
        self.assertEqual(p.stderr, b"")
        value = json.loads(p.stdout)
        self.assertEqual(
            p.stdout, (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        )
        return value

    def add_fixture(self):
        fixture = b"fictional fixture\n\0not interpreted"
        info = self.call("source-add", "Src", data=fixture)
        self.assertEqual(info["sha256"], hashlib.sha256(fixture).hexdigest())
        self.assertEqual(info["bytes"], len(fixture))
        self.assertEqual(self.call("source-show", "Src"), {k: v for k, v in info.items() if k != "status"})
        self.call("profile-add", "Profile", "Src")
        self.call("source-add", "Src", data=b"changed", code=2)
        self.call("profile-add", "Profile", "Src", code=2)

    def test_once_order_reopen_and_cancel(self):
        self.add_fixture()
        before = "2024-02-29T01:00:00Z"
        due = "2024-02-29T01:00:01Z"
        for _ in range(3):
            report = self.call("schedule", "Profile", "--at", before, "--once", due)
            self.assertEqual(report["deadline"], due)
        self.assertEqual(self.call("cancel", "3")["id"], "3")
        self.assertEqual(self.call("next")["deadline"], due)
        self.assertEqual(self.call("dispatch", "--at", before)["outcome"], "idle")
        for expected in ("1", "2"):
            result = self.call("dispatch", "--at", due)
            self.assertEqual((result["id"], result["deadline"], result["outcome"]), (expected, due, "ran"))
            self.assertEqual(result["process"]["state"], "exited")
            self.assertEqual(result["process"]["exit_code"], 0)
        self.assertIsNone(self.call("next")["deadline"])
        self.call("cancel", "1", code=2)
        self.assertEqual(self.call("dispatch", "--at", due)["outcome"], "idle")

    def test_every_coalesces_and_revocation_prevents_launch(self):
        self.add_fixture()
        clock = "2026-11-26T00:00:00Z"
        first = self.call("schedule", "Profile", "--at", clock, "--every", "10")
        self.assertEqual(first["deadline"], "2026-11-26T00:00:10Z")
        result = self.call("dispatch", "--at", "2026-11-26T00:00:45Z")
        self.assertEqual((result["id"], result["deadline"], result["outcome"]),
                         (first["id"], first["deadline"], "ran"))
        self.assertEqual(self.call("next")["deadline"], "2026-11-26T00:00:50Z")
        self.assertFalse(self.call("profile-disable", "Profile")["active"])
        self.assertFalse(self.call("profile-show", "Profile")["active"])
        self.assertFalse(self.call("profile-disable", "Profile")["active"])
        self.call("schedule", "Profile", "--at", "2026-11-26T00:00:50Z", "--every", "10", code=2)
        denial = self.call("dispatch", "--at", "2026-11-26T00:00:51Z")
        self.assertEqual((denial["outcome"], denial["process"]), ("denied", None))
        self.assertEqual(self.call("next")["deadline"], "2026-11-26T00:01:00Z")
        self.call("cancel", first["id"])
        self.assertIsNone(self.call("next")["deadline"])

    def test_invalid_clocks_paths_and_lock(self):
        self.add_fixture()
        for clock in ("2023-02-29T00:00:00Z", "2100-02-29T00:00:00Z", "2024-01-01t00:00:00Z",
                      "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:60Z", "2024-01-01T00:00:00.0Z",
                      "1969-12-31T23:59:59Z", "2024-01-01T24:00:00Z"):
            self.call("dispatch", "--at", clock, code=2)
        self.call("dispatch", "--at", "2000-02-29T00:00:00Z")
        self.call("dispatch", "--at", "2000-02-28T23:59:59Z", code=2)
        self.call("schedule", "Profile", "--at", "2000-02-29T00:00:00Z",
                  "--once", "2000-02-28T23:59:59Z", code=2)
        for step in ("0", "+1", "01", "18446744073709551616"):
            self.call("schedule", "Profile", "--at", "2000-02-29T00:00:00Z", "--every", step, code=2)
        self.call("schedule", "Profile", "--at", "9999-12-31T23:59:59Z", "--every", "1", code=2)
        self.call("schedule", "Profile", "--at", "9999-12-31T23:59:58Z", "--every", "1")
        self.assertEqual(self.call("dispatch", "--at", "9999-12-31T23:59:59Z")["outcome"], "ran")
        self.assertIsNone(self.call("next")["deadline"])
        self.call("source-show", "../clock", code=2)
        alias = self.work / "alias"
        alias.symlink_to(self.state, target_is_directory=True)
        for state in (alias, f"{self.state}/", f"{self.work}/./state", "relative"):
            self.call("next", state=state, code=2)
        writable = self.work / "writable"
        writable.mkdir()
        writable.chmod(0o777)
        self.call("init", state=writable / "unsafe", code=2)
        self.bin.chmod(0o1777)
        try:
            self.call("dispatch", "--at", "9999-12-31T23:59:59Z", code=2)
        finally:
            self.bin.chmod(0o755)
        fd = os.open(self.state, os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.call("next", code=2)
            self.call("source-add", "Locked", data=b"fixture", code=2)
        finally:
            os.close(fd)
        (self.state / "kron/events.kvdb").unlink()
        self.call("next", code=2)
        self.assertFalse((self.state / "kron/events.kvdb").exists())

    def test_immutable_profile_binding_and_failed_runner(self):
        self.add_fixture()
        now = "2026-11-26T00:00:00Z"
        self.call("schedule", "Profile", "--at", now, "--once", now)
        record = self.state / "sources/Src"
        original = record.read_bytes()
        changed = b"different resealed data"
        record.write_bytes(f"CVSOURCE1 {hashlib.sha256(changed).hexdigest()}\n".encode() + changed)
        self.assertEqual(self.call("dispatch", "--at", now)["outcome"], "denied")
        record.write_bytes(original)
        self.call("schedule", "Profile", "--at", now, "--once", now)
        # Deliberately substitute a no-network test executable in a private
        # test deployment to exercise real wait/exit status propagation.
        subprocess.run(["clang", "-x", "c", "-", "-o", self.bin / RUNNER],
                       input=b"int main(void) { return 23; }\n", check=True,
                       env={**os.environ, "TMPDIR": str(self.work)})
        failed = self.call("dispatch", "--at", now)
        self.assertEqual((failed["outcome"], failed["process"]["exit_code"]), ("failed", 23))
        self.assertIsNone(self.call("next")["deadline"])

    def test_market_e2e(self):
        if OPTIONS.market is None:
            self.skipTest("pass --market with the built real W6 offline market executable")
        shutil.copy2(OPTIONS.market, self.bin / MARKET)
        probe = OPTIONS.market.with_name(MARKET_PROBE)
        if probe.exists():
            shutil.copy2(probe, self.bin / MARKET_PROBE)
        example = ROOT / "plugins/caravansary/examples"
        script = example / "workflows/canal-market.caf"
        capture = example / "providers/booking-profile.html"
        s = self.call("source-add", "Script1", data=script.read_bytes())["sha256"]
        c = self.call("source-add", "Capture1", data=capture.read_bytes())["sha256"]
        manifest = (
            "CVSCRAPE1\n"
            "booking_profile booking-profile booking https://booking.example/fixtures/profile "
            "2026-11-26T09:50:00Z 2026-11-26T10:00:00Z\n"
            f"Script1 {s}\n"
            f"Capture1 {c}\n"
        ).encode()
        self.call("source-add", "BadManifest", data=manifest.replace(c.encode(), b"0" * 64))
        self.call("market-profile-add", "Bad", "BadManifest", code=2)
        self.call("source-add", "Manifest1", data=manifest)
        self.assertEqual(self.call("market-profile-add", "Scrape1", "Manifest1")["runner"], "market-scrape-v1")
        now, due = "2026-11-26T10:01:00Z", "2026-11-26T10:01:01Z"
        id_ = self.call("schedule", "Scrape1", "--at", now, "--once", due)["id"]
        self.call("result-show", id_, due, code=2)
        first = self.call("dispatch", "--at", due)
        self.assertEqual((first["id"], first["outcome"], first["result_status"]), (id_, "ran", "committed"))
        output = self.run_cli("result-show", id_, due).stdout
        artifact = json.loads(output)
        direct = subprocess.run(
            [self.bin / MARKET, "scrape", script, "--source", "booking_profile", "--input-root", example,
             "--host-grants", example / "workflows/host-grants.json", "--as-of", "2026-11-26T10:00:00Z"],
            check=True, capture_output=True, timeout=15,
        )
        self.assertEqual(output, direct.stdout)
        self.assertEqual(artifact["kind"], "caravansary.market.scrape@1")
        self.assertEqual(artifact["inputs"]["capture_sha256"]["booking_profile"], c)
        self.assertFalse(artifact["publication_allowed"])
        self.assertFalse(list(self.state.glob(".dispatch.*")))
        id2 = self.call("schedule", "Scrape1", "--at", due, "--once", due)["id"]
        self.call("profile-disable", "Scrape1")
        self.assertEqual(self.call("dispatch", "--at", due)["outcome"], "denied")
        self.call("result-show", id2, due, code=2)
        invalid = self.call("source-add", "ScriptBad", data=b"not a caravan document\n")["sha256"]
        self.call("source-add", "ManifestBadScript",
                  data=manifest.replace(f"Script1 {s}".encode(), f"ScriptBad {invalid}".encode()))
        self.call("market-profile-add", "BadScript", "ManifestBadScript")
        id3 = self.call("schedule", "BadScript", "--at", due, "--once", due)["id"]
        result = self.call("dispatch", "--at", due)
        self.assertEqual((result["outcome"], result["result_status"], result["id"]),
                         ("failed", "not_committed", id3))
        self.call("result-show", id3, due, code=2)
        self.assertFalse(list(self.state.glob(".dispatch.*")))

    def test_market_plumbing(self):
        # Exercises argv, materialized fixture/grant, staging and failure
        # handling without the optional W6 binary. Not a market workflow test.
        subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        HERE / "test_market_runner.c", "-o", self.bin / MARKET],
                       check=True, env={**os.environ, "TMPDIR": str(self.work)})
        clock = "2026-11-26T10:01:01Z"
        capture = self.call("source-add", "Capture", data=b"test-only capture\n")["sha256"]
        for name, script_bytes in (("Good", b"test-only script\n"),
                                   ("Broken", b"test-only script; fail after write\n")):
            script = self.call("source-add", f"{name}Script", data=script_bytes)["sha256"]
            manifest = (
                "CVSCRAPE1\n"
                "test_source test-fixture booking https://booking.example/fixtures/profile "
                "2026-11-26T09:50:00Z 2026-11-26T10:00:00Z\n"
                f"{name}Script {script}\n"
                f"Capture {capture}\n"
            ).encode()
            self.call("source-add", f"{name}Manifest", data=manifest)
            self.call("market-profile-add", name, f"{name}Manifest")
            receipt = self.call("schedule", name, "--at", clock, "--once", clock)
            result = self.call("dispatch", "--at", clock)
            if name == "Good":
                self.assertEqual((result["outcome"], result["result_status"]), ("ran", "committed"))
                readback = self.call("result-show", receipt["id"], clock)
                self.assertEqual(readback, {"kind": "caravansary.market.scrape@1", "test_only": True})
            else:
                self.assertEqual((result["outcome"], result["result_status"]), ("failed", "not_committed"))
                self.assertEqual(result["process"]["exit_code"], 13)
                self.call("result-show", receipt["id"], clock, code=2)
            self.assertFalse(list(self.state.glob(".dispatch.*")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=lambda s: Path(s).resolve())
    parser.add_argument("--market", type=lambda s: Path(s).resolve())
    OPTIONS = parser.parse_args()
    unittest.main(argv=[__file__], verbosity=2)
