#!/usr/bin/env python3
"""Compile an independent C11 std.environ.argv consumer with the pinned toolchain."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CONSUMER = """\
import std.environ as Env;

fn main() {
  let (count_only, _) = Env.getenv("COUNT_ONLY");
  let count = Env.argc();
  if count_only { println(count); return; }

  var args = Env.argv();
  let wire = buffer_new();
  buffer_append(wire, format("{}\\n", count));
  var i = 0;
  while sx_kind(args) == 3 {
    let atom = sx_head(args);
    assert(sx_kind(atom) == 2);
    let value = sx_text(atom);
    buffer_append(wire, format("{}:", text_len(value)));
    buffer_append(wire, value);
    args = sx_tail(args);
    i = i + 1;
  }
  assert(sx_kind(args) == 0 && i == count);
  println(buffer_text(wire));
}
"""


def main():
    mulib = Path(os.environ.get("MULIB_ROOT") or ROOT / "third_party/mulib").resolve()
    compiler = Path(os.environ.get("ON1XC") or ROOT / "build/mulib/on1x/on1xc").resolve()
    with tempfile.TemporaryDirectory(prefix="finpred-environ-argv-") as tmp:
        work = Path(tmp).resolve()
        source = work / "main.on1x"
        source.write_text(CONSUMER, encoding="ascii")
        exe = work / "argv probe"
        subprocess.run(
            [sys.executable, mulib / "on1x/tools/on1x-build.py", source, "--backend", "c11",
             "--on1xc", compiler, "--mulib-root", mulib, "--stdlib", mulib / "on1x/stdlib",
             "-o", exe],
            cwd=work, env=os.environ | {"TMPDIR": str(work), "PYTHONDONTWRITEBYTECODE": "1"},
            check=True, timeout=90,
        )

        def run(vector, **env):
            # Separate the executable path from argv[0]; use bytes so the locale
            # cannot transform the arguments or conceal non-UTF-8 bytes.
            return subprocess.run(vector, executable=exe, cwd=work, env=env,
                                  capture_output=True, timeout=10)

        def snapshot(vector):
            wire = b"".join(str(len(arg)).encode("ascii") + b":" + arg for arg in vector)
            p = run(vector)
            assert p.returncode == 0 and not p.stderr, p
            assert p.stdout == str(len(vector)).encode("ascii") + b"\n" + wire + b"\n"

        snapshot([os.fsencode(exe)])
        snapshot([b"custom argv[0]", b"z", b"", "café 東京 🏨".encode("utf-8"),
                  b"a:b\n two words", b"\xff", b"z", b""])
        snapshot([b"", b"--engine", b"scalar"])
        snapshot([b"probe", b"x" * 4096])
        at_limit = [b"probe"] + [b""] * 4094 + [b"last"]
        snapshot(at_limit)

        over_limit = at_limit + [b"extra"]
        p = run(over_limit)
        assert (p.returncode, p.stdout, p.stderr) == (
            73, b"", b"On1x tool error: argv snapshot entry limit exceeded\n",
        ), p
        p = run(over_limit, COUNT_ONLY="1")
        assert (p.returncode, p.stdout, p.stderr) == (0, b"4097\n", b""), p

    print("environ_argv_ok=true snapshots=5 rejected=1 count_only=1")


if __name__ == "__main__":
    main()
