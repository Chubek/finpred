#!/usr/bin/env python3
"""Build an actual On1x→C11 series consumer and compare across its text ABI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from check_core_numerics import LIMIT, ROOT, oracle_case

CONSUMER = r'''
import algorithms.series_forecast as Series;
import std.environ as Env;
import std.Int as Int;
import std.io.TextIO as IO;

fn arg(name:string) -> i64 {
  let (found, text) = Env.getenv(name);
  let (ok, value, end) = Int.scan(text,0);
  if !found || !ok || end != text_len(text) { tool_fail("bad test setting"); }
  return value;
}

fn main() {
  let data = io_stdin();
  let h = arg("TEST_HORIZON");
  let s = arg("TEST_SEASON");
  let c = arg("TEST_COVERAGE");
  let f = arg("TEST_FIRST");
  let p = Series.predict(data,h,s,c);
  let ps = sx_text(p["status"]);
  if ps == "ok" {
    var interval = 0;
    if p["has_interval"] { interval = 1; }
    println("$ps,${p["point"]},${p["calibration_count"]},$interval,${p["lower"]},${p["upper"]}");
  } else { println(ps); }
  let e = Series.evaluate(data,h,s,c,f);
  let es = sx_text(e["status"]);
  if es == "ok" {
    println("$es,${e["point_count"]},${e["interval_count"]},${e["covered_count"]},${e["absolute_error_sum"]},${e["interval_width_sum"]},${e["interval_score_sum"]}");
    IO.basis_text_io_print(e["folds"]);
  } else { println(es); }
}
'''


def csv(values):
    return ",".join(map(str, values)) + "\n"


def columns(prediction):
    if prediction is None:
        return (0, 0, 0, 0, 0)
    point, count, interval = prediction
    return point, count, int(interval is not None), *(interval or (0, 0))


def test(executable):
    def run(data, h=1, s=1, c=90, f=0):
        env = {**os.environ, "TEST_HORIZON": str(h), "TEST_SEASON": str(s),
               "TEST_COVERAGE": str(c), "TEST_FIRST": str(f)}
        return subprocess.run([executable], env=env, input=data, capture_output=True, timeout=10)

    def compare(values, h=1, s=1, c=90, f=0):
        result = run("".join(f"{v}\n" for v in values).encode(), h, s, c, f)
        assert result.returncode == 0 and not result.stderr, result
        folds, metrics, prediction = oracle_case(values, h, s, c, f)
        expected = "insufficient-training\n" if prediction is None else csv(("ok", *columns(prediction)))
        expected += csv(("ok", *metrics))
        expected += "".join(csv((t, n, y, int(p is not None), *columns(p))) for t, n, y, p in folds)
        assert result.stdout == expected.encode(), (result, expected)

    compare([0, -1, -1])
    compare([-12] * 7 + [-29], c=80, f=7)
    compare([4, 1], s=2)
    seasonal = [(10, -120, 6)[i % 3] - i for i in range(47)]
    seasonal[20] = LIMIT
    compare(seasonal, h=5, s=3, f=15)
    compare([(-1)**i * LIMIT for i in range(256)], h=12, s=2, c=95)
    for data in (b"", b"0", b"00\n", b"-0\n", b"+1\n", b"--1\n", b"1\r\n",
                 b"-1000000000001\n", b"1\n" * 257, b"1\n\n"):
        result = run(data)
        assert result.returncode == 0 and result.stdout == b"invalid-history\n" * 2, result
    for args in ({"h": 0}, {"s": -1}, {"c": 91}):
        result = run(b"1\n", **args)
        assert result.returncode == 0 and result.stdout == b"invalid-request\n" * 2, result
    result = run(b"1\n", f=1)
    assert result.returncode == 0 and result.stdout == b"insufficient-training\ninvalid-request\n", result
    result = run(b"1\0\n")
    assert result.returncode and not result.stdout and b"NUL-free" in result.stderr, result


def main():
    mulib = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    scratch = ROOT / "build"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-numerics-on1x-", dir=scratch) as directory:
        build = Path(directory)
        consumer, executable = build / "main.on1x", build / "series-consumer"
        consumer.write_text(CONSUMER, encoding="utf-8")
        subprocess.run([sys.executable, "-B", mulib / "on1x/tools/on1x-build.py", consumer,
                        "--on1xc", compiler, "--backend", "c11", "--mulib-root", mulib,
                        "--mulib", "statsproc", "--cc", os.environ.get("CC", "cc"), "-I", ROOT / "source",
                        "--extra-c", ROOT / "source/algorithms/series_forecast.c",
                        "--extra-c", ROOT / "source/algorithms/series_forecast_on1x.c",
                        "--cflag=-lm", "-o", executable],
                       cwd=ROOT, env={**os.environ, "TMPDIR": str(build)}, check=True, timeout=120)
        test(executable)
    print("core_numerics_on1x_ok=true")


if __name__ == "__main__":
    main()
