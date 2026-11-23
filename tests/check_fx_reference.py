#!/usr/bin/env python3
"""Compile the isolated ECB FX research consumer and replay only frozen bytes."""
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/dragnet_feeds/ecb.xml"
GOLDEN_PARENT = "blake3:df0a0fa5f8d8a133aef861cdc3e8e2495110a53315ac5de3885e0df39a51aae5"
GOLDEN_PROJECTIONS = {
    "JPY": "blake3:4956ffbbecb91f0363a4a4662537e260a7e9c8ac4018cbbb7c7b64e0b0ff7a30",
    "USD": "blake3:4a9f364efd1b1bbd10605ea186ba466a04ddef468db336357fb70eb22c20cc51",
}
GOLDEN_CHANGES = {
    "JPY": "blake3:659e89da32f1839f3b0eed06f9cd544bab77798983413bc58279e7b03534d5cc",
    "USD": "blake3:95785472fa85fbaf07c38907f130bf102adfc2adf035953f6fa2e5d4b521e63c",
}
WRONG_PARENT = "blake3:" + "0" * 64


def encoded(doc):
    return (json.dumps(doc, separators=(",", ":")) + "\n").encode("ascii")


def validator(kind):
    schema = json.loads((ROOT / f"contracts/{kind}@1.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def run_tests(work):
    env = os.environ.copy()
    env["TMPDIR"] = str(work)
    env["FINPRED_HOME"] = str(work / "unused-pricing-home")
    mulib = Path(env.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(env.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    exe = work / "fx-consumer"
    subprocess.run(
        [sys.executable, mulib / "on1x/tools/on1x-build.py",
         ROOT / "tests/fx_reference_consumer/main.on1x", "--backend", "c11",
         "--on1xc", compiler, "--mulib-root", mulib, "-I", ROOT / "source", "-o", exe],
        cwd=work, env=env, check=True, timeout=180,
    )

    invoked = 0

    def invoke(mode, rc=0, **overrides):
        nonlocal invoked
        args = {
            "MODE": mode, "BASE": "EUR", "QUOTE": "USD", "START_DATE": "2026-11-16",
            "END_DATE": "2026-11-17", "CUTOFF": "2026-11-17T10:10:02Z",
            "START": start_file, "START_PARENT": start_parent, "END": end_file,
            "END_PARENT": end_parent, "ARTIFACT": work / "change.json",
        } | overrides
        result = subprocess.run(
            [exe], cwd=work, env=env | {f"FX_{k}": str(v) for k, v in args.items()},
            capture_output=True, timeout=10,
        )
        assert result.returncode == rc and not result.stderr, (args, result)
        if rc or mode == "verify":
            assert not result.stdout, result
        invoked += 1
        return result.stdout

    def digest(path):
        return invoke("digest", START=path).decode("ascii").strip()

    def write(name, data):
        path = work / name
        path.write_bytes(data)
        return path

    start_file, end_file = work / "start.json", work / "end.json"
    start_parent = end_parent = ""
    capture = b"dragnet.feed-capture@1\necb,offline_snapshot,2026-11-16T10:10:00Z,2026-11-16T10:10:01Z,terms-r1,retention-r2\n"
    # Independently reconstruct the normalized bytes from the existing frozen
    # XML and the same capture metadata used by dispatcher conformance.
    root = ElementTree.parse(FIXTURE).getroot()
    date, = (e.attrib["time"] for e in root.iter() if "time" in e.attrib)
    quotes = [e.attrib for e in root.iter() if "currency" in e.attrib]
    start_doc = {
        "format": "dragnet.ecb-fx-reference@1",
        "source": "European Central Bank", "source_series": "eurofxref-daily",
        "reference_date": date, "provider_updated_at": None, "base_currency": "EUR",
        "unit": "quote_currency_per_EUR", "status": "complete", "mode": "offline_snapshot",
        "observed_at": "2026-11-16T10:10:00Z", "received_at": "2026-11-16T10:10:00Z",
        "ingested_at": "2026-11-16T10:10:01Z", "as_of": "2026-11-16T10:10:01Z",
        "terms_ref": "terms-r1", "retention_ref": "retention-r2",
        "raw_evidence": digest(FIXTURE), "capture_evidence": digest(write("capture.csv", capture)),
        "raw_bytes": FIXTURE.stat().st_size, "pricing_input": False, "observations": quotes,
    }
    start_file.write_bytes(encoded(start_doc))
    start_parent = digest(start_file)
    assert start_parent == GOLDEN_PARENT
    projection_schema = validator("analysis.fx-reference")
    for quote in quotes:
        payload = invoke("project", QUOTE=quote["currency"], CUTOFF=start_doc["as_of"])
        projected = json.loads(payload)
        projection_schema.validate(projected)
        assert projected["rate"] == quote["rate"]
        assert digest(write("projection.json", payload)) == GOLDEN_PROJECTIONS[quote["currency"]]

    # Synthetic follow-up snapshot, with an intentionally distinct knowledge
    # cutoff even after ingestion; no provider file or network is consulted.
    end_doc = start_doc | {
        "reference_date": "2026-11-17", "observed_at": "2026-11-17T10:10:00Z",
        "received_at": "2026-11-17T10:10:00Z", "ingested_at": "2026-11-17T10:10:01Z",
        "as_of": "2026-11-17T10:10:02Z", "terms_ref": "synthetic", "retention_ref": "synthetic",
        "raw_evidence": WRONG_PARENT, "capture_evidence": WRONG_PARENT, "raw_bytes": 1,
        "observations": [{"currency": "JPY", "rate": "173.95"},
                         {"currency": "USD", "rate": "1.1030"}],
    }
    end_file.write_bytes(encoded(end_doc))
    end_parent = digest(end_file)
    schema = validator("analysis.fx-reference-change")
    outputs = {}
    for currency, a, b in (("USD", "1.09300", "1.1030"), ("JPY", "174.05", "173.95")):
        payload = invoke("compare", QUOTE=currency)
        direction = ["down", "flat", "up"][int(Decimal(b).compare(Decimal(a))) + 1]
        expected = {
            "kind": "analysis.fx-reference-change", "version": 1,
            "unit": "quote_currency_per_base_currency", "pricing_input": False, "executable": False,
            "source_kind": "dragnet.ecb-fx-reference@1", "source_series": "eurofxref-daily",
            "base_currency": "EUR", "quote_currency": currency, "cutoff": end_doc["as_of"],
            "start_date": date, "end_date": end_doc["reference_date"],
            "start_rate": a, "end_rate": b, "start_parent": start_parent, "end_parent": end_parent,
            "direction": direction,
        }
        schema.validate(json.loads(payload))
        assert encoded(expected) == payload
        artifact = write("change.json", payload)
        invoke("verify", QUOTE=currency)
        outputs[currency] = digest(artifact)
        for field, value in (("direction", "flat"), ("start_parent", WRONG_PARENT),
                             ("end_parent", start_parent), ("quote_currency", "CAD")):
            write("change.json", encoded(expected | {field: value}))
            invoke("verify", rc=1, QUOTE=currency)
        assert not schema.is_valid(expected | {"executable": True})
        assert not schema.is_valid(expected | {"unit": "EUR_per_quote_currency"})
    assert outputs == GOLDEN_CHANGES

    # Compare before either leg's ingest, at the end's receipt, and at ingest
    # but before its source-as-of. Equality at source-as-of succeeded above.
    for cutoff in ("2026-11-16T10:10:00Z", end_doc["received_at"], end_doc["ingested_at"]):
        invoke("compare", rc=3, CUTOFF=cutoff)
    for flags in (
        {"START_PARENT": ""}, {"END_PARENT": WRONG_PARENT},
        {"START": end_file}, {"END": start_file},
    ):
        invoke("compare", rc=1, **flags)
    for flags in (
        {"BASE": "USD"}, {"QUOTE": "EUR"}, {"QUOTE": "usd"},
        {"CUTOFF": "2026-11-17T10:10:02+00:00"}, {"START_DATE": "2026-02-30"},
        {"END_DATE": "2026-11-16"}, {"END_DATE": "2026-11-15"}, {"END_DATE": "2026-11-31"},
    ):
        invoke("compare", rc=2, **flags)
    invoke("bad-request", rc=2)
    for flags in (
        {"START_DATE": "2026-11-15"}, {"END_DATE": "2026-11-18"},
        {"END": start_file, "END_PARENT": start_parent},
    ):
        invoke("compare", rc=5, **flags)
    invoke("compare", rc=4, QUOTE="CAD")
    missing_end = write("missing-quote.json", encoded(end_doc | {"observations": end_doc["observations"][:1]}))
    invoke("compare", rc=4, END=missing_end, END_PARENT=digest(missing_end))
    for invalid in (
        end_doc | {"format": "dragnet.ecb-fx-reference@2"},
        end_doc | {"unit": "EUR_per_quote_currency"},
        end_doc | {"base_currency": "USD"},
        end_doc | {"pricing_input": True},
        end_doc | {"status": "partial"},
        end_doc | {"reference_date": "2026-11-18"},
        end_doc | {"reference_date": "2026-11-09"},  # older than the capture's seven-day window
        end_doc | {"ingested_at": "2026-11-17T10:09:59Z"},
        end_doc | {"as_of": end_doc["received_at"]},
        end_doc | {"observations": end_doc["observations"] + [{"currency": "USD", "rate": "2"}]},
        end_doc | {"observations": end_doc["observations"] + [{"currency": "CAD", "rate": "0.00"}]},
        end_doc | {"observations": end_doc["observations"] + [{"currency": "CAD", "rate": "1e2"}]},
        end_doc | {"observations": end_doc["observations"] + [{"currency": "CAD", "rate": "9" * 25}]},
    ):
        bad = write("invalid.json", encoded(invalid))
        invoke("compare", rc=2, END=bad, END_PARENT=digest(bad))
    for invalid_bytes in (b"x" * 8193, encoded(end_doc) + b"\n"):
        bad = write("invalid.json", invalid_bytes)
        invoke("compare", rc=2, END=bad, END_PARENT=digest(bad))

    # Bounds and formatting edge cases compared against independent exact Decimal values.
    for a, b in (("1.09300", "1.093"), ("10", "9.999999"), ("9.999999", "10"),
                 ("999999999999999999999998", "999999999999999999999999"),
                 ("0.0000000000000000000001", "0.0000000000000000000002"), ("1", "1.0")):
        def fixed(doc, rate):
            return encoded(doc | {"observations": [{"currency": "USD", "rate": rate}]})

        x = write("decimal-start.json", fixed(start_doc, a))
        y = write("decimal-end.json", fixed(end_doc, b))
        output = invoke("compare", START=x, START_PARENT=digest(x), END=y, END_PARENT=digest(y))
        result = json.loads(output)
        schema.validate(result)
        assert (result["start_rate"], result["end_rate"]) == (a, b)
        assert result["direction"] == {-1: "down", 0: "flat", 1: "up"}[Decimal(b).compare(Decimal(a))]

    assert not Path(env["FINPRED_HOME"]).exists()
    print(f"fx_reference_ok=true calls={invoked} "
          f"compiler_sha256={sha256(compiler.read_bytes()).hexdigest()} "
          f"parents={start_parent},{end_parent} projections={json.dumps(GOLDEN_PROJECTIONS, sort_keys=True)} "
          f"changes={json.dumps(outputs, sort_keys=True)}")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="fx-reference-") as temp:
        run_tests(Path(temp))
