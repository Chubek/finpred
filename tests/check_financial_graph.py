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
    "empty-available": "invalid_output", "empty-root": "input", "empty-edge": "invalid_request",
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
# Captured from the named-edge executor before slot compilation.
ARCHIVE_IDS = {
    "": b"blake3:2747af62e0ce067c049a293ec50fa616131696a4b083a9657836fd056f5073bb",
    "_multiroom": b"blake3:e8b3814afdf1c02a2195f56dcdc9834789105fa511d9f883da129287af8401aa",
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


def encode_frames(fields):
    return b"".join(str(len(field)).encode("ascii") + b":" + field for field in fields)


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
        schedule = compile_consumer(work, "financial_schedule_consumer")
        empty = work / "empty"
        empty.mkdir()
        scheduled = subprocess.run([schedule], cwd=empty, capture_output=True, timeout=15)
        assert (scheduled.returncode, scheduled.stdout, scheduled.stderr) == (0, b"financial_schedule_ok=true\n", b""), scheduled
        assert not list(empty.iterdir()), scheduled

        def run(case, suffix="", **extra):
            p = subprocess.run([exe], cwd=empty, capture_output=True, timeout=15,
                               env={**os.environ, "FINPRED_HOME": str(empty / "store"),
                                    "CASE": case, "ROOT": str(ROOT),
                                    "SCENARIO": str(FIX / f"scenario{suffix}.csv"),
                                    "OFFERS": str(FIX / f"offers{suffix}.csv"),
                                     "VALUATION": str(FIX / "valuation.csv"), **extra})
            assert p.returncode == 0 and not p.stderr and not list(empty.iterdir()), p
            return p.stdout

        for case, expected in REJECTIONS.items():
            assert run(case) == expected.encode("ascii") + b"\n", case
        for case, expected in {
            "compose-ok": b"ok\njoined\n", "compose-type": b"edge_type\n",
            "compose-budget": b"budget\n", "compose-duplicate": b"link_reference\n",
            "compose-reference": b"link_reference\n",
        }.items():
            assert run(case) == expected, case
        for suffix, price, reason in (
            ("", b"17100", b"lower_percentile_shortcut"),
            ("_multiroom", b"16000", b"guardrail_adjustment"),
        ):
            native = run("native", suffix)
            assert native == run("reordered", suffix) == run("replay", suffix)
            graph_digest, root = verify_evidence(native, price, reason)
            assert (graph_digest, root) == (GRAPH_ID, ROOT_IDS[suffix])
            captured = run("archive-capture", suffix)
            assert captured == run("archive-reordered", suffix)
            digest, raw = captured.split(b"\n", 1)
            assert digest == ARCHIVE_IDS[suffix]
            items = frames(raw)
            assert items[:4] == [b"automat.financial-replay@1", b"recommendation", graph_digest.encode(),
                                 b"2026-11-20T10:00:00Z"]
            assert items[4].startswith(b"blake3:") and items[5] == b"3"
            assert items[6:15:3] == [b"offers", b"scenario", b"valuation"]
            assert items[7:15:3] == [b"1", b"1", b"1"]
            assert items[8:15:3] == [(FIX / f"offers{suffix}.csv").read_bytes(),
                                     (FIX / f"scenario{suffix}.csv").read_bytes(),
                                     (FIX / "valuation.csv").read_bytes()]
            archived = work / "replay.bundle"
            archived.write_bytes(raw)
            archive_args = {"ARCHIVE": str(archived), "APPROVED": digest.decode()}
            assert run("archive-replay", **archive_args) == native
            assert run("archive-mode", **archive_args) == b"archive_format\n"
            assert run("archive-binding", **archive_args) == b"replay_mismatch\n"
            changed_roots = items.copy()
            changed_roots[8] += b"\n"
            reversed_evidence = items[:16] + items[19:22] + items[16:19] + items[22:]
            for incompatible in (changed_roots, reversed_evidence):
                archived.write_bytes(encode_frames(incompatible))
                assert run("archive-inventory", **archive_args) == b"replay_mismatch\n"
            for malformed in (raw + b"0:", raw[:-1], b"0" + raw, raw[:-1] + b"x"):
                archived.write_bytes(malformed)
                assert run("archive-digest", **archive_args) == b"archive_digest\n"
                assert run("archive-format", **archive_args) == b"archive_format\n"
            print(f"financial_graph_fixture={suffix or 'default'} graph={graph_digest} root={root}")
        memo = run("memo")
        verify_evidence(memo, b"17100", b"lower_percentile_shortcut", memo=True)
        status, _, invocations, evidence = run("empty-unknown").split(b"\n", 3)
        assert status == b"ok" and invocations == b"1"
        _, *items = frames(evidence)
        assert items[::3] == [b"input", b"first", b"second"]
        assert [frames(artifact)[-2:] for artifact in items[5::3]] == [[b"4", b""], [b"4", b""]]
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
