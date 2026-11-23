#!/usr/bin/env python3
"""Compile a separate On1x consumer and compare its CSV to the archived fixture."""
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins/poindexter"


def main():
    descriptor = json.loads((PACKAGE / "plugin.json").read_bytes())
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    with tempfile.TemporaryDirectory(prefix="finpred-poindexter-") as tmp:
        project = Path(tmp) / "project"
        shutil.copytree(ROOT / "tests/poindexter_consumer", project)
        shutil.copytree(PACKAGE, project / "vendor/poindexter", ignore=shutil.ignore_patterns("target", "build"))
        out = Path(tmp) / "build"
        subprocess.run([sys.executable, sdk / "on1x/tools/on1x-project.py", "build", project,
                         "--on1xc", compiler, "--mulib-root", sdk, "--output-dir", out], check=True, timeout=90)
        output = subprocess.check_output([out / "consumer"], timeout=10)
    fixture = json.loads((ROOT / "fixtures/replay_v1.json").read_bytes())
    id_, = (key for key, summary in fixture["runs"].items() if "recommendation_minor=17100\n" in summary)
    files = fixture["files"]
    rec = files[f"runs/{id_}.txt"].strip().split(",")[5]
    val, = (p.removeprefix("artifacts/blake3-").removesuffix(".txt")
            for p, text in files.items() if '"kind":"pricing.valuation"' in text)
    contract = json.loads(files[f"artifacts/blake3-{rec}.txt"])
    valuation = json.loads(files[f"artifacts/blake3-{val}.txt"])
    columns = "view source_run source_recommendation source_valuation currency price_basis current_minor recommended_minor change_minor reason published".split()
    hdr, row, hdr2, edge = list(csv.reader(output.decode("ascii").splitlines()))
    assert hdr == hdr2 == columns
    assert row == [descriptor["output"], f"run:{id_}", f"blake3:{rec}", f"blake3:{val}", "EUR", "room_night",
                   str(valuation["data"]["current_cents"]), str(contract["data"]["price_minor"]), "-400",
                   contract["data"]["reason"], "false"]
    assert edge == row[:6] + ["0", "1000000000000", "1000000000000", "target_percentile", "false"]
    limits = descriptor["resource_limits"]
    assert descriptor["kind"] == "View" and descriptor["host_capabilities"] == [] and descriptor["effects"] == ["pure"]
    assert len(hdr) == limits["columns"] and output.endswith(b"\n")
    assert max(len(b"\n".join(lines)) + 1 for lines in (output.splitlines()[:2], output.splitlines()[2:])) <= limits["output_bytes_max"]
    print("poindexter_package_ok=true fixture=17100 change_minor=-400 rejected=9")


if __name__ == "__main__":
    main()
