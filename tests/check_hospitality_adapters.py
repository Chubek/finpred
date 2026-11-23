#!/usr/bin/env python3
"""Compile the hospitality graph adapters independently; pin legacy parity."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from check_yieldcraft_package import CASES, FIX, ROOT

PROFILES = {
    "value-p40": 17100, "balanced-p55": 17800, "premium-p75": 19000,
    "lead-linear": 17100, "lead-quadratic": 17100,
}
INTERMEDIATES = {
    "": b"distribution@1,5,2,0,5\n30000\n33000\n35000\n38000\n40000\nsample@1,5,5,1,10000\n",
    "_multiroom": b"distribution@1,3,0,1,6\n23000\n30000\n35000\nsample@1,3,3,1,12000\n",
}


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    archive = json.loads((FIX / "replay_v1.json").read_bytes())["files"]
    with tempfile.TemporaryDirectory(prefix="finpred-hospitality-adapters-") as temp:
        work = Path(temp)
        exe = work / "consumer"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-build.py",
            ROOT / "tests/hospitality_adapter_consumer/main.on1x", "--backend", "c11",
            "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source",
            "-I", ROOT, "-o", exe,
        ], check=True, cwd=work)
        empty = work / "empty"
        empty.mkdir()

        def invoke(env, *, case="recommend", profile="scenario", diagnostic=None):
            p = subprocess.run([exe], cwd=empty, capture_output=True, timeout=15, env={
                **os.environ, **env, "GRAPH_CASE": case, "GRAPH_PROFILE": profile,
                "FINPRED_HOME": str(empty / "store"),
            })
            assert not list(empty.iterdir()), "adapter wrote to filesystem"
            if diagnostic is not None:
                assert p.returncode > 0 and not p.stdout and diagnostic in p.stderr, p
            else:
                assert p.returncode == 0 and not p.stderr, p
            return p.stdout

        for suffix, v1, v2 in CASES:
            _, sd, od, vd, td, rec, _ = archive[f"runs/{v1}.txt"].strip().split(",")
            env = dict(GRAPH_SCENARIO=FIX / f"scenario{suffix}.csv", GRAPH_OFFERS=FIX / f"offers{suffix}.csv",
                       GRAPH_VALUATION=FIX / "valuation.csv", GRAPH_SD=sd, GRAPH_OD=od, GRAPH_VD=vd, GRAPH_TD=td)
            frozen = archive[f"artifacts/blake3-{rec}.txt"]
            for run_id in (v1, v2):
                assert invoke({**env, "GRAPH_RUN": run_id}) == frozen.replace(v1, run_id).encode("ascii")
            intermediate = invoke(env, case="intermediates")
            assert intermediate == INTERMEDIATES[suffix], (suffix, intermediate)
            if not suffix:
                assert invoke(env, case="request_bounds") == b"cutoff_and_work_ok=true\n"
                for profile, price in PROFILES.items():
                    payload = json.loads(invoke({**env, "GRAPH_RUN": v1}, profile=profile))
                    assert payload["data"]["price_minor"] == price and not payload["data"]["published"], (profile, payload)
                invoke(env, case="bad_sample", diagnostic=b"graph sample: inconsistent diagnostic")
                late = work / "late.csv"
                lines = env["GRAPH_OFFERS"].read_bytes().splitlines(keepends=True)
                lines[1] = lines[1].replace(b"2026-11-20T08:00:00Z", b"2026-11-22T08:00:00Z")
                late.write_bytes(b"".join(lines))
                assert invoke({**env, "GRAPH_OFFERS": late}, case="intermediates") == (
                    b"distribution@1,4,3,0,4\n33000\n35000\n38000\n40000\nsample@1,4,5,0,7000\n"
                )
                few = work / "few.csv"
                few.write_bytes(b"".join(lines[:2]))
                invoke({**env, "GRAPH_OFFERS": few}, diagnostic=b"insufficient_evidence")
                duplicate = work / "duplicate.csv"
                duplicate.write_bytes(env["GRAPH_OFFERS"].read_bytes() + lines[2])
                invoke({**env, "GRAPH_OFFERS": duplicate}, diagnostic=b"duplicate bookable room")
    print("hospitality_adapters_ok=true envelopes=4 profiles=5 intermediates=3 rejected=3 request_bounds=2")


if __name__ == "__main__":
    main()
