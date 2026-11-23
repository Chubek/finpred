#!/usr/bin/env python3
"""Compile and exercise the trusted, offline Dragnet Source dispatch host.

Run after installing libcurl, libxml2, Jansson and the pinned On1x toolchain.
Only saved fixtures are used.  No external provider is contacted.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

from check_crossref_replay import GOLDEN_BYTES
from check_dragnet_frozen_csv import FIXTURE_DIGEST

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_feeds"


def run(*args, input=None, env=None, cwd=ROOT, timeout=90, good=True):
    p = subprocess.run(args, input=input, capture_output=True, cwd=cwd,
                       env=env, timeout=timeout)
    if good:
        assert p.returncode == 0, (args, p)
    return p


def inherited(exe, paths, work, env, *, good=True, trace=None):
    # All paths are positional parameters. No file content is interpolated
    # into the shell source. Explicitly close any unused descriptor slots.
    slots = [*paths, *([None] * (6 - len(paths)))]
    redirs = " ".join(f'{fd}<"${fd - 1}"' if path else f"{fd}<&-"
                      for fd, path in enumerate(slots, 3))
    prefix = ("strace", "-f", "-e", "trace=network", "-o", trace) if trace else ()
    result = run(*prefix, "bash", "-c", 'exec "$1" ' + redirs, "dragnet", str(exe),
                 *(str(p) if p else "" for p in paths), cwd=work, env=env, good=good, timeout=30)
    if trace:
        # A successful strace with no network syscalls records only process exits.
        traced = trace.read_text().strip()
        assert traced.endswith("+++ exited with 0 +++") and "(" not in traced, traced
    return result


def routed(exe, selector, files, work, env, *, good=True, trace=None):
    if isinstance(selector, str):
        selector = (selector + "\n").encode("ascii")
    select = raw("source-selector.txt", selector, work)
    return inherited(exe, [select, *files], work, env, good=good, trace=trace)


def rejected(result, error):
    assert result.returncode > 0 and not result.stdout and error in result.stderr, result


def raw(name, content, directory):
    p = directory / name
    p.write_bytes(content)
    return p


def validator(path):
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def check_policy(work, env):
    mulib = Path(env.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(env.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    consumer = work / "source-policy"
    run(sys.executable, mulib / "on1x/tools/on1x-build.py",
        ROOT / "tests/dragnet_dispatch_consumer/policy.on1x", "--backend", "c11",
        "--on1xc", compiler, "--mulib-root", mulib, "-I", PKG / "source",
        "-I", ROOT / "source", "-I", ROOT, "-o", consumer, env=env, cwd=work, timeout=180)
    for source in ("dragnet.frozen_csv@1", "dragnet.crossref@1", "dragnet.public-feed@1"):
        for mode in ("execution", "recommendation"):
            rejected(run(consumer, cwd=work, good=False, env={
                **env, "DRAGNET_TEST_SOURCE": source, "DRAGNET_TEST_MODE": mode,
            }), b"dragnet source: denied or unknown source")


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
        trace = work / "network.trace" if shutil.which("strace") else None

        scenario = ROOT / "fixtures/scenario.csv"
        offers = ROOT / "fixtures/offers.csv"
        csv_source = "dragnet.frozen_csv@1"
        csv_out = work / "frozen-csv"
        run(PKG / "build.sh", csv_out, env=env, timeout=180)
        frozen = routed(exe, csv_source, [scenario, offers], work, env, trace=trace).stdout
        assert frozen == inherited(csv_out / "dragnet-frozen-csv", [scenario, offers], work, env).stdout
        records = [json.loads(line) for line in frozen.splitlines()]
        assert len(records) == 5
        offer_schema = validator(ROOT / "contracts/hospitality.offer@1.schema.json")
        for rec in records:
            offer_schema.validate(rec)
            assert rec["metadata"]["provenance"]["source_artifacts"] == [FIXTURE_DIGEST]

        absent_home = work / "absent-pricing-store"
        assert routed(exe, csv_source, [scenario, offers], work,
                      {**env, "FINPRED_HOME": str(absent_home)}).stdout == frozen
        assert not absent_home.exists()

        # Reject incompatible versions and unknown algorithms *before* any
        # unselected data descriptor can be read.
        for source in ("dragnet.frozen_csv@2", "dragnet.unknown@1", "dragnet.public-feed@2"):
            rejected(routed(exe, source, [], work, env, good=False), b"denied")
        for source in (b"Dragnet.frozen_csv@1\n", b"dragnet.frozen_csv@1",
                       b"dragnet.frozen_csv@1\r\n", b"dragnet.frozen_csv@1\n\n"):
            rejected(routed(exe, source, [], work, env, good=False), b"invalid source selector")
        for source in (b"", b"x" * 128 + b"\n"):
            rejected(routed(exe, source, [], work, env, good=False), b"bounded descriptor snapshot")
        for bad in (raw("empty-offers.csv", b"", work), raw("large-offers.csv", b"x" * 2000001, work)):
            rejected(routed(exe, csv_source, [scenario, bad], work, env, good=False),
                     b"bounded descriptor snapshot")
        for files in ([scenario], [None, offers]):
            p = routed(exe, csv_source, files, work, env, good=False)
            assert p.returncode > 0 and not p.stdout and p.stderr, p
        header, row, *_ = offers.read_bytes().splitlines(keepends=True)
        for content, error in ((header.replace(b"property_id", b"invalid_id") + row, b"unexpected header"),
                               (header + row + row, b"duplicate bookable room")):
            bad = raw("invalid-offers.csv", content, work)
            rejected(routed(exe, csv_source, [scenario, bad], work, env, good=False), error)

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
        dispatched = routed(exe, "dragnet.crossref@1", inputs, work, env, trace=trace).stdout
        # Invoke the pre-existing importer with exactly the five descriptor
        # files, without a source-selector descriptor.
        original = inherited(crossref_out / "dragnet-crossref-import", inputs, work, env).stdout
        assert dispatched == original == GOLDEN_BYTES
        validator(PKG / "contracts/dragnet.crossref-evidence@1.schema.json").validate(json.loads(dispatched))
        output_hashes = {"frozen_csv": sha256(frozen).hexdigest(), "crossref": sha256(dispatched).hexdigest()}
        p = routed(exe, "dragnet.crossref@1", [req, search, detail, work_decode, search_decode],
                   work, env, good=False)
        assert p.returncode != 0 and not p.stdout, p

        # Reuse the actual native feed decoder and existing On1x normalizer.
        feeds_out = work / "feeds"
        run(PKG / "build-feeds.sh", feeds_out, env=env, timeout=180)
        asof = raw("as-of.txt", b"2026-11-16T10:10:01Z\n", work)
        early = raw("early-as-of.txt", b"2026-11-16T10:10:00Z\n", work)
        bad_time = raw("malformed-as-of.txt", b"2026-11-16T10:10:01ZX", work)
        feed_schema = validator(PKG / "contracts/dragnet.public-feed@1.schema.json")
        for source, fixture in (("ecb", "ecb.xml"), ("eurostat", "eurostat.json")):
            capture = raw(source + ".capture.csv", (
                "dragnet.feed-capture@1\n"
                f"{source},offline_snapshot,2026-11-16T10:10:00Z,"
                "2026-11-16T10:10:01Z,terms-r1,retention-r2\n").encode(), work)
            body = FIX / fixture
            handoff = raw(source + ".decode", run(feeds_out / "dragnet-feed-decode",
                                                  source, input=body.read_bytes(), env=env).stdout, work)
            dispatched = routed(exe, "dragnet.public-feed@1", [capture, body, handoff, asof],
                                work, env, trace=trace).stdout
            expected = run(PKG / "feeds", "import", capture, body, "2026-11-16T10:10:01Z",
                           env={**env, "DRAGNET_FEEDS_BIN": str(feeds_out)}).stdout
            assert dispatched == expected
            artifact = json.loads(dispatched)
            feed_schema.validate(artifact)
            assert artifact["pricing_input"] is False
            assert artifact["raw_bytes"] == body.stat().st_size
            output_hashes[source] = sha256(dispatched).hexdigest()
            bad_body = raw("tampered-body", body.read_bytes() + b"\n", work)
            for raw_body, cutoff, error in (
                (bad_body, asof, b"mismatched decode handoff"),
                (body, early, b"not available as of cutoff"),
                (body, bad_time, b"malformed as-of timestamp"),
            ):
                rejected(routed(exe, "dragnet.public-feed@1", [capture, raw_body, handoff, cutoff],
                                work, env, good=False), error)

        check_policy(work, env)
        assert marker.read_bytes() == b"no plugin writes\n"
        assert [p.name for p in protected.iterdir()] == ["sentinel"]
    print("dragnet_dispatch_ok=true sources=3 parity_fixtures=4 denied_modes=6 pricing_store_unchanged=true"
          f" network_traced={'4' if trace else '0'}")
    print("dragnet_dispatch_output_sha256=" + json.dumps(output_hashes, sort_keys=True))


if __name__ == "__main__":
    main()
