#!/usr/bin/env python3
"""Compare the compiled SDK check command's reports to the native C policy."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from check_sdk_packages import LIMITS, cases


ROOT = Path(__file__).resolve().parents[1]
TEXT = ("VERSION", "KIND", "OUTPUT", "MODE", "EFFECT")
LISTS = ("INPUTS", "REQUESTED", "DEPS", "GRANTS")
KEYS = ("PACKAGE", "SDK", *TEXT, *LISTS, *LIMITS)
HEADER = ",".join((
    "package", "sdk_version", "package_version", "kind", "output", "mode", "effect",
    "inputs", "requested", "dependencies", "grants", *LIMITS,
))
SCHEMA = "finpred-sdk-diagnostic@1"


def request(case):
    fields = [case[key].replace(",", ";") if key in LISTS else case[key] for key in KEYS]
    return f'finpred-sdk-check@1\n{HEADER}\n{",".join(fields)}\n'.encode("ascii")


def want(status, reason, subject, field, index=None):
    return dict(schema=SCHEMA, status=status, reason=reason, subject=subject, field=field, index=index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    exe = parser.parse_args().executable.resolve(strict=True)
    sys.path.insert(0, str(ROOT / "bindings/python"))
    from finpred_sdk import Host, Limits, SDK, Use

    with tempfile.TemporaryDirectory(prefix="finpred-sdk-cli-") as tmp:
        work = Path(tmp)
        build = work / "build"
        subprocess.run(["cmake", "-S", ROOT / "source/sdk", "-B", build,
                        "-DBUILD_SHARED_LIBS=ON"], cwd=work, check=True)
        subprocess.run(["cmake", "--build", build], cwd=work, check=True)
        sdk = SDK(build / "libfinpred_sdk.so")
        home = work / "must-not-exist"
        path = work / "policy request.csv"

        def run(payload, report, input_path=path):
            if payload is not None:
                path.write_bytes(payload)
            p = subprocess.run([exe], cwd=work, capture_output=True, timeout=5, env={
                "FINPRED_MODE": "sdk-check", "FINPRED_SDK_REQUEST": str(input_path),
                "FINPRED_HOME": str(home), "FINPRED_ENGINE": "not-an-engine",
                "FINPRED_STRATEGY": str(home / "not-a-strategy"),
            })
            assert p.returncode == report["status"] and not p.stderr, (report, p)
            assert p.stdout.count(b"\n") == 1 and json.loads(p.stdout) == report, (report, p.stdout)
            assert not home.exists() and not (work / ".finpred").exists()
            if payload is not None:
                assert path.read_bytes() == payload

        def parity(case, legacy_status):
            def names(key):
                return tuple(case[key].split(",")) if case[key] else ()

            limits = Limits(**{key: int(case[key]) for key in LIMITS})
            use = Use(int(case["SDK"]), *(case[key] for key in TEXT), names("INPUTS"), names("REQUESTED"))
            host = Host(limits, names("DEPS"), names("GRANTS"))
            if any(len(names(key)) > 16 for key in LISTS):
                # Python intentionally rejects oversized representations before calling C.
                report = want(1, "invalid_value", "host", "dependencies")
            else:
                d = sdk.check_diagnostic(case["PACKAGE"], use, host)
                report = want(d.status, d.reason.name.lower(), d.subject.name.lower(), d.field.name.lower(), d.index)
            assert report["status"] == legacy_status, (case, report)
            run(request(case), report)

        count = 0
        for pkg in ("dragnet", "yieldcraft", "poindexter"):
            manifest = json.loads((ROOT / "plugins" / pkg / "plugin.json").read_bytes())
            for case, status in cases(manifest):
                parity(case, status)
                count += 1
            base = next(cases(manifest))[0]
            parity(base | {"SDK": "4294967295"}, 2)
            parity(base | {key: "4294967295" for key in LIMITS}, 0)

        ok = want(0, "none", "none", "none")
        raw = request(base)
        run(raw.replace(b"\n", b"\r\n"), ok)
        run(raw.rstrip(b"\n"), ok)
        p = subprocess.run([ROOT / "bin/finpred", "sdk-check", path.name],
                           cwd=work, capture_output=True, timeout=5, env={
                               "PATH": os.defpath, "FINPRED_EXE": str(exe),
                               "FINPRED_HOME": str(home),
                           })
        assert p.returncode == 0 and not p.stderr and json.loads(p.stdout) == ok, p
        assert not home.exists() and path.read_bytes() == raw.rstrip(b"\n")
        invalid = want(1, "invalid_value", "use", "none")
        for bad in (b"", b" " * 16385, raw + b"\n", raw[:-1] + b",extra\n",
                    raw.replace(b"check@1", b"check@0", 1), raw.replace(b"package", b"name", 1),
                    raw.replace(b"Strategy", b'"Strategy"').replace(b"View", b'"View"'),
                    raw.replace(b"\n", b"\r", 1), raw[:-1] + b"\x00\n"):
            run(bad, invalid)
        run(None, invalid, work / "missing")
        run(None, invalid, work)
        run(request(base | {"SDK": "01"}), want(1, "invalid_value", "use", "sdk_version"))
        run(request(base | {"output_bytes_max": "4294967296"}),
            want(1, "invalid_value", "host", "output_bytes_max"))
    print(f"sdk_diagnostic_cli_ok=true package_vectors={count} boundary_and_wire_checks=passed")


if __name__ == "__main__":
    main()
