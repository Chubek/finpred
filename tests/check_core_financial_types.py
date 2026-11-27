#!/usr/bin/env python3
"""Exercise the production competitor arithmetic and the declared-module profile."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ROOT / "tests/core_financial_types_consumer"


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    cc = os.environ.get("CC", "cc")
    scratch = ROOT / "build/tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="core-types-", dir=scratch) as tmp:
        work = Path(tmp)
        env = {**os.environ, "TMPDIR": tmp}

        def run(*args, **settings):
            return subprocess.run(args, cwd=work, env={**env, **settings},
                                  capture_output=True, timeout=60)

        def success(p, stdout=None):
            assert p.returncode == 0, (p.args, p.stdout, p.stderr)
            if stdout is not None:
                assert (p.stdout, p.stderr) == (stdout, b""), (p.args, p.stdout, p.stderr)

        def failure(p, message):
            assert p.returncode > 0 and message in p.stderr, (p.args, p.stdout, p.stderr)

        legacy = work / "legacy"
        success(run(sys.executable, sdk / "on1x/tools/on1x-build.py", CONSUMER / "legacy.on1x",
                    "--backend", "c11", "--on1xc", compiler, "--mulib-root", sdk, "--cc", cc,
                    "-I", ROOT / "source", "-o", legacy))
        success(run(legacy, CASE="ok"), b"legacy competitor amounts ok\n")
        for case, message in (
            ("invalid_amount", b"competitor: invalid quote occupancy, inventory, conditions or amount"),
            ("invalid_shape", b"competitor: invalid bundle discount"),
            ("insufficient_net", b"competitor: bundle discount not supported by every qualifying base total"),
            ("empty_bundle", b"competitor: bundle discount not supported by every qualifying base total"),
        ):
            result = run(legacy, CASE=case)
            failure(result, message)
            assert not result.stdout, result.stdout

        mismatch = work / "unit_mismatch.on1x"
        mismatch.write_text(
            'import core.quote_amounts as A;\n'
            'fn main() {\n'
            '  let gross = record<A.GrossStay>{minor:1};\n'
            '  let net = A.maximum_net_base();\n'
            '  let _ = A.min_net_base(net,gross);\n'
            '}\n', encoding="utf-8",
        )
        emitted = work / "unit_mismatch.c"
        result = run(compiler, "--emit-c", "-I", ROOT / "source", mismatch, "-o", emitted)
        failure(result, b"nominal")
        assert not emitted.exists()

        # Stage the real declared-module project; both paths use the same
        # production arithmetic, without adding membership to legacy consumers.
        project = work / "project"
        src = project / "src"
        core = src / "core"
        core.mkdir(parents=True)
        shutil.copyfile(CONSUMER / "On1xfile", project / "On1xfile")
        for file in ("main.on1x", "sealed_quote_amounts.on1xm", "sealed_quote_amounts.on1xi"):
            shutil.copyfile(CONSUMER / file, src / file)
        for file in ("quote_amounts.on1x", "money.on1x"):
            shutil.copyfile(ROOT / "source/core" / file, core / file)
        (src / "On1xfile.m").write_text('on1xfile 1\nsource "main.on1x"\n', encoding="utf-8")
        (core / "On1xfile.m").write_text(
            'on1xfile 1\nlibrary "quote_amounts.on1x"\nlibrary "money.on1x"\n', encoding="utf-8")
        output = work / "generation"
        exe = output / "core-financial-types"

        def project_build():
            return run(sys.executable, sdk / "on1x/tools/on1x-project.py", "build", project,
                       "--on1xc", compiler, "--mulib-root", sdk, "--cc", cc, "--output-dir", output)

        success(project_build())
        success(run(exe), b"sealed competitor amounts ok\n")
        report = output / ".on1x-build.json"
        original = (exe.read_bytes(), report.read_bytes())
        entry = src / "main.on1x"
        entry.write_text(
            'import CoreTest.QuoteAmounts as A;\n'
            'fn main() { let _ = A.CheckedQuote::Accepted(42,42); }\n', encoding="utf-8")
        failure(project_build(), b"opaque module type representation is not accessible")
        assert (exe.read_bytes(), report.read_bytes()) == original
        shutil.copyfile(CONSUMER / "main.on1x", entry)
        iface = src / "sealed_quote_amounts.on1xi"
        signature = iface.read_text(encoding="utf-8")
        iface.write_text(signature.replace("(bool,i64,i64)", "(i64,i64,i64)"), encoding="utf-8")
        failure(project_build(), b"signature mismatch")
        assert (exe.read_bytes(), report.read_bytes()) == original
    print("core_financial_types_ok=true legacy_rejections=5 signed_rejections=2")


if __name__ == "__main__":
    main()
