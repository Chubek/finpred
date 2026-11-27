#!/usr/bin/env python3
"""Verify Ottomat 7 composition with an independently constructed native graph."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

from check_financial_graph import ROOT, compile_consumer, frames

HEADER = b"ottomat 7\neffect pure\n"
FIRST = b"""fragment prepare
input raw test.value@1 none none required 64
import test.pass@1
let normalizer = test.pass@1 value=raw
output normalized test.value@1 none none required 32
emit normalized normalizer.value
end
"""
SECOND = b"""fragment blend
input inbound test.value@1 none none required 32
input extra test.value@1 none none required 32
import test.join@1
let mixer = test.join@1 a=inbound b=extra
output mixed test.value@1 none none required 32
emit mixed mixer.value
wire inbound normalized
end
"""
THIRD = b"""fragment deliver
input before test.value@1 none none required 32
input original test.value@1 none none required 32
import test.join@1
let finish = test.join@1 a=before b=original
output final test.value@1 none none required 32
emit final finish.value
wire before mixed
wire original normalized
end
"""
SOURCE = HEADER + FIRST + SECOND + THIRD
OK = [b"ok", b"", b"", b"0", b"0", b"0", b"0"]


def main():
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    identity = "sha256:" + hashlib.sha256(compiler.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="finpred-ottomat-composition-") as temp:
        work = Path(temp)
        exe = compile_consumer(work, "ottomat_composition_consumer", grammar=True)
        path = work / "composition.ottomat"
        empty = work / "empty"
        empty.mkdir()

        def run(source=SOURCE, task="", compiler_id=identity):
            path.write_bytes(source)
            env = {**os.environ, "CASE": task, "COMPILER_ID": compiler_id,
                   "STRATEGY": str(path), "FINPRED_HOME": str(empty / "store")}
            r = subprocess.run([exe], env=env, cwd=empty, capture_output=True, timeout=15)
            assert r.returncode == 0 and not r.stderr and not list(empty.iterdir()), r
            return frames(r.stdout)

        def accepted(source, task=""):
            result = run(source, task)
            assert result[:8] == OK + [source], result[:8]
            assert result[8].startswith(b"blake3:") and result[9].startswith(b"blake3:")
            assert result[10:12] == [identity.encode(), b"finpred.ottomat-financial-composition@1"]
            n = int(result[12])
            assert n == source.count(b"\n")
            spans = result[13:13 + n * 5]
            declared = b""
            ranges = []
            for fragment, verb, name, start, end in zip(
                spans[::5], spans[1::5], spans[2::5], spans[3::5], spans[4::5], strict=True
            ):
                line = source[int(start):int(end)]
                words = line.split()
                assert words[0] == (b"ottomat" if verb == b"header" else verb)
                assert name == (words[1] if len(words) > 1 else b"")
                if verb == b"fragment":
                    declared = name
                assert fragment == declared
                ranges.append(line)
            assert ranges == source.splitlines()
            pinned = result[13 + len(spans):]
            expected = [b"normalizer", b"test.pass@1", b"mixer", b"test.join@1", b"finish", b"test.join@1"]
            if task == "max-fragments":
                expected += [b"more", b"test.join@1"]
            assert pinned[:1 + len(expected)] == [str(len(expected) // 2).encode(), *expected]
            return result[8], result[9], pinned[1 + len(expected):]

        source_id, graph_id, evidence = accepted(SOURCE)
        assert evidence == run(task="native")
        assert evidence[:3] == [b"ok", graph_id, b"3"]
        assert evidence[4] == b"3" and evidence[5:14:3] == [b"final", b"mixed", b"normalized"]
        assert evidence[7:14:3] == [b"[one]+two+[one]", b"[one]+two", b"[one]"]
        alternate = SOURCE.replace(b"a=inbound b=extra", b"b=extra a=inbound")
        alternate_id, alternate_graph, alternate_evidence = accepted(alternate)
        assert alternate_id != source_id and alternate_graph == graph_id and alternate_evidence == evidence
        assert accepted(SOURCE, "changed")[2] == [b"graph_mismatch"]
        assert run(task="legacy") == [b"syntax"]

        def reject(source, status, fragment=b"", subject=b"", mark=None, *, task="", compiler_id=identity):
            actual = run(source, task, compiler_id)
            assert len(actual) == 7 and actual[:3] == [status, fragment, subject], actual
            row, col, start, end = map(int, actual[3:])
            assert 0 <= start <= end <= len(source), actual
            assert row == source[:start].count(b"\n") + 1
            assert col == start - source[:start].rfind(b"\n")
            if mark is not None:
                assert source[start:end] == mark, (actual, source[start:end], mark)
            return start, end

        reject(SOURCE.replace(b"ottomat 7", b"ottomat 6"), b"syntax", mark=b"6")
        reject(SOURCE.replace(b"effect pure", b"effect read"), b"denied", subject=b"effect", mark=b"read")
        reject(SOURCE.replace(b"fragment blend", b"fragment\tblend"), b"syntax", mark=b"\t")
        reject(SOURCE.replace(b"fragment blend", b"fragment \xffblend"), b"syntax", mark=b"\xff")
        assert reject(SOURCE[:-1], b"syntax", mark=b"") == (len(SOURCE)-1, len(SOURCE)-1)
        reject(SOURCE + b"# comment\n", b"syntax", mark=b"#")
        reject(SOURCE + b"x" * 4096, b"size")
        assert reject(b"x\n" * 97, b"size", mark=b"x") == (192, 193)
        reject(SOURCE, b"compiler_identity", compiler_id="bad")
        reject(HEADER + FIRST, b"fragment_count", mark=b"")
        fourth = (THIRD.replace(b"deliver", b"fourth").replace(b"finish", b"more").replace(b"final", b"fourth")
                  .replace(b"wire before mixed", b"wire before final"))
        fifth = fourth.replace(b"fourth", b"fifth")
        _, four_graph, four_evidence = accepted(SOURCE + fourth, "max-fragments")
        assert four_evidence[:3] == [b"ok", four_graph, b"4"]
        reject(SOURCE + fourth + fifth, b"fragment_limit", b"fifth", b"fifth", b"fifth", task="max-fragments")
        reject(SOURCE.replace(b"fragment blend", b"fragment prepare"), b"duplicate_fragment", b"prepare",
               b"prepare", b"prepare")
        reject(SOURCE.replace(b"wire inbound normalized\n", b""), b"missing_wire", b"blend", mark=b"end")
        reject(HEADER + FIRST.replace(b"\nend", b"\nwire raw normalized\nend") + SECOND + THIRD,
               b"unexpected_wire", b"prepare", b"raw", b"wire raw normalized")
        reject(SOURCE.replace(b"wire inbound normalized", b"wire inbound final"), b"link_reference",
               b"blend", b"inbound", b"wire inbound final")
        reject(SOURCE.replace(b"wire inbound normalized", b"wire absent normalized"), b"link_reference",
               b"blend", b"absent", b"wire absent normalized")
        reject(SOURCE.replace(b"wire inbound normalized\n", b"wire inbound normalized\nwire inbound mixed\n"),
               b"duplicate_wire", b"blend", b"inbound", b"inbound")
        widened = FIRST.replace(b"output normalized test.value@1 none none required 32",
                                b"output normalized test.value@1 none none required 64")
        reject(HEADER + widened + SECOND + THIRD, b"edge_type", b"blend", b"inbound",
               b"wire inbound normalized")
        reject(SOURCE.replace(b"value=raw", b"value=normalizer.value"), b"cycle", b"prepare",
               mark=b"fragment prepare")
        reject(HEADER + FIRST + SECOND.replace(b"mixer", b"normalizer") + THIRD,
               b"duplicate_id", b"blend", b"normalizer", b"let normalizer = test.join@1 a=inbound b=extra")
        reject(SOURCE.replace(b"import test.pass@1", b"import test.missing@1"), b"unknown_handler",
               b"prepare", b"test.missing@1", b"test.missing@1")
        reject(SOURCE.replace(b"emit normalized normalizer.value", b"emit normalized raw"), b"emit",
               b"prepare", b"normalized", b"raw")
        reject(SOURCE.replace(b"emit normalized normalizer.value\n",
                              b"emit normalized normalizer.value\nemit normalized normalizer.value\n"),
               b"duplicate_emit", b"prepare", b"normalized", b"normalized")
        reject(SOURCE, b"budget", b"deliver", b"finish",
               b"let finish = test.join@1 a=before b=original", task="budget")
    print("ottomat_composition_ok=true native_parity=true alternate_source=true binding_recheck=true")


if __name__ == "__main__":
    main()
