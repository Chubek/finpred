#!/usr/bin/env python3
"""Independent C11-lowered SDK consumer and Eurostat analysis projection."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-11-16T10:10:01Z"
PARENT = "blake3:1218288306d1faf0fcc4566bb31ca9afa7f5b6dd9dec328ac5c49d2b66181fd6"
PROJECTED = "blake3:ca37bd4541c67f9a644b9d57d7c4c8359c4950c0fdb009aa3f2fdd2e20e20ff5"
SDK_CASES = {
    "echo": 0, "second": 0, "connects": 0, "read": 1, "record": 1, "action": 1,
    "disabled": 1, "unknown": 1, "duplicate": 1, "bad-role": 1, "wrong-mode": 1,
    "wrong-pin": 2, "wrong-abi": 2, "wrong-policy": 2, "bad-state": 3,
    "bad-cutoff": 3, "bad-arity": 3, "big-value": 3, "bad-work": 4, "over-work": 4,
    "wrong-output": 6,
}


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    schema = json.loads((ROOT / "contracts/analysis.guest-nights-monthly@1.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    with tempfile.TemporaryDirectory(prefix="finpred-sdk-data1-") as tmp:
        work = Path(tmp)
        child_env = os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"}

        def build(consumer, includes=()):
            binary = work / consumer
            cmd = [
                sys.executable, mulib / "on1x/tools/on1x-build.py",
                ROOT / f"tests/{consumer}/main.on1x", "--backend", "c11", "--on1xc",
                compiler, "--mulib-root", mulib, "-I", ROOT / "source", "-o", binary,
            ]
            for include in includes:
                cmd.extend(("-I", include))
            subprocess.run(cmd, cwd=work, env=child_env, check=True, timeout=90)
            return binary

        def run(exe, case, *, rc=0, **payload):
            proc = subprocess.run([exe], env=child_env | {"CASE": case} | payload,
                                  cwd=work, capture_output=True, timeout=5)
            assert proc.returncode == rc and not proc.stderr, (
                exe.name, case, rc, proc.returncode, proc.stdout, proc.stderr)
            if rc or exe == sdk:
                assert not proc.stdout, (case, proc.stdout)
            return proc.stdout.decode()

        sdk = build("sdk_callable_consumer")
        for case, expected in SDK_CASES.items():
            run(sdk, case, rc=expected)

        data = build("data_guest_nights_consumer", [ROOT / "plugins/dragnet/source"])
        raw = (ROOT / "tests/dragnet_feeds/eurostat.json").read_text()
        source = run(data, "fixture", RAW=raw)
        assert run(data, "digest", SNAPSHOT=source).strip() == PARENT

        def project(s=source, *, parent=PARENT, cutoff=CUTOFF, rc=0, recompute=False):
            return run(data, "changed-parent" if recompute else "project", rc=rc,
                       SNAPSHOT=s, PARENT=parent, CUTOFF=cutoff)

        result = project()
        assert project() == result
        assert run(data, "digest", SNAPSHOT=result).strip() == PROJECTED
        proof = {"SNAPSHOT": source, "PARENT": PARENT, "CUTOFF": CUTOFF, "PROJECTED": result}
        assert run(data, "verify", **proof) == ""
        assert run(data, "verify", rc=1, **(proof | {"PROJECTED": result.replace("515000001", "0")})) == ""
        doc = json.loads(result)
        validator.validate(doc)
        assert doc["state"] == "partial" and doc["parent"] == PARENT
        assert doc["currency"] is None and doc["pricing_input"] is False
        raw_doc = json.loads(raw)
        original = sorted(raw_doc["dimension"]["time"]["category"]["index"].items())
        expected = [
            {"period": period, "state": "available" if str(idx) in raw_doc["value"] else "unknown",
             "nights": raw_doc["value"].get(str(idx)), "provider_flag": raw_doc["status"].get(str(idx))}
            for period, idx in original
        ]
        assert doc["observations"] == expected
        assert datetime.fromisoformat(doc["provider_updated_at"]) < datetime.fromisoformat(doc["received_at"])
        assert doc["observed_at"] == doc["received_at"] < doc["ingested_at"] == doc["source_as_of"] == doc["cutoff"]
        assert json.loads(project(cutoff="2026-11-17T00:00:00Z"))["cutoff"] == "2026-11-17T00:00:00Z"

        complete = source.replace('"status":"partial"', '"status":"complete"').replace(
            '"nights":null', '"nights":0')
        doc = json.loads(project(complete, recompute=True))
        validator.validate(doc)
        assert doc["state"] == "available" and doc["observations"][-1]["nights"] == 0
        sparse = complete.replace("2026-07", "2026-06")
        doc = json.loads(project(sparse, recompute=True))
        validator.validate(doc)
        assert doc["state"] == "partial" and doc["observations"][0]["period"] == "2026-06"

        project(parent="", rc=1)
        project(s="", rc=1)
        project(parent="blake3:" + "0" * 64, rc=1)
        project(source.replace("515000001", "515000002"), rc=1)
        project(cutoff="2026-11-16T10:10:00Z", rc=3)
        project(source.replace(f'"as_of":"{CUTOFF}"', '"as_of":"2026-11-17T00:00:00Z"'),
                rc=3, recompute=True)
        project(cutoff="2026-02-29T00:00:00Z", rc=2)
        malformed = [
            source.replace("accommodation-nights@1", "accommodation-nights@2"),
            source.replace("guest_nights", "EUR"),
            source.replace("EU27_2020", "AT"),
            source.replace("2026-09", "2026-08"),
            source.replace("2026-09", "2026-05"),
            source.replace("2026-09", "2026-11"),
            source.replace("2026-09", "2026-13"),
            source.replace("+0100", "+0160"),
            source.replace("+0100", "+0000"),
            source.replace('"status":"partial"', '"status":"complete"'),
            source.replace('"pricing_input":false', '"pricing_input":true'),
            source.replace("515000001", "-1"),
            source.replace("515000001", "001"),
            source.replace('"p"', '"un\\u006bnown"'),
            source.replace('"period":"2026-07"', '"period":"2026-07","period":"2026-07"'),
            source[:-1],
            source + "x" * 4096,
        ]
        assert len(set(malformed + [source])) == len(malformed) + 1
        for modified in malformed:
            project(modified, rc=2, recompute=True)
        print(f"sdk_callable_ok=true cases={len(SDK_CASES)} packages=2")
        print(f"guest_nights_projection_ok=true rejection_cases={len(malformed)+7} parent={PARENT} projected={PROJECTED}")


if __name__ == "__main__":
    main()
