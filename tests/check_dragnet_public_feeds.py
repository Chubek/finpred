#!/usr/bin/env python3
"""Compiled Dragnet feed conformance; transport exercises loopback only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_feeds"
ECB = (FIX / "ecb.xml").read_bytes()
ESTAT = (FIX / "eurostat.json").read_bytes()
RECEIPT = "2026-11-16T10:10:00Z"
INGEST = "2026-11-16T10:10:01Z"
ECB_PATH = "/stats/eurofxref/eurofxref-daily.xml"
TOUR_PATH = (
    "/eurostat/api/dissemination/statistics/1.0/data/tour_occ_nim"
    "?lang=EN&freq=M&unit=NR&nace_r2=I551-I553&c_resid=TOTAL&geo=EU27_2020&lastTimePeriod=3"
)


def stamp(provider, receipt=RECEIPT, ingest=INGEST, mode="offline_snapshot"):
    return f"dragnet.feed-capture@1\n{provider},{mode},{receipt},{ingest},terms-r1,retention-r2\n".encode()


def expect_json(result, validator):
    assert result.returncode == 0 and not result.stderr, result
    value = json.loads(result.stdout)
    validator.validate(value)
    return value


def snapshot(directory):
    return sorted((p.name, p.stat().st_mode, p.stat().st_ino, p.stat().st_mtime_ns,
                   p.stat().st_ctime_ns, p.read_bytes()) for p in directory.iterdir())


@contextmanager
def loopback(responses):
    seen = []
    arrived = threading.Event()
    hold = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.path, self.headers.get("Accept-Encoding"),
                         self.headers.get("Authorization")))
            arrived.set()
            status, headers, body = responses.get(self.path, (404, {}, b""))
            if status is None:
                hold.wait(20)
                return
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server.server_port, seen, arrived
        finally:
            hold.set()
            server.shutdown()
            thread.join()


def main():
    validator = Draft202012Validator(json.loads(
        (PKG / "contracts/dragnet.public-feed@1.schema.json").read_text()), format_checker=FormatChecker())
    Draft202012Validator.check_schema(validator.schema)
    with tempfile.TemporaryDirectory(prefix="dragnet-feeds-") as tmp:
        work = Path(tmp)
        build = work / "build"
        denied_store = work / "pricing"
        denied_store.mkdir(mode=0o700)
        (denied_store / "sentinel").write_text("unrelated\n")
        store_before = snapshot(denied_store)
        env = {**os.environ, "DRAGNET_FEEDS_BIN": str(build),
               "FINPRED_HOME": str(denied_store), "DRAGNET_BUILD_LOOPBACK_FIXTURE": "1",
               "https_proxy": "http://127.0.0.1:1"}
        subprocess.run([PKG / "build-feeds.sh", build], env=env, check=True, timeout=90)

        def run(*args):
            return subprocess.run([PKG / "feeds", *args], env=env, cwd=work,
                                  capture_output=True, timeout=35)

        capture = work / "capture.csv"
        raw = work / "raw.dat"

        def load(provider, body, metadata=None, cutoff=INGEST):
            capture.write_bytes(stamp(provider) if metadata is None else metadata)
            raw.write_bytes(body)
            return run("import", capture, raw, cutoff)

        first = load("ecb", ECB)
        fx = expect_json(first, validator)
        assert fx["format"] == "dragnet.ecb-fx-reference@1"
        assert fx["observations"] == [{"currency": "USD", "rate": "1.09300"},
                                      {"currency": "JPY", "rate": "174.05"}]
        assert fx["reference_date"] == "2026-11-16" and fx["provider_updated_at"] is None
        assert fx["observed_at"] == fx["received_at"] == RECEIPT
        assert fx["ingested_at"] == fx["as_of"] == INGEST
        assert fx["pricing_input"] is False and fx["raw_bytes"] == len(ECB)
        assert load("ecb", ECB).stdout == first.stdout
        crlf = expect_json(load("ecb", ECB.replace(b"\n", b"\r\n")), validator)
        assert crlf["observations"] == fx["observations"] and crlf["raw_evidence"] != fx["raw_evidence"]
        assert crlf["capture_evidence"] == fx["capture_evidence"]
        nights = expect_json(load("eurostat", ESTAT), validator)
        assert nights["format"] == "dragnet.eurostat-accommodation-nights@1"
        assert nights["raw_evidence"] == "blake3:60367005771fdca9a8057ffdd23de902b14b5b1256d57b25456d2ee371e02091"
        assert nights["status"] == "partial" and nights["pricing_input"] is False
        assert nights["observations"] == [
            {"period": "2026-07", "nights": 480000000, "provider_flag": None},
            {"period": "2026-08", "nights": 515000001, "provider_flag": "p"},
            {"period": "2026-09", "nights": None, "provider_flag": None},
        ]
        full = ESTAT.replace(b'"value":{"1":', b'"value":{"2":0,"1":')
        assert expect_json(load("eurostat", full), validator)["status"] == "complete"
        offset = ESTAT.replace(b"2026-11-16T11:00:00+0100", b"2026-11-16T05:00:00-0500")
        assert expect_json(load("eurostat", offset), validator)["observations"] == nights["observations"]
        real_cutoff = expect_json(load("eurostat", ESTAT, cutoff="2026-11-30T00:00:00Z"), validator)
        assert real_cutoff["as_of"] == "2026-11-30T00:00:00Z"

        for provider, body, error in [
            ("ecb", ECB.replace(b"JPY", b"USD"), b"duplicate FX quote"),
            ("ecb", ECB.replace(b"1.09300", b"0.00"), b"nonpositive FX"),
            ("ecb", ECB.replace(b"2026-11-16", b"2026-11-17"), b"future or stale FX"),
            ("ecb", ECB.replace(b"2026-11-16", b"2026-11-08"), b"future or stale FX"),
            ("ecb", ECB.replace(b"2026-11-16", b"2026-02-29"), b"future or stale FX"),
            ("ecb", ECB.replace(b"<gesmes:Envelope", b"<!DOCTYPE gesmes:Envelope []>\n<gesmes:Envelope"),
             b"invalid provider snapshot"),
            ("ecb", ECB[:-30], b"invalid provider snapshot"),
            ("eurostat", ESTAT.replace(b'"unit":{"category":{"index":{"NR"', b'"unit":{"category":{"index":{"EUR"'),
             b"invalid provider snapshot"),
            ("eurostat", ESTAT.replace(b"515000001", b"515000001.0"), b"invalid provider snapshot"),
            ("eurostat", ESTAT.replace(b"515000001", b"-1"), b"invalid accommodation count"),
            ("eurostat", ESTAT.replace(b'"1":515000001', b'"1":515000001,"1":1'), b"invalid provider snapshot"),
            ("eurostat", ESTAT.replace(b'"2026-09":2', b'"2026-09":0'), b"invalid provider snapshot"),
            ("eurostat", ESTAT.replace(b"2026-09", b"2026-11"), b"unfinished period"),
            ("eurostat", ESTAT.replace(b"+0100", b"+0060"), b"invalid provider update offset"),
            ("eurostat", ESTAT.replace(b"+0100", b"-0100"), b"future or stale accommodation"),
            ("eurostat", ESTAT.replace(b"2026-11-16T11", b"2026-06-16T11"), b"future or stale accommodation"),
            ("eurostat", b"x" * 65537, b"invalid frozen inputs"),
        ]:
            p = load(provider, body)
            assert p.returncode != 0 and not p.stdout and error in p.stderr, p
        for metadata, cutoff, error in [
            (stamp("ecb"), RECEIPT, b"not available as of cutoff"),
            (stamp("ecb", receipt=INGEST, ingest=RECEIPT), INGEST, b"receipt is later"),
            (stamp("ecb", mode="production"), INGEST, b"unknown capture mode"),
            (stamp("ecb").replace(b"terms-r1", b"unsafe/path"), INGEST, b"invalid policy"),
            (stamp("ecb").replace(b"capture@1", b"capture@2"), INGEST, b"invalid capture contract"),
        ]:
            p = load("ecb", ECB, metadata=metadata, cutoff=cutoff)
            assert p.returncode != 0 and not p.stdout and error in p.stderr, p

        # Independently invoke the compiled On1x consumer; a handoff from one
        # snapshot must never normalize a different body. Offline verify
        # ignores cached decoder output completely.
        cfg = stamp("ecb")
        capture.write_bytes(cfg)
        raw.write_bytes(ECB + b"\n")
        cutoff = work / "as-of.txt"
        cutoff.write_text(INGEST + "\n")
        decode = work / "decode"
        decode.write_bytes(subprocess.run([build / "dragnet-feed-decode", "ecb"], input=ECB,
                                          check=True, capture_output=True).stdout)
        p = subprocess.run(["sh", "-c", 'exec "$1" 3<"$2" 4<"$3" 5<"$4" 6<"$5"',
                            "feed-test", build / "dragnet-feed-normalize", capture, raw, decode, cutoff],
                           capture_output=True, timeout=10)
        assert p.returncode != 0 and not p.stdout and b"mismatched decode handoff" in p.stderr, p

        def spool(name):
            directory = work / name
            directory.mkdir(mode=0o700)
            return directory

        utc_now = datetime.now(timezone.utc)
        recent_ecb = ECB.replace(b"2026-11-16", utc_now.date().isoformat().encode())
        start_this_month = utc_now.date().replace(day=1)
        months = []
        for _ in range(3):
            start_this_month = (start_this_month - timedelta(days=1)).replace(day=1)
            months.insert(0, start_this_month.strftime("%Y-%m").encode())
        old = [b"2026-07", b"2026-08", b"2026-09"]
        recent_estat = ESTAT.replace(b"2026-11-16T11:00:00+0100",
                                    utc_now.strftime("%Y-%m-%dT%H:%M:%S+0000").encode())
        period_mapping = dict(zip(old, months))
        recent_estat = re.sub(rb"2026-0[789]", lambda m: period_mapping[m[0]], recent_estat)
        good = {ECB_PATH: (200, {"Content-Type": "text/xml"}, recent_ecb),
                TOUR_PATH: (200, {"Content-Type": "application/json"}, recent_estat)}
        out = spool("success")
        with loopback(good) as (port, seen, _):
            p = run("poll-fixture", str(port), out, "terms-r1", "retention-r2")
            assert p.returncode == 1 and not p.stderr, p
            events = [json.loads(line) for line in p.stdout.splitlines()]
            assert [(e["provider"], e["status"]) for e in events] == [("ecb", "complete"), ("eurostat", "partial")]
            assert seen == [(ECB_PATH, "identity", None), (TOUR_PATH, "identity", None)]
            p = run("poll-fixture", str(port), out, "terms-r1", "retention-r2")
            assert p.returncode == 1 and [json.loads(line)["status"] for line in p.stdout.splitlines()] == ["deferred"] * 2
            assert len(seen) == 2
        for event, body in zip(events, [recent_ecb, recent_estat]):
            bundle = out / event["detail"]
            assert (bundle / "body").read_bytes() == body
            assert bundle.stat().st_mode & 0o777 == 0o500
            artifact = json.loads((bundle / "observation.json").read_bytes())
            validator.validate(artifact)
            assert artifact["mode"] == "loopback_fixture"
            assert artifact["observed_at"] == artifact["received_at"] <= artifact["ingested_at"] == artifact["as_of"]
            before = snapshot(bundle)
            result = run("verify", bundle)
            assert result.returncode == 0 and result.stdout == b"dragnet_feed_replay_ok=true\n", result
            assert snapshot(bundle) == before
            fake = spool("tampered-" + event["provider"])
            for f in bundle.iterdir():
                shutil.copyfile(f, fake / f.name)
            (fake / "body").write_bytes(body + b"\n")
            assert run("verify", fake).returncode != 0
            if shutil.which("strace"):
                trace = work / "network.trace"
                p = subprocess.run(["strace", "-f", "-e", "trace=network", "-o", trace,
                                    PKG / "feeds", "verify", bundle], env=env,
                                   capture_output=True, timeout=15)
                assert p.returncode == 0, p
                assert not any("socket(" in l or "connect(" in l for l in trace.read_text().splitlines())

        for code, headers, body, reason in [
            (302, {"Location": "/unexpected"}, b"", "http_status"),
            (503, {"Retry-After": "3600"}, b"", "provider_backoff"),
            (429, {}, b"", "provider_backoff"),
            (200, {"Content-Encoding": "gzip"}, recent_ecb, "content_encoding"),
            (200, {"Content-Length": str(len(recent_ecb) + 10)}, recent_ecb, "incomplete_transfer"),
            (200, {"Content-Type": "text/html"}, recent_ecb, "content_type"),
            (200, {"Content-Length": "65537"}, b"x" * 65537, "transfer_limit"),
            (200, {}, b"x" * 65537, "transfer_limit"),
            (200, {}, b"<wrong />", "invalid_snapshot"),
            (None, {}, b"", "timeout"),
        ]:
            out = spool("failed-" + str(len(list(work.iterdir()))))
            ecb_res = (code, {"Content-Type": "text/xml", **headers}, body)
            with loopback({**good, ECB_PATH: ecb_res}) as (port, seen, _):
                p = run("poll-fixture", str(port), out, "terms-r1", "retention-r2")
                events = [json.loads(line) for line in p.stdout.splitlines()]
                assert p.returncode == 1 and events[0]["status"] == "failed" and events[0]["detail"] == reason, p
                assert events[1]["status"] == "partial" and [r[0] for r in seen] == [ECB_PATH, TOUR_PATH], p
                assert not list(out.glob(".incoming*")) and not list(out.glob("loopback_fixture-ecb-*"))
                if reason == "provider_backoff":
                    assert (out / ".dragnet-loopback_fixture-ecb-next").read_text() == "provider_hold\n"

        out = spool("cancel")
        with loopback({**good, ECB_PATH: (None, {}, b"")}) as (port, seen, arrived):
            proc = subprocess.Popen([PKG / "feeds", "poll-fixture", str(port), out, "terms-r1", "retention-r2"],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                assert arrived.wait(5), "worker never reached the loopback fixture"
                assert run("poll-fixture", str(port), out, "terms-r1", "retention-r2").returncode == 2
                proc.send_signal(signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=5)
                assert proc.returncode != 0 and not stdout and not stderr, (stdout, stderr)
                assert not list(out.glob(".incoming*")) and not list(out.glob("loopback_fixture-*"))
                assert [r[0] for r in seen] == [ECB_PATH]
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        assert (out / ".dragnet-loopback_fixture-ecb-next").exists()
        assert run("poll-fixture", "1", denied_store, "terms-r1", "retention-r2").returncode == 2
        with tempfile.TemporaryDirectory(dir=denied_store) as nested:
            assert run("poll-fixture", "1", nested, "terms-r1", "retention-r2").returncode == 2
        assert snapshot(denied_store) == store_before
        assert run("poll", "arbitrary-url", out, "terms-r1", "retention-r2", "1").returncode == 2
        assert run("poll-fixture", "https://localhost/", out, "terms-r1", "retention-r2").returncode == 2
    print("dragnet_public_feeds_ok=true providers=2 acquisition=loopback offline_replay=verified")


if __name__ == "__main__":
    main()
