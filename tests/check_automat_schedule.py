#!/usr/bin/env python3
"""Compare the production dependency planner with an independent readiness oracle."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

from check_financial_graph import compile_consumer

FINANCIAL = "automat.financial-graph@1"
SCALAR = tuple(f"automat.scalar-dag@{n}" for n in (1, 2, 3))


def expected(rows, lexical):
    remaining = dict(rows)
    assert len(remaining) == len(rows)
    seen = {}
    while remaining:
        ready = [name for name, parents in remaining.items() if all(p in seen for p in parents)]
        if not ready:
            return ()
        chosen = min(ready) if lexical else ready[0]
        seen[chosen] = True
        del remaining[chosen]
    return tuple(seen)


def main():
    with tempfile.TemporaryDirectory(prefix="finpred-dependency-schedule-") as temp:
        work = Path(temp)
        exe = compile_consumer(work, "schedule_consumer")

        def run(version, rows):
            env = {**os.environ, "SCHEDULE_VERSION": version,
                   "SCHEDULE_ROWS": "".join(" ".join((name, *parents)) + "\n" for name, parents in rows)}
            result = subprocess.run([exe], cwd=work, env=env, check=True,
                                    capture_output=True, timeout=10)
            assert not result.stderr, result.stderr
            return tuple(result.stdout.decode("ascii").splitlines())

        # The first completion unlocks a higher-priority node. It must beat a
        # node that was ready all along, even with two bindings to its parent.
        ties = [("a", ["z", "z"]), ("z", []), ("zz", []), ("ab", ["zz"])]
        for version in (*SCALAR, FINANCIAL):
            assert run(version, ties) == ("z", "a", "zz", "ab")
            assert run(version, ties[::-1]) == expected(ties[::-1], version == FINANCIAL)
            assert not run(version, [*ties, ("cycle", ["cycle"])])
            assert not run(version, [("one", ["two"]), ("two", ["one"])])
            assert not run(version, [("one", ["missing"])])
            assert not run(version, [("one", []), ("one", [])])
        for version in ("automat.fixed-graph@1", "automat.financial-graph@2", "automat.scalar-dag@4"):
            assert not run(version, ties)
        assert not run(FINANCIAL, [("one", []), ("two", ["one"] * 17)])
        assert not run(FINANCIAL, [(f"n{i}", []) for i in range(33)])

        rng = random.Random(17)
        for case in range(64):
            limit = 16 if case % 2 == 0 else 32
            # Include lexical prefix/digit/punctuation ties, forward references,
            # isolated nodes, fanout and repeated edges. DAGs by construction.
            names = [f"{'abc'[i % 3]}{('', '-', '_')[i % 3]}{i // 3}" for i in range(limit)]
            rng.shuffle(names)
            width = 3 if limit == 16 else 16
            rows = [(name, rng.choices(names[:i], k=rng.randrange(width + 1)) if i else [])
                    for i, name in enumerate(names)]
            rng.shuffle(rows)
            versions = (*SCALAR, FINANCIAL) if limit == 16 else (FINANCIAL,)
            for version in versions:
                assert run(version, rows) == expected(rows, version == FINANCIAL), (version, case)
    print("automat_dependency_schedule_ok=true randomized_graphs=64")


if __name__ == "__main__":
    main()
