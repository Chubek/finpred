#!/usr/bin/env python3
"""Check scalar lineage against independent frozen bytes and BLAKE3-256 hashes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
compiler = os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")

# Computed with libblake3 1.8.7 independently of On1x. Order is input order
# followed by evaluation order, which differs from plan declaration order.
first = "d7bba29d68d693f5bca94074acd372bef5a635e18dfce851724a58095d348f27"
second = "c378311fce28b1237559d877812fc1612368f81a6221f6085fc768a092794456"
hi = "f7a555ef982f0fd0f70759fe01c84fdfc5e1ddd5b97edd6dbb550ced83feaa0b"
lo = "eb7cb8ad7e64ee1259648335e032d61bf031485485d9ba68533699fb648536da"
spread = "f3f59aede2d460f6e4c25363919556d703726661ec3d0acf6be7a3af42767967"
swapped = "f0d026963928e37f7d5e79599d186c2c653c7756f3d66a10824e1fd08ae564a1"
entries = [
    (first, "scalar-input@1\nname=first\nkind=scalar.level@1\nvalue=17\n"),
    (second, "scalar-input@1\nname=second\nkind=scalar.level@1\nvalue=42\n"),
    (hi, "scalar-node@1\nid=hi\nowner=finpred.core@1\nhandler=maximum@1\nkind=scalar.level@1\n"
         f"left={first}\nright={second}\nvalue=42\n"),
    (lo, "scalar-node@1\nid=lo\nowner=finpred.core@1\nhandler=minimum@1\nkind=scalar.level@1\n"
         f"left={first}\nright={second}\nvalue=17\n"),
    (spread, "scalar-node@1\nid=spread\nowner=finpred.core@1\nhandler=distance@1\nkind=scalar.distance@1\n"
             f"left={hi}\nright={lo}\nvalue=25\n"),
]
with tempfile.TemporaryDirectory(prefix="finpred-dag-replay-") as tmp:
    exe = Path(tmp) / "consumer"
    subprocess.run([sys.executable, sdk / "on1x/tools/on1x-build.py",
                    ROOT / "tests/dag_replay_consumer/main.on1x", "--backend", "c11",
                    "--on1xc", compiler, "--mulib-root", sdk, "-I", ROOT / "source", "-I", ROOT,
                    "-o", exe], cwd=tmp, check=True)

    def check(case, expected, items=entries, root=spread, output="spread"):
        env = {**os.environ, "DAG_CASE": case, "OUTPUT": output, "ROOT_DIGEST": root}
        for i, (digest, data) in enumerate(items):
            env.update({f"HASH{i}": digest, f"BYTES{i}": data})
        run = subprocess.run([exe], cwd=tmp, env=env, timeout=10, capture_output=True)
        assert run.returncode == 0, (case, run.returncode, run.stderr)
        assert run.stdout == expected.encode("ascii"), (case, run.stdout, expected)

    frames = "".join(f"{key}\n{data}END\n" for key, data in entries)
    for output, root in [("spread", spread), ("hi", hi), ("spread", spread)]:
        check("dump", root + "\n" + frames, output=output)
        check("verify", "true\n", root=root, output=output)

    for case in ("missing", "extra", "nonlist", "pair_short", "pair_long",
                 "bytes_type", "nil_root", "input", "denied"):
        check(case, "false\n")
    check("order", "false\n", entries[:2] + [entries[3], entries[2], entries[4]])
    check("root", "false\n", root=hi)
    check("input_bytes", "false\n", [(first, entries[0][1].replace("17", "18"))] + entries[1:])
    check("digest", "false\n", [(second, entries[0][1])] + entries[1:])
    # Both the forged child and its root digest agree on reversed parents.
    # Distance is symmetric: checking the scalar value alone misses this edit.
    forged = entries[-1][1].replace(f"left={hi}\nright={lo}", f"left={lo}\nright={hi}")
    check("parents", "false\n", entries[:-1] + [(swapped, forged)], root=swapped)
print("scalar_dag_replay_ok=true golden_runs=3 verified=3 rejected=14")
