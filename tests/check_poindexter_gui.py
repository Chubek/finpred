#!/usr/bin/env python3
"""Compile the optional ImmGTK host and test it with the compiled On1x worker."""
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "plugins/poindexter/gui"


def main():
    env = os.environ.copy()
    mulib = Path(env.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    env["MULIB_ROOT"] = str(mulib)
    tmp = Path(env.get("TMPDIR", ROOT / "build")).resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(tmp)

    with tempfile.TemporaryDirectory(prefix="poindexter-gui-test-", dir=tmp) as work:
        work = Path(work)
        worker = Path(env.get("POINDEXTER_EXE", work / "engine/poindexter-grid")).resolve()
        if "POINDEXTER_EXE" not in env:
            subprocess.run([
                "python3", mulib / "on1x/tools/on1x-project.py", "build",
                ROOT / "plugins/poindexter/workbench",
                "--on1xc", env.get("ON1XC", ROOT / "build/mulib/on1x/on1xc"),
                "--mulib-root", mulib, "--offline", "--output-dir", worker.parent,
            ], cwd=ROOT, env=env, check=True, timeout=120)
        env["POINDEXTER_EXE"] = str(worker)
        env["POINDEXTER_GUI_EXE"] = str(work / "poindexter-gui")
        subprocess.run(["bash", GUI / "build.sh"], cwd=ROOT, env=env, check=True, timeout=60)
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "x11"], text=True))
        test = work / "conformance"
        subprocess.run([
            env.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            "-I", mulib / "include", ROOT / "tests/poindexter_gui_consumer.c", GUI / "worksheet.c",
            "-o", test, *flags, "-lm",
        ], cwd=ROOT, env=env, check=True, timeout=60)

        book = work / "local book; $(literal).pxw"
        original = b"poindexter-workbook@1\nA1\t17500\nB1\t17100\nC1\t=B1-A1\nD2\ta|\"b\nP64\t99\n"
        book.write_bytes(original)
        before = book.stat()
        sentinel = work / "unselected"
        sentinel.write_bytes(original)
        link = work / "linked.pxw"
        link.symlink_to(sentinel)
        malformed = work / "bad.pxw"
        malformed.write_bytes(b"not a workbook\n")
        queue = work / "fifo"
        os.mkfifo(queue)
        subprocess.run([test, worker, book, malformed, link, queue, work / "new.pxw"],
                       env=env, check=True, timeout=30)
        expected = original.replace(b"B1\t17100", b"B1\t=17000+50")
        assert book.read_bytes() == expected
        assert book.stat().st_ino != before.st_ino
        assert sentinel.read_bytes() == original and link.is_symlink()
        assert malformed.read_bytes() == b"not a workbook\n"
        assert (work / "new.pxw").read_bytes() == b"poindexter-workbook@1\n"
        assert not list(work.glob("*.tmp.*"))
        result = subprocess.check_output(
            [ROOT / "bin/poindexter", "--book", book, "--get", "C1"], env=env, text=True)
        assert result == "-450\n"
        # An inaccessible display should fail without touching the selected book.
        no_display = dict(env, DISPLAY="", FINPRED_HOME=str(work / "must-not-exist"))
        result = subprocess.run([env["POINDEXTER_GUI_EXE"], "--book", book], env=no_display,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode != 0 and "X11 display" in result.stderr
        assert book.read_bytes() == expected and not (work / "must-not-exist").exists()

        if all(shutil.which(tool) for tool in ("xvfb-run", "Xvfb", "xauth")):
            subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1024x768x24",
                            test, "--window", worker, book], env=env, check=True, timeout=30)
            assert book.read_bytes() == expected
            print("poindexter_gui_x11=passed private_xvfb")
        else:
            print("poindexter_gui_x11=skipped private_xvfb_tools_unavailable")
    print("poindexter_gui_ok=true native_pixels pointer_edit on1x_recalculation local_save")


if __name__ == "__main__":
    main()
