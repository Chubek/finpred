#!/usr/bin/env python3
"""Validate grants against saved fixtures without contacting the providers."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from check_dragnet_dispatch import FIX, PKG, ROOT, inherited, raw, rejected, routed, run


def main():
    with tempfile.TemporaryDirectory(prefix="dragnet-offline-evidence-") as temp:
        work = Path(temp)
        env = {**os.environ, "DRAGNET_BUILD_LOOPBACK_FIXTURE": "0"}
        mulib = Path(env.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
        compiler = Path(env.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
        helper = work / "digest"
        run(sys.executable, mulib / "on1x/tools/on1x-build.py", FIX / "file_digest.on1x",
            "--backend", "c11", "--on1xc", compiler, "--mulib-root", mulib, "-o", helper,
            env=env, cwd=work, timeout=180)

        def digest(path):
            return run(helper, cwd=work, env={**env, "DRAGNET_TEST_HASH_FILE": str(path)}).stdout.decode()

        legacy_out = work / "legacy"
        evidence_out = work / "evidence"
        run(PKG / "build-dispatch.sh", legacy_out, env=env, timeout=180)
        run(PKG / "build-dispatch.sh", evidence_out, "--offline-evidence", env=env, timeout=180)
        feeds = work / "feeds"
        run(PKG / "build-feeds.sh", feeds, env=env, timeout=180)
        exe = evidence_out / "dragnet-offline-evidence"
        legacy = legacy_out / "dragnet-source-dispatch"
        schemas = PKG / "contracts"
        schema = json.loads((schemas / "dragnet.offline-feed-evidence@1.schema.json").read_text())
        feed = schemas / "dragnet.public-feed@1.schema.json"
        registry = Registry().with_resource("https://finpred.local/dragnet/" + feed.name,
                                            Resource.from_contents(json.loads(feed.read_text())))
        Draft202012Validator.check_schema(schema)
        validate = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        cutoff = "2026-11-16T10:10:01Z"
        valid_from = "2026-11-16T10:20:00Z"
        valid_until = "2026-11-16T10:30:00Z"
        asof = raw("as-of", (cutoff + "\n").encode(), work)
        check = raw("clock", (valid_from + "\n").encode(), work)
        trace = work / "network.trace" if shutil.which("strace") else None
        for provider, fixture in (("ecb", "ecb.xml"), ("eurostat", "eurostat.json")):
            body = FIX / fixture
            capture = raw("capture", (f"dragnet.feed-capture@1\n{provider},offline_snapshot,"
                                      f"2026-11-16T10:10:00Z,{cutoff},terms-r1,retention-r2\n").encode(), work)
            decode = raw("decode", run(feeds / "dragnet-feed-decode", provider, input=body.read_bytes(),
                                       env=env).stdout, work)
            capture_id, body_id, decode_id = map(digest, (capture, body, decode))
            fields = [provider, "offline_analysis", cutoff, valid_from, valid_until,
                      capture_id, body_id, decode_id, "terms-r1", "retention-r2"]

            def grant(*, change=None, header="dragnet.feed-permission@1", suffix="\n"):
                cols = fields.copy()
                if change:
                    i, value = change
                    cols[i] = value
                return raw("grant", (header + "\n" + ",".join(cols) + suffix).encode(), work)

            policy = grant()
            accepted = inherited(exe, [policy, check, capture, body, decode], work, env, trace=trace)
            doc = json.loads(accepted.stdout)
            validate.validate(doc)
            assert doc["permission_digest"] == digest(policy) and doc["decode_digest"] == decode_id
            assert doc["checked_at"] == valid_from and doc["external_execution"] is False
            expected = routed(legacy, "dragnet.public-feed@1", [capture, body, decode, asof],
                              work, env).stdout
            assert accepted.stdout.partition(b',"snapshot":')[2] == expected[:-1] + b"}\n"

            # Closed payload slots prove the gate doesn't need their contents to deny.
            def deny(error, *fds):
                rejected(inherited(exe, fds, work, env, good=False), error)

            for kw, error in (
                ({"header": "dragnet.feed-permission@2"}, b"invalid grant framing"),
                ({"suffix": "\n\n"}, b"invalid grant framing"),
                ({"suffix": ",extra\n"}, b"unexpected column count"),
                ({"change": (0, "unregistered")}, b"unknown provider"),
                ({"change": (1, "execution")}, b"purpose denied"),
                ({"change": (2, "2026-11-16T10:31:00Z")}, b"grant not current"),
                ({"change": (5, "blake3:" + "A" * 64)}, b"invalid digest"),
                ({"change": (8, "terms/r1")}, b"invalid policy reference"),
            ):
                deny(error, grant(**kw), check)

            for when in ("2026-11-16T10:19:59Z", valid_until):
                bad_clock = raw("bad-clock", (when + "\n").encode(), work)
                deny(b"grant not current", grant(), bad_clock)
            deny(b"expected bounded descriptor", None, check)
            deny(b"expected bounded descriptor", grant())

            for index, error in ((0, b"capture scope mismatch"), (2, b"capture outside cutoff"),
                                 (5, b"capture digest mismatch"), (8, b"capture scope mismatch"),
                                 (9, b"capture scope mismatch")):
                value = {0: "ecb" if provider == "eurostat" else "eurostat",
                         2: "2026-11-16T10:10:00Z", 5: "blake3:" + "0" * 64,
                         8: "other-terms", 9: "other-retention"}[index]
                deny(error, grant(change=(index, value)), check, capture)
            public = raw("public-capture", capture.read_bytes().replace(b"offline_snapshot", b"public_https"), work)
            deny(b"capture scope mismatch", grant(change=(5, digest(public))), check, public)
            tampered = raw("tampered-body", body.read_bytes() + b"\n", work)
            deny(b"body digest mismatch", grant(), check, capture, tampered)
            tampered = raw("tampered-decode", decode.read_bytes() + b"\n", work)
            deny(b"decode digest mismatch", grant(), check, capture, body, tampered)
    print("dragnet_offline_evidence_ok=true providers=2 legacy_byte_parity=2 external_execution=false"
          f" network_traced={2 if trace else 0}")


if __name__ == "__main__":
    main()
