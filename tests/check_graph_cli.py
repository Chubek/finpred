#!/usr/bin/env python3
"""Exercise the built read-only graph command through the public launcher."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from check_financial_graph import GRAPH_ID, ROOT

LAUNCHER = ROOT / "bin/finpred"
STRATEGY = ROOT / "tests/ottomat_financial_consumer/hospitality.ottomat"
PROFILE = "finpred.hospitality-graph-check@1"


def composed(v6):
    lines = v6.splitlines(keepends=True)
    return b"".join([
        b"ottomat 7\n", lines[1], b"fragment prepare\n",
        lines[2].replace(b"input scenario", b"input normalize-scenario"), lines[3], lines[5],
        lines[10].replace(b"scenario=scenario", b"scenario=normalize-scenario"),
        b"output inventory hospitality.inventory@1 minor_per_stay EUR required 65536\n",
        b"emit inventory normalizer.normalized\nend\nfragment recommend\n",
        lines[2], lines[4],
        b"input prepared hospitality.inventory@1 minor_per_stay EUR required 65536\n",
        *lines[6:10], lines[11].replace(b"normalizer.normalized", b"prepared"), *lines[12:],
        b"wire prepared inventory\nend\n",
    ])


def main():
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="graph-cli-", dir=ROOT / "build") as tmp:
        work = Path(tmp)
        state = work / "no-store"
        env = {
            **os.environ,
            "FINPRED_HOME": str(state),
            "FINPRED_SCENARIO": str(work / "no-evidence"),
            "FINPRED_STRATEGY": str(work / "not-the-request"),
            "FINPRED_GRAPH_BUDGET": "1",
            "FINPRED_GRAPH_RESOLVER": "caller-supplied",
            "FINPRED_GRAPH_COMPILER": "sha256:" + "0" * 64,
        }
        env.pop("FINPRED_MODE", None)
        strategy = work / "strategy with spaces.ottomat"
        v6 = STRATEGY.read_bytes()
        v7 = composed(v6)

        def launch(*args, **overrides):
            return subprocess.run(
                [LAUNCHER, "graph", *args], cwd=work,
                env={**env, **overrides}, capture_output=True, timeout=10,
            )

        def check(path=strategy.name, *, action="inspect", status="ok"):
            p = launch(action, path)
            assert p.returncode == (0 if status == "ok" else 1), p
            assert not p.stderr and len(p.stdout.splitlines()) == 1, p
            d = json.loads(p.stdout)
            assert d["schema"] == "finpred-graph-check@1" and d["profile"] == PROFILE, d
            assert d["status"] == status, d
            assert not state.exists()
            if status != "ok":
                assert set(d) == {"schema", "profile", "status", "ottomat_version", "diagnostic"}, d
            return d

        strategy.write_bytes(v6)
        old = check()
        assert old == check(str(strategy))
        summary = check(action="validate")
        assert summary == {k: v for k, v in old.items() if k not in {"inputs", "nodes", "exports"}}
        assert old["graph_digest"] == GRAPH_ID and old["ottomat_version"] == 6
        assert old["source_digest"] == (
            "blake3:d8fbf323a9a60af57204ac57c01129dc96476806d5c5a76b484179e17d6a0620"
        )
        assert old["lowering"] == "finpred.ottomat-financial-lowering@1"
        assert old["mode"] == "recommendation" and old["effect"] == "pure"
        assert old["bounds"] == {
            "work": 1000004, "budget": 1000004, "edges": 13, "depth": 5,
            "max_root_bytes": 2004096, "max_read_bytes": 2096896, "max_emitted_bytes": 74880,
        }
        assert [p["name"] for p in old["inputs"]] == ["offers", "scenario", "valuation"]
        assert [n["id"] for n in old["nodes"]] == [
            "normalizer", "comparables", "diagnostic", "decision", "guardrails",
        ]
        assert old["nodes"][0]["pin"]["handler"] == "yieldcraft.normalize@1"
        assert old["nodes"][0]["pin"]["code_digest"] == (
            "blake3:c9bdef211c603aa7a31f6271c8bee5c6bb82da0b5a50f33434fb41d3a0f34759"
        )
        assert old["nodes"][1]["bindings"][1] == {
            "input": "normalized", "from": {"node": "normalizer", "port": "normalized"},
        }
        assert old["nodes"][0]["bindings"][0]["from"] == {"node": None, "port": "scenario"}
        assert old["exports"][0]["from"] == {"node": "guardrails", "port": "recommendation"}
        compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc"))
        if compiler.is_file():
            assert old["compiler_identity"] == "sha256:" + hashlib.sha256(compiler.read_bytes()).hexdigest()
        else:
            assert len(old["compiler_identity"]) == 71 and old["compiler_identity"].startswith("sha256:")

        strategy.write_bytes(v6.replace(b"scenario=scenario offers=offers", b"offers=offers scenario=scenario"))
        reordered = check()
        assert reordered["source_digest"] != old["source_digest"]
        assert {k: v for k, v in reordered.items() if k != "source_digest"} == {
            k: v for k, v in old.items() if k != "source_digest"
        }

        strategy.write_bytes(v7)
        composed_report = check()
        assert composed_report["ottomat_version"] == 7
        assert composed_report["lowering"] == "finpred.ottomat-financial-composition@1"
        assert composed_report["source_digest"] != old["source_digest"]
        assert composed_report["nodes"][1:] == old["nodes"][1:]
        assert composed_report["nodes"][0]["bindings"][0]["from"]["port"] == "normalize-scenario"
        assert [p["port"]["name"] for p in composed_report["exports"]] == ["inventory", "recommendation"]
        flatten = v6.replace(b"input scenario", v6.splitlines()[2].replace(
            b"input scenario", b"input normalize-scenario"
        ) + b"\ninput scenario").replace(b"scenario=scenario", b"scenario=normalize-scenario", 1).replace(
            b"output recommendation", b"output inventory hospitality.inventory@1 minor_per_stay EUR required 65536\n"
            b"output recommendation",
        ) + b"emit inventory normalizer.normalized\n"
        strategy.write_bytes(flatten)
        assert check()["graph_digest"] == composed_report["graph_digest"]

        # A public but unused port's arbitrary printable type token still
        # needs JSON escaping, even on a valid financial graph.
        odd_type = b'test."\\kind'
        strategy.write_bytes(v6.replace(b"input scenario", b"input spare " + odd_type +
                                       b"@1 none none required 16\ninput scenario"))
        assert check()["inputs"][-2]["kind"] == odd_type.decode()

        for raw, status, version in (
            (b"", "size", 0), (b"x" * 4097, "size", 0),
            (v6.replace(b"ottomat 6", b"ottomat 5"), "version", 0),
            (v6[:-1], "syntax", 6),
            (v6.replace(b"effect pure", b"effect read"), "denied", 6),
            (v7.replace(b"effect pure", b"effect record"), "denied", 7),
            (v6.replace(b"import yieldcraft.normalize@1", b"import missing.handler@1"), "unknown_handler", 6),
            (v6.replace(b"finpred.offers.csv@1", b"finpred.offers.csv@2"), "edge_type", 6),
            (v6.replace(b"let diagnostic", b"let extra = yieldcraft.comparables@1 "
                        b"scenario=scenario normalized=normalizer.normalized\nlet diagnostic"), "budget", 6),
            (v7.replace(b"wire prepared inventory", b"wire prepared missing"), "link_reference", 7),
        ):
            strategy.write_bytes(raw)
            assert check(status=status)["ottomat_version"] == version
        strategy.write_bytes(v6.replace(b"input scenario", b"input\x00scenario", 1))
        assert check(status="syntax")["diagnostic"] == {
            "line": 3, "column": 6, "byte_range": [27, 28], "fragment": "", "subject": "",
        }
        invalid_name = b'bad"\\'
        malformed = v7.replace(b"fragment prepare", b"fragment " + invalid_name)
        strategy.write_bytes(malformed)
        a = malformed.index(invalid_name)
        assert check(status="fragment")["diagnostic"] == {
            "line": 3, "column": 10, "byte_range": [a, a + len(invalid_name)],
            "fragment": invalid_name.decode(), "subject": invalid_name.decode(),
        }

        os.mkfifo(work / "fifo")
        (work / "symlink").symlink_to(strategy)
        check("absent", status="input_open")
        check(".", status="input_type")
        check("fifo", status="input_type")
        check("symlink", status="input_open")
        for args in (("run", strategy.name), ("inspect", strategy.name, "--execution"), ("validate",)):
            p = launch(*args)
            assert p.returncode == 2 and not p.stdout, p
        p = launch("inspect", strategy.name, FINPRED_MODE="execution")
        assert p.returncode == 2 and not p.stdout, p
        assert not state.exists()
    print("graph_cli_ok=true")


if __name__ == "__main__":
    main()
