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
from xml.etree import ElementTree

from jsonschema import Draft202012Validator, FormatChecker

from check_crossref_replay import GOLDEN_BYTES
from check_dragnet_frozen_csv import FIXTURE_DIGEST

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins/dragnet"
FIX = ROOT / "tests/dragnet_feeds"
# Application source closure (not compiler/stdlib or native decoder).
# The identity module is excluded so its fingerprint is not self-referential.
SOURCE_CLOSURE = (
    "plugins/dragnet/source/dragnet/frozen_crossref.on1x",
    "plugins/dragnet/source/dragnet/frozen_csv.on1x",
    "plugins/dragnet/source/dragnet/public_feeds.on1x",
    "plugins/dragnet/source/dragnet/source_registry.on1x",
    "plugins/yieldcraft/matcher.on1x",
    "source/core/contracts.on1x", "source/core/csv.on1x", "source/core/date.on1x",
    "source/core/format.on1x", "source/core/money.on1x", "source/core/serialize.on1x",
    "source/sdk/callable.on1x", "source/sdk/packages.on1x", "source/sdk/registry.on1x",
)
P0B_SHA256 = {
    "crossref": "cb5ac6b40e5e8f25bd6748fdc7abd845793fc79e5cd04f886e81f27619aaca3d",
    "ecb": "dee6b6f01e0d25c783e2a3b8fb145aab6022fd1ed029e9205c0917591ace32b2",
    "eurostat": "7e47fff84e82befe9c7261adf441ad5c6471ba2330ca3eb1439072018e6b7e3e",
    "frozen_csv": "79f38dcdad31dd5f07de9ae50c584edbc83d658721c3bf02ff73e2f413d3ebbd",
}
POLICY_DIGESTS = (
    b"blake3:3345b769d3b862d23cb42ad56fdb3bc24244409fba34d96ee8c0b098c2a3646b",
    b"blake3:ee4c224d4765436994e433741d323588ffcc8940d8bff5b9f0ac417d81975d1a",
    b"blake3:6adf072d96ce1553818f937ae3c2847dacf8669f080fbe914d3b8a888d283bc3",
    b"blake3:5479b1909e3b56823e1d8054e8dd84429d8ba38c213f86073fdbf27fbcd4579d",
)
FX_PARENT = "blake3:df0a0fa5f8d8a133aef861cdc3e8e2495110a53315ac5de3885e0df39a51aae5"
FX_PROJECTIONS = {
    "JPY": "blake3:4956ffbbecb91f0363a4a4662537e260a7e9c8ac4018cbbb7c7b64e0b0ff7a30",
    "USD": "blake3:4a9f364efd1b1bbd10605ea186ba466a04ddef468db336357fb70eb22c20cc51",
}


def run(*args, input=None, env=None, cwd=ROOT, timeout=90, good=True):
    p = subprocess.run(args, input=input, capture_output=True, cwd=cwd,
                       env=env, timeout=timeout)
    if good:
        assert p.returncode == 0, (args, p)
    return p


def inherited(exe, paths, work, env, *, good=True, trace=None):
    # All paths are positional parameters. No file content is interpolated
    # into the shell source. Pass the six slots before the command vector.
    slots = [*paths, *([None] * (6 - len(paths)))]
    redirs = " ".join(f'{fd}<"${fd - 2}"' if path else f"{fd}<&-"
                      for fd, path in enumerate(slots, 3))
    # Trace only the dispatcher and its descendants. Some Bash builds probe
    # stdin with getpeername() at startup, before the dispatcher is launched.
    command = ("strace", "-f", "-e", "trace=network", "-o", trace, "--", exe) if trace else (exe,)
    result = run("bash", "-c", 'exec "${@:7}" ' + redirs, "dragnet",
                 *(str(p) if p else "" for p in slots), *command,
                 cwd=work, env=env, good=good, timeout=30)
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


def sdk_consumer(work, env):
    mulib = Path(env.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(env.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    consumer = work / "source-sdk"
    run(sys.executable, mulib / "on1x/tools/on1x-build.py",
        ROOT / "tests/dragnet_dispatch_consumer/sdk.on1x", "--backend", "c11",
        "--on1xc", compiler, "--mulib-root", mulib, "-I", PKG / "source",
        "-I", ROOT / "source", "-I", ROOT, "-o", consumer, env=env, cwd=work, timeout=180)

    def frame(data):
        return str(len(data)).encode("ascii") + b":" + data

    bundle = raw("source-closure.bundle", frame(b"dragnet.source-closure@1") + b"".join(
        frame(path.encode("ascii")) + frame((ROOT / path).read_bytes()) for path in SOURCE_CLOSURE), work)

    def invoke(key, files=(), *, case="success", cutoff="2026-11-16T10:10:01Z",
               mode="analysis", rc=0, error=None, parent="", base="EUR", quote="USD"):
        p = run(consumer, cwd=work, good=False, env={
            **env, "DRAGNET_SDK_SOURCE": key, "DRAGNET_SDK_MODE": mode, "DRAGNET_SDK_CASE": case,
            "DRAGNET_SDK_CUTOFF": cutoff, "DRAGNET_SDK_BUNDLE": str(bundle),
            "DRAGNET_SDK_PARENT": parent, "DRAGNET_SDK_BASE": base, "DRAGNET_SDK_QUOTE": quote,
            **{f"DRAGNET_SDK_{i}": str(file) for i, file in enumerate(files, 1)},
        })
        if error is not None:
            rejected(p, error)
        else:
            assert p.returncode == rc and not p.stderr and (rc == 0 or not p.stdout), p
        return p.stdout

    return invoke


def check_fx_projection(sdk, normalized, work):
    schema = validator(ROOT / "contracts/analysis.fx-reference@1.schema.json")
    source = raw("ecb.normalized.json", normalized, work)
    parent = sdk("", [source], case="fx-digest").decode().strip()
    assert parent == FX_PARENT
    quotes = {e.attrib["currency"]: e.attrib["rate"] for e in ElementTree.parse(FIX / "ecb.xml").iter()
              if "currency" in e.attrib}
    projections = {}
    for quote, rate in quotes.items():
        payload = sdk("", [source], case="fx-project", parent=parent, quote=quote)
        doc = json.loads(payload)
        schema.validate(doc)
        assert (doc["base_currency"], doc["quote_currency"], doc["rate"]) == ("EUR", quote, rate)
        assert doc["reference_date"] == "2026-11-16" and doc["parent"] == parent
        assert doc["provider_updated_at"] is None
        assert doc["pricing_input"] is doc["executable"] is False
        expected = raw(quote + ".analysis.json", payload, work)
        assert not sdk("", [source, expected], case="fx-verify", parent=parent, quote=quote)
        corrupt = raw("fx-tampered.json", payload.replace(b'"rate":"', b'"rate":"2'), work)
        sdk("", [source, corrupt], case="fx-verify", parent=parent, quote=quote, rc=1)
        projections[quote] = sdk("", [expected], case="fx-digest").decode().strip()

    for kwargs in (dict(parent="", rc=1), dict(parent="blake3:" + "0" * 64, rc=1),
                   dict(base="USD", rc=2), dict(quote="EUR", rc=2), dict(quote="usd", rc=2),
                   dict(cutoff="2026-11-16T10:10:00Z", rc=3), dict(quote="CAD", rc=4)):
        sdk("", [source], case="fx-project", **({"parent": parent} | kwargs))
    for old, new in (
        (b"quote_currency_per_EUR", b"EUR_per_quote_currency"),
        (b"ecb-fx-reference@1", b"ecb-fx-reference@2"),
        (b"2026-11-16", b"2026-11-17"),
        (b'"currency":"JPY"', b'"currency":"USD"'),
        (b'"174.05"', b'"0.00"'),
        (b'"174.05"', b'"1e2"'),
        (b'"pricing_input":false', b'"pricing_input":true'),
    ):
        invalid = normalized.replace(old, new, 1)
        assert invalid != normalized
        sdk("", [raw("ecb-invalid.json", invalid, work)], case="fx-recomputed", rc=2)
    wrong = raw("ecb-tampered-parent.json", normalized.replace(b"1.09300", b"1.00000"), work)
    sdk("", [wrong], case="fx-project", parent=parent, rc=1)
    assert projections == FX_PROJECTIONS
    print("ecb_fx_projection_ok=true pairs=2 parent=" + parent
          + " projected=" + json.dumps(projections, sort_keys=True))


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
        sdk = sdk_consumer(work, env)
        keys = ("dragnet.frozen_csv@1", "dragnet.crossref@1", "dragnet.public-feed.ecb@1",
                "dragnet.public-feed.eurostat@1")
        policies = [sdk(key, case="identity").strip() for key in keys]
        assert tuple(policies) == POLICY_DIGESTS

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
        cutoff = "2026-11-20T10:00:00Z"
        assert sdk(csv_source, [scenario, offers], cutoff=cutoff) == frozen
        assert sdk(csv_source, [scenario, offers], case="legacy", cutoff=cutoff) == frozen
        for case, rc in (("forged-pin", 2), ("arity", 3), ("presence", 3), ("budget", 4)):
            sdk(csv_source, [scenario, offers], case=case, cutoff=cutoff, rc=rc)
        sdk(csv_source, [scenario, offers], cutoff="2026-11-20T10:00:01Z", rc=5)
        sdk(csv_source, [scenario, offers], cutoff="2026-02-30T10:00:00Z", rc=3)
        sdk(csv_source, mode="recommendation", rc=1)
        sdk("dragnet.public-feed@1", rc=1)
        sdk("dragnet.frozen_csv@2", rc=1)
        first, *rows = offers.read_bytes().splitlines()
        no_eligible = raw("no-eligible.csv", b"\n".join(
            [first, *(row.rsplit(b",", 1)[0] + b",0" for row in rows), b""]), work)
        assert sdk(csv_source, [scenario, no_eligible], case="empty-ndjson", cutoff=cutoff) == b""
        assert routed(exe, csv_source, [scenario, no_eligible], work, env).stdout == (
            inherited(csv_out / "dragnet-frozen-csv", [scenario, no_eligible], work, env).stdout) == b""

        absent_home = work / "absent-pricing-store"
        assert routed(exe, csv_source, [scenario, offers], work,
                      {**env, "FINPRED_HOME": str(absent_home)}).stdout == frozen
        assert not absent_home.exists()

        # Reject incompatible versions and unknown algorithms *before* any
        # unselected data descriptor can be read.
        for source in ("dragnet.frozen_csv@2", "dragnet.unknown@1", "dragnet.public-feed@2",
                       "dragnet.public-feed.ecb@1", "dragnet.public-feed.eurostat@1"):
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
        crossref_cutoff = req.read_text().splitlines()[2].split(",")[4]
        assert sdk("dragnet.crossref@1", inputs, cutoff=crossref_cutoff) == dispatched
        assert sdk("dragnet.crossref@1", inputs, case="legacy", cutoff=crossref_cutoff) == dispatched
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
        unknown_capture = raw("unknown.capture.csv", (
            b"dragnet.feed-capture@1\n"
            b"unknown,offline_snapshot,2026-11-16T10:10:00Z,"
            b"2026-11-16T10:10:01Z,terms-r1,retention-r2\n"), work)
        # Select and admit the capture's concrete provider before touching
        # any body or decode slots, even if those descriptors are closed.
        rejected(routed(exe, "dragnet.public-feed@1", [unknown_capture, None, None, asof],
                        work, env, good=False), b"feed: unknown source")
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
            key = f"dragnet.public-feed.{source}@1"
            trial = "partial" if source == "eurostat" else "success"
            assert sdk(key, [capture, body, handoff], case=trial) == dispatched
            assert sdk(key, [capture, body, handoff], case="legacy") == dispatched
            for i, limit in enumerate((512, 65536, 4096)):
                files = [capture, body, handoff, asof]
                files[i] = raw("oversized-feed-slot", b"x" * (limit + 1), work)
                rejected(routed(exe, "dragnet.public-feed@1", files, work, env, good=False),
                         b"bounded descriptor snapshot")
            wrong_key = "dragnet.public-feed.eurostat@1" if source == "ecb" else "dragnet.public-feed.ecb@1"
            sdk(wrong_key, [capture, body, handoff], error=b"capture provider mismatch")
            if source == "ecb":
                check_fx_projection(sdk, dispatched, work)
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
        assert output_hashes == P0B_SHA256
    print("dragnet_dispatch_ok=true sources=3 parity_fixtures=4 legacy_wrapper_parity=4"
          " denied_modes=6 feed_slot_caps=6 provider_before_payload=true pricing_store_unchanged=true"
          f" network_traced={'4' if trace else '0'}")
    print("dragnet_dispatch_output_sha256=" + json.dumps(output_hashes, sort_keys=True))
    print("dragnet_sdk_ok=true bindings=4 typed_parity=4 empty_ndjson=true policy_digests="
          + ",".join(p.decode("ascii") for p in policies))


if __name__ == "__main__":
    main()
