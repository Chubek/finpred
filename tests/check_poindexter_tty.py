#!/usr/bin/env python3
"""Build the real worksheet worker and check frames on pipes and a private PTY."""
import errno
import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "plugins/poindexter/workbench"
BOOK = b"poindexter-workbook@1\nA1\t4\nB1\t=A1*7\nA2\t'label\n"
FRAME = (
    b"     | A           | B           \n"
    b"1    | 4           |>28          \n"
    b"2    | label       |             \n"
    b"\nB1  fx: =A1*7\nValue: 28\n"
)
CLEAN = b"POINDEXTER   Worksheet   |   B1\n\n" + FRAME
DIRTY = b"POINDEXTER   Worksheet *   |   B1\n\n" + FRAME
# One xterm reset also restores the default character set (ESC ( B).
STYLE = re.compile(rb"\x1b(?:\[[0-9;:]*m|\(B)")
CYAN = re.compile(rb"\x1b\[(?:[0-9]+;)*36(?:;[0-9]+)*m|\x1b\[38[;:]5[;:]6m")


def snapshot(root):
    # Ignore atime: reading a workbook can legitimately update it.
    state = {}
    for path in [root, *sorted(root.rglob("*"))]:
        st = path.lstat()
        state[path.relative_to(root)] = (
            st.st_mode, st.st_ino, st.st_mtime_ns, st.st_ctime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return state


def read_pty(master):
    output = bytearray()
    deadline = time.monotonic() + 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
            raise AssertionError(f"worksheet PTY did not close: {output!r}")
        try:
            chunk = os.read(master, 4096)
        except OSError as exc:
            if exc.errno != errno.EIO:  # Linux signals slave closure with EIO.
                raise
            break
        if not chunk:
            break
        output.extend(chunk)
        assert len(output) < 8192, "worksheet PTY emitted more than one bounded frame"
    return bytes(output)


def main():
    sdk = Path(os.environ.get("MULIB_ROOT", ROOT / "third_party/mulib")).resolve()
    compiler = Path(os.environ.get("ON1XC", ROOT / "build/mulib/on1x/on1xc")).resolve()
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("PX_", "FINPRED_"))
        and k not in {"NO_COLOR", "COLORTERM", "TERMINFO", "TERMINFO_DIRS", "DISPLAY",
                      "WAYLAND_DISPLAY"}
    }
    with tempfile.TemporaryDirectory(prefix="finpred-poindexter-tty-") as tmp:
        d = Path(tmp)
        out = d / "out"
        subprocess.run([
            sys.executable, sdk / "on1x/tools/on1x-project.py", "build", WORKBENCH,
            "--on1xc", compiler, "--mulib-root", sdk, "--offline", "--output-dir", out,
        ], check=True, cwd=d, timeout=180)
        exe = out / "poindexter-grid"
        data = d / "data"
        data.mkdir()
        book, store, home = (data / name for name in ("book", "store", "home"))
        book.write_bytes(BOOK)
        store.mkdir()
        (store / "sentinel").write_bytes(b"unchanged\n")
        home.mkdir()
        env.update(PX_BOOK=str(book), PX_CELL="B1", PX_ROWS="2", PX_COLS="2",
                   HOME=str(home), TMPDIR=str(home), FINPRED_HOME=str(store), TERM="xterm")
        before = snapshot(data)

        def pipe(op, **extra):
            proc = subprocess.run(
                [exe], cwd=data, env={**env, "PX_OP": op, **extra}, start_new_session=True,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
            )
            assert proc.returncode == 0 and proc.stderr == b"", proc
            assert all(c == 10 or 32 <= c <= 126 for c in proc.stdout), proc.stdout
            return proc.stdout

        assert pipe("frame") == FRAME
        assert pipe("terminal_frame") == CLEAN
        assert pipe("terminal_frame", PX_DIRTY="1") == DIRTY

        master, slave = pty.openpty()
        try:
            slave_name = os.ttyname(slave)
        finally:
            os.close(slave)

        def terminal(op, **extra):
            # Reopen the same private slave per call so the master can observe EOF.
            fd = os.open(slave_name, os.O_RDWR | os.O_NOCTTY)
            try:
                attrs = termios.tcgetattr(fd)
                attrs[1] &= ~termios.OPOST  # Compare exact LF bytes, not PTY CRLF.
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
                proc = subprocess.Popen(
                    [exe], cwd=data, env={**env, "PX_OP": op, **extra}, start_new_session=True,
                    stdin=subprocess.DEVNULL, stdout=fd, stderr=subprocess.PIPE,
                )
            finally:
                os.close(fd)
            with proc:
                try:
                    output = read_pty(master)
                    _, error = proc.communicate(timeout=10)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                assert proc.returncode == 0 and error == b"", (op, extra, proc.returncode, error)
            return output

        try:
            assert terminal("frame", PX_DIRTY="1") == FRAME
            # The pinned runtime supports xterm even without a terminfo database
            # via its known ANSI family. Check both the regular name and fallback.
            for term in ("xterm", "xterm-finpred-test-no-entry"):
                rendered = terminal("terminal_frame", TERM=term)
                prefix, name, suffix = rendered.partition(b"POINDEXTER")
                assert name and CYAN.search(prefix) and STYLE.sub(b"", prefix) == b"", rendered
                styled_tail, sep, tail = suffix.partition(b"   Worksheet")
                assert styled_tail and STYLE.sub(b"", styled_tail) == b"", rendered
                assert name + sep + tail == CLEAN, rendered
            assert terminal("terminal_frame", NO_COLOR="") == CLEAN
            assert terminal("terminal_frame", NO_COLOR="1", PX_DIRTY="1") == DIRTY
            assert terminal("terminal_frame", TERM="dumb") == CLEAN
        finally:
            os.close(master)

        assert snapshot(data) == before, "rendering changed workbook, store, or data tree"
    print("poindexter_tty_ok=true pipe_cases=3 pty_cases=6 exact_frame formula dirty no_writes")


if __name__ == "__main__":
    main()
