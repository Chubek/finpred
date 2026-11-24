#!/usr/bin/env python3
"""Compile and exercise the additive financial-graph consumer independently."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"
REJECTIONS = {
    "shape": "graph_shape", "duplicate": "duplicate_id", "kind": "edge_type",
    "unit": "edge_type", "major": "edge_type", "denied": "denied",
    "unknown": "unknown_handler", "cycle": "cycle", "ref": "unknown_reference",
    "disabled": "unknown_handler", "budget": "budget", "cutoff": "handler_failure",
    "wrong-parent": "replay_mismatch",
}
PARENTS = {
    "normalizer": ["scenario", "offers"],
    "comparables": ["scenario", "normalizer"],
    "diagnostic": ["scenario", "comparables"],
    "decision": ["scenario", "valuation", "comparables", "diagnostic"],
    "guardrails": ["scenario", "valuation", "decision"],
}
GRAPH_ID = "blake3:d7f83ea49b2610bed9b5df102436ac43df0f9510aeca78806ceb756c5a0ebb03"
ROOT_IDS = {
    "": "blake3:cb09c71eef28de3e81cb110a0a17a0a3fb9cce49395fb12e9e383abd41bd82d8",
    "_multiroom": "blake3:34ed09d793bfc3b19a59c489ee1b2b5e689186efe47af6c61bc2d80cbc4be07b",
}


def frames(raw):
    """Independent reader for the graph's length-delimited evidence fields."""
    result = []
    while raw:
        length, raw = raw.split(b":", 1)
        n = int(length)
        assert 0 <= n <= len(raw) and length == str(n).encode("ascii")
        field, raw = raw[:n], raw[n:]
        result.append(field)
    return result


def compile_consumer(work, name, *, grammar=False):
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    exe = work / name
    args = []
    if grammar:
        from ottomat_build import flags
        args = flags(compiler, sdk, work)
    subprocess.run([
        sys.executable, sdk / "on1x/tools/on1x-build.py",
        ROOT / f"tests/{name}/main.on1x", "--backend", "c11", "--on1xc", compiler,
        "--mulib-root", sdk, *args, "-I", ROOT / "source", "-I", ROOT, "-o", exe,
    ], check=True, cwd=work)
    return exe


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-financial-graph-") as temp:
        work = Path(temp)
        exe = compile_consumer(work, "financial_graph_consumer")
        empty = work / "empty"
        empty.mkdir()
        def run(case, suffix=""):
            p = subprocess.run([exe], cwd=empty, capture_output=True, timeout=15,
                               env={**os.environ, "FINPRED_HOME": str(empty / "store"),
                                    "CASE": case, "ROOT": str(ROOT),
                                    "SCENARIO": str(FIX / f"scenario{suffix}.csv"),
                                    "OFFERS": str(FIX / f"offers{suffix}.csv"),
                                    "VALUATION": str(FIX / "valuation.csv")})
            assert p.returncode == 0 and not p.stderr and not list(empty.iterdir()), p
            return p.stdout

        for case, expected in REJECTIONS.items():
            assert run(case) == expected.encode("ascii") + b"\n", case
        for suffix, price, reason in (
            ("", b"17100", b"lower_percentile_shortcut"),
            ("_multiroom", b"16000", b"guardrail_adjustment"),
        ):
            native = run("native", suffix)
            assert native == run("reordered", suffix) == run("replay", suffix)
            graph_digest, root = verify_evidence(native, price, reason)
            assert (graph_digest, root) == (GRAPH_ID, ROOT_IDS[suffix])
            print(f"financial_graph_fixture={suffix or 'default'} graph={graph_digest} root={root}")
        memo = run("memo")
        verify_evidence(memo, b"17100", b"lower_percentile_shortcut", memo=True)
    print(f"financial_graph_ok=true fixtures=2 rejections={len(REJECTIONS)} replay=2 memo=1")


def verify_evidence(raw, expected_price, expected_reason, *, memo=False):
    status, graph, invocations, recommendation, evidence = raw.split(b"\n", 4)
    assert status == b"ok" and invocations == b"5"
    prices = recommendation.split(b",")
    assert prices[6] == expected_price and prices[11] == expected_reason
    trace, *items = frames(evidence)
    names = [b"offers", b"scenario", b"valuation", b"normalizer", b"comparables", b"diagnostic",
             b"decision", b"guardrails"]
    if memo:
        names.insert(7, b"extra")
    assert items[::3] == names
    assert [line.split(b"=")[0] for line in trace.splitlines()] == names[3:]
    known = {}
    for name, digest, data in zip(items[::3], items[1::3], items[2::3], strict=True):
        fields = frames(data)
        assert fields[0] == b"automat.financial-artifact@1" and fields[2] == name
        assert fields[10] == b"2026-11-20T10:00:00Z"
        assert fields[-2] == b"1"
        if fields[1] == b"node":
            identity = frames(fields[-4])
            assert identity[0] == graph and identity[-2].startswith(b"blake3:")
            parents = frames(fields[-3])
            expected = PARENTS["diagnostic" if name == b"extra" else name.decode("ascii")]
            assert int(parents[0]) == len(expected)
            for (_, producer, port, parent), id_ in zip(
                zip(parents[1::4], parents[2::4], parents[3::4], parents[4::4], strict=True),
                expected, strict=True,
            ):
                actual = producer or port
                assert actual == id_.encode("ascii") and parent == known[actual]
        known[name] = digest
    return graph.decode("ascii"), known[b"guardrails"].decode("ascii")


if __name__ == "__main__":
    main()
