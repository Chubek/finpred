#!/usr/bin/env python3
"""Compile and exercise the trusted, offline Dragnet Source dispatch host.

Run after installing libcurl, libxml2, Jansson and the pinned On1x toolchain.
Only saved fixtures are used.  No external provider is contacted.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_feeds"


def run(*args, input=None, env=None, timeout=90, good=True):
    p = subprocess.run(args, input=input, capture_output=True, cwd=ROOT,
                       env=env, timeout=timeout)
    if good:
        assert p.returncode == 0, (args, p)
    return p


def routed(exe, selector, files, work, env=None, good=True):
    select = work / "source-selector.txt"
    select.write_bytes((selector + "\n").encode("ascii"))
    paths = [select, *files]
    # All paths are positional parameters. No file content is interpolated
    # into the shell source, and the host receives only inherited fds.
    redirs = " ".join(f'{i + 3}<"${i + 2}"' for i in range(len(paths)))
    script = 'exec "$1" ' + redirs
    return run("bash", "-c", script, "dispatch", str(exe), *(str(p) for p in paths),
               env=env, good=good, timeout=30)


def raw(name, content, directory):
    p = directory / name
    p.write_bytes(content)
    return p


def body_from_json_lines(payload):
    return [json.loads(line) for line in payload.splitlines()]


def main():
    with tempfile.TemporaryDirectory(prefix="dragnet-dispatch-") as temp:
        work = Path(temp)
        env = os.environ.copy()
        env["DRAGNET_BUILD_LOOPBACK_FIXTURE"] = "0"
        protected = work / "protected-pricing-store"
        protected.mkdir(mode=0o700)
        marker = protected / "sentinel"
        marker.write_bytes(b"no plugin writes\n")
        env["FINPRED_HOME"] = str(protected)
        output = work / "dispatch-output"
        run(PKG / "build-dispatch.sh", output, env=env, timeout=180)
        exe = output / "dragnet-source-dispatch"
        assert exe.is_file() and os.access(exe, os.X_OK), exe

        scenario = ROOT / "fixtures/scenario.csv"
        offers = ROOT / "fixtures/offers.csv"
        frozen = routed(exe, "dragnet.frozen_csv@1", [scenario, offers], work, env).stdout
        records = body_from_json_lines(frozen)
        assert len(records) == 5
        assert all(rec["kind"] == "hospitality.offer" for rec in records)
        # Reject incompatible versions and unknown algorithms *before* any
        # unselected data descriptor can be read.
        for source in ("dragnet.frozen_csv@2", "dragnet.unknown@1", "dragnet.public-feed@2"):
            p = routed(exe, source, [], work, env, good=False)
            assert p.returncode != 0 and not p.stdout and b"denied" in p.stderr, p
        truncated = raw("invalid-offers.csv", offers.read_bytes().replace(b"property_id", b"invalid_id", 1), work)
        p = routed(exe, "dragnet.frozen_csv@1", [scenario, truncated], work, env, good=False)
        assert p.returncode != 0 and not p.stdout, p

        # Existing Crossref decoder remains separately executable.  A bad
        # decoder-to-raw digest pairing must not pass through the gateway.
        crossref_out = work / "crossref"
        run(PKG / "build-crossref.sh", crossref_out, env=env, timeout=180)
        crossref = ROOT / "tests/dragnet_elvi_consumer"
        search = crossref / "search.json"
        detail = crossref / "work.json"
        req = crossref / "request.csv"
        decoder = crossref_out / "dragnet-crossref-capture"
        search_decode = raw("search.decode", run(decoder, "search", "hotel & rates",
                                                 input=search.read_bytes(), env=env).stdout, work)
        work_decode = raw("work.decode", run(decoder, "work", input=detail.read_bytes(), env=env).stdout, work)
        inputs = [req, search, detail, search_decode, work_decode]
        dispatched = routed(exe, "dragnet.crossref@1", inputs, work, env).stdout
        # Invoke the pre-existing importer with exactly the five descriptor
        # files, without a source-selector descriptor.
        redirs = " ".join(f'{i+3}<"${i+2}"' for i in range(len(inputs)))
        original = run("bash", "-c", 'exec "$1" ' + redirs, "import",
                       str(crossref_out / "dragnet-crossref-import"),
                       *(str(p) for p in inputs), env=env).stdout
        assert dispatched == original
        assert json.loads(dispatched)["format"] == "dragnet.crossref-evidence@1"
        p = routed(exe, "dragnet.crossref@1", [req, search, detail, work_decode, search_decode],
                   work, env, good=False)
        assert p.returncode != 0 and not p.stdout, p

        # Reuse the actual native feed decoder and existing On1x normalizer.
        feeds_out = work / "feeds"
        run(PKG / "build-feeds.sh", feeds_out, env=env, timeout=180)
        asof = raw("as-of.txt", b"2026-11-16T10:10:01Z\n", work)
        for source, fixture in (("ecb", "ecb.xml"), ("eurostat", "eurostat.json")):
            capture = raw(source + ".capture.csv", (
                "dragnet.feed-capture@1\n"
                f"{source},offline_snapshot,2026-11-16T10:10:00Z,"
                "2026-11-16T10:10:01Z,terms-r1,retention-r2\n").encode(), work)
            body = FIX / fixture
            handoff = raw(source + ".decode", run(feeds_out / "dragnet-feed-decode",
                                                  source, input=body.read_bytes(), env=env).stdout, work)
            dispatched = routed(exe, "dragnet.public-feed@1", [capture, body, handoff, asof],
                                work, env).stdout
            expected = run(PKG / "feeds", "import", capture, body, "2026-11-16T10:10:01Z",
                           env={**env, "DRAGNET_FEEDS_BIN": str(feeds_out)}).stdout
            assert dispatched == expected
            artifact = json.loads(dispatched)
            assert artifact["pricing_input"] is False
            assert artifact["raw_evidence"].startswith("blake3:")
            bad_body = raw("tampered-body", body.read_bytes() + b"\n", work)
            p = routed(exe, "dragnet.public-feed@1", [capture, bad_body, handoff, asof],
                       work, env, good=False)
            assert p.returncode != 0 and not p.stdout, p

        assert marker.read_bytes() == b"no plugin writes\n"
        assert [p.name for p in protected.iterdir()] == ["sentinel"]
    print("dragnet_dispatch_ok=true sources=3 host_writes=0 network=none")


if __name__ == "__main__":
    main()
