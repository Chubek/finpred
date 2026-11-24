#!/usr/bin/env python3
"""Verify Ottomat 6 lowers to the same financial IR/evidence as native On1x."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from check_financial_graph import ROOT, FIX, compile_consumer, frames

STRATEGY = ROOT / "tests/ottomat_financial_consumer/hospitality.ottomat"


def main():
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    compiler_id = "sha256:" + hashlib.sha256(compiler.read_bytes()).hexdigest()
    raw = STRATEGY.read_bytes()
    with tempfile.TemporaryDirectory(prefix="finpred-ottomat-financial-") as tmp:
        work = Path(tmp)
        ott = compile_consumer(work, "ottomat_financial_consumer", grammar=True)
        native = compile_consumer(work, "financial_graph_consumer")
        empty = work / "empty"
        empty.mkdir()
        edited = work / "strategy.ottomat"

        def run(exe, suffix="", *, source=raw, identity=compiler_id, case="native", **extra):
            edited.write_bytes(source)
            env = {**os.environ, "CASE": case, "ROOT": str(ROOT), "STRATEGY": str(edited),
                   "COMPILER_ID": identity, "FINPRED_HOME": str(empty / "store"),
                   "SCENARIO": str(FIX / f"scenario{suffix}.csv"),
                   "OFFERS": str(FIX / f"offers{suffix}.csv"), "VALUATION": str(FIX / "valuation.csv"), **extra}
            r = subprocess.run([exe], env=env, cwd=empty, capture_output=True, timeout=15)
            assert r.returncode == 0 and not r.stderr and not list(empty.iterdir()), r
            return r.stdout

        def accepted(source, suffix=""):
            status, source_id, compiler, lowering, evidence = run(ott, suffix, source=source).split(b"\n", 4)
            assert status == b"ok 0 0" and source_id.startswith(b"blake3:")
            assert compiler == compiler_id.encode() and lowering == b"finpred.ottomat-financial-lowering@1"
            assert evidence == run(native, suffix)
            return source_id

        first = accepted(raw)
        assert accepted(raw, "_multiroom") == first
        reordered = raw.replace(b"scenario=scenario offers=offers", b"offers=offers scenario=scenario")
        alternate = accepted(reordered)
        assert alternate != first
        assert run(ott, case="changed-binding").splitlines()[-1] == b"graph_mismatch"
        approval, bundle = run(ott, case="archive-capture").split(b"\n", 1)
        alternate_approval, alternate_bundle = run(ott, case="archive-capture", source=reordered).split(b"\n", 1)
        _, native_bundle = run(native, case="archive-capture").split(b"\n", 1)
        assert frames(bundle) == [b"ottomat.financial-replay@1", compiler_id.encode(),
                                  b"finpred.ottomat-financial-lowering@1", raw, native_bundle]
        assert frames(alternate_bundle)[3:] == [reordered, native_bundle]
        assert alternate_approval != approval
        path = work / "ottomat.bundle"
        path.write_bytes(bundle)
        args = {"ARCHIVE": str(path), "APPROVED": approval.decode()}
        assert run(ott, case="archive-replay", source=b"not the archived source", **args) == run(native)
        assert run(ott, case="archive-reject", identity="sha256:" + "0" * 64, **args) == b"compiler_identity\n"
        path.write_bytes(alternate_bundle)
        assert run(ott, case="archive-reject", **args) == b"archive_digest\n"

        cases = (
            (raw.replace(b"ottomat 6", b"ottmat 6"), b"syntax"),
            (raw.replace(b"ottomat 6", b"ottomat 5"), b"syntax"),
            (raw.replace(b"effect pure", b"effect action"), b"denied 2 1"),
            (raw.replace(b"effect pure", b"effect read"), b"denied 2 1"),
            (raw.replace(b"effect pure", b"effect record"), b"denied 2 1"),
            (raw.replace(b"input scenario ", b"input\tscenario "), b"syntax 3 6"),
            (raw.replace(b"offers.csv@1", b"offers.csv@2"), b"edge_type 11 1"),
            (raw.replace(b"none none required 2000000", b"minor_per_stay none required 2000000"), b"edge_type 11 1"),
            (raw.replace(b"required 2048", b"missing 2048"), b"port 3 1"),
            (raw.replace(b"import yieldcraft.normalize@1", b"import missing.handler@1"), b"unknown_handler 6 1"),
            (raw.replace(b"import yieldcraft.comparables@1", b"import yieldcraft.normalize@1"), b"duplicate_import 7 1"),
            (raw.replace(b"let normalizer = yieldcraft.normalize@1", b"let normalizer = missing.handler@1"),
             b"undeclared_import 11 1"),
            (raw.replace(b"offers=offers", b"offers..offers"), b"binding 11 1"),
            (raw.replace(b"normalizer.normalized", b"missing.normalized"), b"unknown_reference 12 1"),
            (raw.replace(b"emit recommendation guardrails.recommendation", b"emit missing guardrails.recommendation"),
             b"emit 17 1"),
            (raw + b"x" * 4096, b"size 1 1"),
        )
        for source, expected in cases:
            result = run(ott, source=source)
            assert len(result.splitlines()) == 1 and (result.startswith(expected + b" ") or result == expected + b"\n"), (
                expected, result)
        assert run(ott, identity="unset") == b"compiler_identity 1 1\n"
    print(f"ottomat_financial_ok=true parity=3 rejected={len(cases)+1} binding_mismatch=1 "
          f"source={first.decode()} alternate={alternate.decode()}")


if __name__ == "__main__":
    main()
