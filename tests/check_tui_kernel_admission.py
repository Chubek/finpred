#!/usr/bin/env python3
"""Release-toolchain conformance: MuLIB TUI headers do not grant safe imports.

Use the release MULIB_ROOT and its ON1XC (defaults to build/on1x/on1xc).
With a newer matched toolchain, pass --expect-dynlib-syntax to check the
same denial after the compiler recognizes the dynamic linkage request.
Catalog registration and --kernel-imports do not grant safe admission.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
KERNELS = ("tui", "imtui", "termkey")
NOT_ADMITTED = "ON1X-KERNEL-NOT-ADMITTED"
DYN_SYNTAX_ERROR = "expected ';', found '['"
BODY = "fn main() { println(42); }\n"


def run(work, *args):
    env = dict(os.environ, TMPDIR=str(work), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=60)


def evidence(result):
    return f"exit={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"


def require_denied(module, source, output, result, stage, syntax_error=False):
    if result.returncode == 0 and not syntax_error:
        raise ValueError(
            f"{module}: {stage} accepted the import. Recheck the toolchain pins and the "
            "upstream profile; if it is legitimately admitted, replace the release "
            "denial expectation with a reviewed end-to-end executable test. "
            "Staged C output alone is not admission."
        )
    column = 14 if syntax_error else 1
    diagnostic = DYN_SYNTAX_ERROR if syntax_error else f"{NOT_ADMITTED}: {module} "
    located = any(
        line.startswith(f"{source}:1:{column}:") and diagnostic in line
        for line in result.stderr.splitlines()
    )
    published = output is not None and (output.exists() or output.is_symlink())
    if (result.returncode != 1 or not located or result.stdout
            or published):
        hint = (
            " Use --expect-dynlib-syntax with a newer matched toolchain."
            if syntax_error else ""
        )
        raise ValueError(
            f"{module}: {stage} did not refuse at {source}:1:{column} with "
            f"{diagnostic.strip()!r} and no output.{hint}\n{evidence(result)}"
        )


def check_import(work, module, linkage, expect_dynlib_syntax, compiler, staged, driver):
    work.mkdir()
    source = work / "probe.on1x"
    modifier = "[dynlib]" if linkage == "dynlib" else ""
    source.write_text(f"import kernel{modifier} {module} as K;\n{BODY}", encoding="ascii")
    scanned = run(work, compiler, "--kernel-imports", "--no-prelude", source)
    syntax_error = linkage == "dynlib" and not expect_dynlib_syntax
    if syntax_error:
        require_denied(module, source, None, scanned, "request inspection", syntax_error=True)
    else:
        if scanned.returncode != 0 or scanned.stderr:
            raise ValueError(
                f"{module} ({linkage}): request inspection failed; check the matching "
                f"MuLIB and compiler pins:\n{evidence(scanned)}"
            )
        report = json.loads(scanned.stdout)
        request = {
            "module": module, "alias": "K", "unsafe": False, "line": 1,
            "column": 1, "offset": 0, "file_hex": os.fsencode(source).hex(),
        }
        if linkage == "dynlib":
            request["linkage"] = "dynlib"
        if report.get("schema") != "on1x.kernel-requests/v1" or report.get("requests") != [request]:
            raise ValueError(f"{module} ({linkage}): unexpected request report: {report!r}")

    generated = work / "probe.c"
    rejected = run(work, *staged, source, "-o", generated)
    require_denied(module, source, generated, rejected, "staged C11 compiler", syntax_error)

    program = work / "probe"
    rejected = run(work, *driver, source, "-o", program)
    require_denied(module, source, program, rejected, "ordinary C11 build", syntax_error)
    status = (
        f"request=syntax_rejected scan_exit=1 {DYN_SYNTAX_ERROR}"
        if syntax_error else f"request=recognized scan_exit=0 {NOT_ADMITTED}"
    )
    print(f"{module} linkage={linkage} {status} staged_exit=1 build_exit=1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect-dynlib-syntax", action="store_true",
        help="require [dynlib] request recognition instead of the pinned release's syntax error",
    )
    args = parser.parse_args()
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", sdk / "build/on1x/on1xc")).resolve()
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ValueError(f"missing executable on1xc at {compiler}; set MULIB_ROOT or ON1XC")
    catalog_path = sdk / "on1x/contracts-exotract/kernel-auto.json"
    catalog = json.loads(catalog_path.read_bytes())["modules"]
    driver = [
        sys.executable, sdk / "on1x/tools/on1x-build.py",
        "--backend", "c11", "--on1xc", compiler, "--mulib-root", sdk, "--no-prelude",
    ]
    staged = [compiler, "--emit-c", "--kernel-c11", "--kernel-stage", "--no-prelude"]
    with tempfile.TemporaryDirectory(prefix="finpred-tui-kernel-admission-") as tmp:
        root = Path(tmp).resolve()
        control = root / "control"
        control.mkdir()
        plain = control / "plain.on1x"
        plain.write_text(BODY, encoding="ascii")
        program = control / "plain"
        built = run(control, *driver, plain, "-o", program)
        if built.returncode != 0 or not program.is_file():
            raise ValueError(f"ordinary C11 control build failed:\n{evidence(built)}")
        executed = run(control, program)
        if (executed.returncode, executed.stdout, executed.stderr) != (0, "42\n", ""):
            raise ValueError(f"ordinary C11 control run failed:\n{evidence(executed)}")

        # An allowed staged profile exercises the same compiler flags. It emits
        # an unresolved caller only; do not link or execute it without review.
        clamp = control / "clamp.on1x"
        controls = ("", "[dynlib]") if args.expect_dynlib_syntax else ("",)
        for modifier in controls:
            clamp.write_text(
                f"import kernel{modifier} mulib.clamp as K;\n"
                "fn main() { println(K.add_i64(40, 2)); }\n",
                encoding="ascii",
            )
            clamp_c = control / f"clamp{modifier}.c"
            emitted = run(control, *staged, clamp, "-o", clamp_c)
            if emitted.returncode != 0 or not clamp_c.is_file() or not clamp_c.stat().st_size:
                raise ValueError(f"staged clamp{modifier} control failed:\n{evidence(emitted)}")

        for name in KERNELS:
            module = f"mulib.{name}"
            header = f"include/mulib-{name}.h"
            if catalog.get(name, {}).get("header") != header or not (sdk / header).is_file():
                raise ValueError(f"{module}: expected {header} registered in {catalog_path}")

            for linkage in ("static", "dynlib"):
                check_import(root / f"{name}-{linkage}", module, linkage,
                             args.expect_dynlib_syntax, compiler, staged, driver)
    syntax_rejections = 0 if args.expect_dynlib_syntax else 9
    admission_rejections = 12 if args.expect_dynlib_syntax else 6
    print(f"tui_kernel_admission_ok=true executions=1 staged_controls={len(controls)} "
          f"syntax_rejections={syntax_rejections} admission_rejections={admission_rejections}")


if __name__ == "__main__":
    main()
