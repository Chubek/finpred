# Poindexter GUI (optional)

This is a Linux X11 spreadsheet for **local editable working copies**. It uses the
pinned MuLIB native ImmGTK widgets, hit testing, font and software framebuffer.
Despite the name, ImmGTK does **not** require GTK, OpenGL, Lua or a GPU. Xlib
presents the completed framebuffer and receives keyboard and pointer events.

## Build and run

Use the [pinned MuLIB and On1x toolchain](../../../INSTALL.md). The optional C11
host build needs Bash, a C compiler, `pkg-config` and the Xlib development package
(`libx11-dev` on Debian, `libx11` on Arch). There is no GUI dependency in the
FinPRED CLI or the terminal workbench.

```sh
export MULIB_ROOT="${MULIB_ROOT:-$PWD/third_party/mulib}"
export TMPDIR="$PWD/build"
mkdir -p "$TMPDIR"
./bin/poindexter --build
bash plugins/poindexter/gui/build.sh
./target/poindexter/poindexter-gui --book ./prices.pxw
```

`POINDEXTER_GUI_EXE` sets the build output path; `CC` selects the C compiler.
At launch the GUI defaults to the `poindexter-grid` executable next to it.
Set `POINDEXTER_EXE` to the path to a **trusted** compatible worker to override
that. Running the GUI requires a reachable X11 display with a standard
24-bit RGB TrueColor visual (Xwayland can also supply this). The window uses
a fixed 720×480 canvas and the worksheet's printable ASCII input.

Click a cell or use the arrow keys. Page Up/Down moves a viewport, and
Home/End outside edit mode jumps to A1/P64. Press Enter or F2 to edit the formula
bar, then Enter to apply or Esc to cancel. Try entering `17500` in A1, `17100`
in B1, and `=B1-A1` in C1. C1 displays `-400` and recalculates when B1 changes.
Save or Ctrl+S writes the workbook; nothing is saved on open or on edit.
Quit or Ctrl+Q asks for a second quit if there are unsaved changes.

An absent book starts empty and is created only on Save. For verified pricing
data, make a **separate** worksheet copy first with the [terminal
workbench](../workbench/README.md) and then open that book in the GUI. The GUI
does not accept run IDs, import source data, execute scripts, access FinPRED's
run store or publish recommendations. It does not add clipboard support,
multi-writer merging or concurrent editing.

## Process boundary and verification

There is no On1x FFI or KernelBind admission. The single-threaded C host invokes
the unchanged compiled On1x worker via `execve` with a restricted environment
and fixed `check`, `frame` and `edit` operations. Cell source is an environment
value, never shell or Lua code. The worker owns workbook validation, encoding,
formula evaluation and errors; the host consumes the bounded `frame` output
(four cells × up to twelve rows per page, plus selected source and value).
No native struct or pointer crosses the process boundary. GUI session files
are private, and successful edits replace the working copy only after the
worker also evaluates the resulting page. Save copies the worker's encoded
workbook into a same-directory temporary file and renames it over the selected
local path. Use a private directory and one editor per workbook: this is not
a filesystem sandbox, worker isolation policy or power-loss durability
guarantee. The host waits synchronously for its trusted worker. An abnormal
termination can leave private temporary files in `TMPDIR`.

```sh
TMPDIR="$PWD/build" python3 tests/check_poindexter_gui.py
```

The test builds both the optional GUI and the pinned On1x worker by default,
exercises actual software-rendered pixels and ImmGTK pointer input without
a display, edits and recalculates in On1x, and reloads the saved workbook in
the existing terminal frontend. It also rejects malformed/nonregular
books and checks that rejected edits and unsaved changes do not write the
selected book. When `xvfb-run` and `xauth` are available, it verifies X11
presentation by reading back pixels on a private Xvfb server. Otherwise
it reports that extra smoke test as skipped and does not touch the user's display.
