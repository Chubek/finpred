#!/usr/bin/env python3
"""Exercise the compiled worksheet, verified import and actual terminal controls."""
from contextlib import contextmanager
import csv
import io
import json
import os
import pty
import select
import subprocess
import tempfile
import time
from pathlib import Path

from check_poindexter_cli import CONTRIBUTION_HEADER, CONTRIBUTION_ID, CONTRIBUTION_INPUTS
from check_store import invoke, tree

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin/poindexter"


@contextmanager
def terminal(env, book):
    master, slave = pty.openpty()
    proc = subprocess.Popen([CLI, "--book", book], env=env, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    data = b""
    def expect(needle):
        nonlocal data
        deadline = time.monotonic() + 10
        while needle not in data:
            remain = deadline - time.monotonic()
            if remain < 0 or not select.select([master], [], [], remain)[0]:
                raise AssertionError((needle, data[-1000:]))
            data += os.read(master, 65536)
        _, _, data = data.partition(needle)
    def key(s):
        os.write(master, s.encode())
    try:
        yield expect, key
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


def interactive(env, book):
    with terminal(env, book) as (expect, key):
        expect(b"Press ?")
        key("\x1b[C"); expect(b"B1  fx:")
        key("e"); expect(b"Edit B1:"); key("=4*7\n"); expect(b"Value: 28")
        key("u"); expect(b"Undone."); key("r"); expect(b"Redone.")
        key("x"); expect(b"Worksheet statement:"); key("SET B1 = B1+2\n"); expect(b"Value: 30")
        key("s"); expect(b"Workbook saved."); key("q")


def save_conflicts(env, book, new_book):
    # Valid, noncanonical row order: stale detection must compare the raw
    # snapshot, not the worker's normalized encoding.
    original = b"poindexter-workbook@1\nB1\t2\nA1\t1\n"
    external = original.replace(b"A1\t1\n", b"A1\t90\n")
    book.write_bytes(original)
    with terminal(env, book) as (expect, key):
        expect(b"Press ?")
        key("x"); expect(b"Worksheet statement:"); key("SET A1 = 7\n")
        expect(b"Value: 7")
        book.write_bytes(external)
        key("s"); expect(b"Value: 7"); expect(b"Save conflict: workbook changed on disk.")
        assert book.read_bytes() == external
        assert not list(book.parent.glob(f"{book.name}.tmp.*"))
        key("q"); expect(b"Discard unsaved changes?"); key("n\n")
        book.write_bytes(original)
        key("s"); expect(b"Workbook saved.")
        assert book.read_bytes() == b"poindexter-workbook@1\nA1\t7\nB1\t2\n"
        key("x"); expect(b"Worksheet statement:"); key("SET A1 = 8\n")
        expect(b"Value: 8")
        key("s"); expect(b"Workbook saved."); key("q")
    assert book.read_bytes() == b"poindexter-workbook@1\nA1\t8\nB1\t2\n"

    with terminal(env, new_book) as (expect, key):
        expect(b"Press ?")
        key("x"); expect(b"Worksheet statement:"); key("SET A1 = 9\n")
        expect(b"Value: 9")
        new_book.write_bytes(b"not a workbook\n")
        key("s"); expect(b"Value: 9"); expect(b"Save conflict: workbook path is no longer free.")
        assert new_book.read_bytes() == b"not a workbook\n"
        assert not list(new_book.parent.glob(f"{new_book.name}.tmp.*"))
        new_book.unlink()
        key("s"); expect(b"Workbook saved."); key("q")
    assert new_book.read_bytes() == b"poindexter-workbook@1\nA1\t9\n"


def contribution_import(parent, env):
    home = parent / "contribution-store"
    missing = parent / "missing"
    env = {**env, "FINPRED_HOME": str(home),
           **{f"FINPRED_{k}": str(missing) for k in ("SCENARIO", "OFFERS", "DEMAND", "STRATEGY", "VALUATION")}}

    def cli(*args):
        return subprocess.run([CLI, *args], env=env, capture_output=True, timeout=20)

    def out(*args):
        proc = cli(*args)
        assert proc.returncode == 0, proc
        return proc.stdout.decode("ascii")

    summary = invoke(home, "run", **CONTRIBUTION_INPUTS).decode("ascii")
    fields = dict(line.split("=", 1) for line in summary.splitlines())
    rid = fields["run_id"]
    assert rid == CONTRIBUTION_ID
    before = tree(home)
    book = parent / "contribution.pxw"
    rows = list(csv.reader(io.StringIO(out("--run", rid, "--book", book, "--csv"))))
    assert rows[0] == CONTRIBUTION_HEADER.split(",")
    assert rows[1][:2] == ["poindexter.contribution-sheet@1", f"run:{rid}"]
    assert rows[1][6:11] == ["17500", "19000", "1500", "max_expected_contribution", "false"]
    assert rows[1][12:] == ["8000", "105000", "milli_minor:1155000000", "1000"]
    assert "O2\t'milli_minor:1155000000\n" in book.read_text()

    script = parent / "contribution.pxs"
    script.write_text("ASSERT (H2-M2)*N2/P2 = 1155000\nSET H2 = H2+1\n")
    assert out("--book", book, "--script", script, "--get", "H2") == "19001\n"
    assert out("--run", rid, "--get", "H2") == "19000\n"
    assert tree(home) == before

    # A valid total may be larger than the worksheet's arithmetic limit.
    demand = parent / "max-demand.csv"
    head = CONTRIBUTION_INPUTS["demand"].read_bytes().splitlines()[:4]
    demand.write_bytes(b"\n".join(head + [b"0,1000000", b"1000000000000,1000000", b""])
                       .replace(b",8000\n", b",0\n"))
    valuation = parent / "max-valuation.csv"
    valuation.write_bytes((ROOT / "fixtures/valuation.csv").read_bytes().replace(
        b",17500,16000,25000,5000,500\n", b",1000000000000,0,1000000000000,1000000000000,0\n"))
    edge = invoke(home, "run", **dict(CONTRIBUTION_INPUTS, demand=demand, valuation=valuation))
    max_id = edge.splitlines()[0].decode("ascii").split("=", 1)[1]
    before = tree(home)
    assert out("--run", max_id, "--get", "O2") == "milli_minor:1000000000000000000\n"
    assert tree(home) == before

    trace = home / f"artifacts/blake3-{fields['trace_digest']}.txt"
    trace.write_bytes(b"corrupted\n")
    before = tree(home)
    rejected = parent / "rejected-contribution.pxw"
    proc = cli("--run", rid, "--book", rejected, "--csv")
    assert proc.returncode > 0 and not proc.stdout and not rejected.exists(), proc
    assert tree(home) == before


def main():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PX_", "FINPRED_")) or k == "FINPRED_EXE"}
    with tempfile.TemporaryDirectory(prefix="finpred-worksheet-") as tmp:
        d = Path(tmp)
        env.update(FINPRED_HOME=str(d / "store"), TERM="xterm")
        def cli(*args, ok=True):
            proc = subprocess.run([CLI, *args], env=env, capture_output=True, text=True, timeout=20)
            if ok != (proc.returncode == 0):
                raise AssertionError((args, proc.returncode, proc.stdout, proc.stderr))
            return proc.stdout if ok else proc.stderr
        script, book = d / "script", d / "worksheet"
        script.write_text("""TEXT A1 Buckets
FILL A2:A5 = ROW()*10
FORMULA B1 = SUM(A2:A5)
FORMULA B2 = AVG(A2:A5)
FORMULA B3 = MIN(A2:A5)+MAX(A2:A5)*2
FORMULA B4 = COUNT(A1:A5)
FORMULA C1 = IF(B1=140,B1+3*2,1/0)
LET X = 1
REPEAT 5
  LET X = $X*2
END
IF $X>31
  SET C2 = $X+ABS(-10)
ELSE
  SET C2 = 0
END
ASSERT C1=146
ASSERT C2=42
ASSERT ROUNDDIV(-5,2)=-3
ASSERT ROUNDDIV(5,-2)=-3
ASSERT ROUNDDIV(4,3)=1
TEXT C3 Quoted "label", retained
FORMULA D1 = P64+1
FORMULA D2 = B2/0
FORMULA D3 = 1000000000000000*2
FORMULA D4 = A1+1
FORMULA D5 = D5+1
""")
        rows = list(csv.reader(io.StringIO(cli("--script", script, "--book", book))))
        assert rows[0] == ["Buckets", "140", "146", "1"], rows
        assert rows[1] == ["20", "35", "42", "#DIV/0!"]
        assert rows[2] == ["30", "120", 'Quoted "label", retained', "#NUM!"]
        assert rows[3][1:] == ["4", "", "#VALUE!"]
        assert rows[4][3] == "#CYCLE!"
        before = book.read_bytes()
        for code in ["SET A2 = 900\nASSERT 0\n", "REPEAT 257\nEND\n",
                     "REPEAT 256\nREPEAT 256\nSET A1 = 1\nEND\nEND\n",
                     "SHELL whoami\n", "SET Q1 = 9\n", "FORMULA A1 = 1+\n"]:
            script.write_text(code)
            assert cli("--book", book, "--script", script, ok=False)
            assert before == book.read_bytes()
        script.write_text("SET A2 = 100\n")
        assert cli("--book", book, "--script", script, "--get", "B1") == "220\n"
        assert cli("--book", book, "--get", "C1") == "#DIV/0!\n"
        assert "=SUM(A2:A5)" in book.read_text()
        script.write_text("SET A1 = 2\nSET A2 = 3\nSET B1 = 5\n"
                          "FORMULA C2 = A1+$A1+A$1+$A$1\nCOPY C2 D3:D4\n")
        assert cli("--book", book, "--script", script, "--get", "D3") == "40\n"  # B2 + A2 + B1 + A1
        assert "D3\t=B2+$A2+B$1+$A$1\n" in book.read_text()
        assert "D4\t=B3+$A3+B$1+$A$1\n" in book.read_text()
        before = book.read_bytes()
        script.write_text("COPY C2 A1\n")
        assert "off the grid" in cli("--book", book, "--script", script, ok=False)
        assert book.read_bytes() == before
        chain = d / "deep"
        chain.write_text("poindexter-workbook@1\n" +
                         "".join(f"A{i}\t=A{i+1}\n" for i in range(1,60)) + "A60\t1\n")
        chain_rows = list(csv.reader(io.StringIO(cli("--book", chain, "--csv"))))
        assert chain_rows[0] == ["#DEPTH!"] and chain_rows[49] == ["1"]
        data = d / "input.csv"
        data.write_bytes(b'"Item, one","He said ""yes""",0042,=1+1\r\n12,-5,,\r\n')
        imported = d / "imported"
        rows = list(csv.reader(io.StringIO(cli("--import-csv", data, "--book", imported, "--csv"))))
        assert rows == [["Item, one", 'He said "yes"', "0042", "=1+1"], ["12", "-5", "", ""]]
        assert cli("--book", imported, "--get", "D1") == "=1+1\n"
        data.write_text('"broken\n')
        bad = d / "bad"
        assert cli("--import-csv", data, "--book", bad, "--csv", ok=False) and not bad.exists()
        summary = subprocess.check_output([ROOT / "bin/finpred", "run"], env=env, text=True)
        rid = summary.splitlines()[0].split("=")[1]
        legacy = json.loads((ROOT / "fixtures/replay_v1.json").read_bytes())
        for path, content in legacy["files"].items():
            (d / "store" / path).write_bytes(content.encode("ascii"))
        legacy_id, = (key for key, text in legacy["runs"].items() if "recommendation_minor=17100\n" in text)
        def snapshot():
            return {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in (d / "store").rglob("*.txt")}
        frozen = snapshot()
        price = ROOT / "plugins/poindexter/workbench/examples/price-check.pxs"
        assert cli("--run", rid, "--script", price, "--get", "B12") == "121800\n"
        assert cli("--run", rid, "--get", "B2") == f"run:{rid}\n"
        assert cli("--run", legacy_id, "--get", "H2") == "17100\n"
        assert frozen == snapshot()
        assert cli("--run", "0"*64, "--csv", ok=False)
        interactive(env, d / "interactive")
        assert cli("--book", d / "interactive", "--get", "B1") == "30\n"
        save_conflicts(env, d / "existing-save", d / "new-save")
        assert frozen == snapshot()
        contribution_import(d, env)
    print("poindexter_workbench_ok=true formulae scripts rollback replay_import_v1_v2_v3 terminal_edit_save save_conflicts=2")


if __name__ == "__main__":
    main()
