# Poindexter terminal spreadsheet

Build the On1x worksheet engine with the [pinned compiler](../../../INSTALL.md),
then launch the terminal grid (Linux, Bash, ANSI terminal):

```sh
./bin/poindexter --build
./bin/poindexter --book prices.pxw
```

An absent workbook starts empty. Try editing `A1` to `17500`, `B1` to
`17100`, and `C1` to `=B1-A1`. The grid displays `-400`; the formula bar
shows the original expression. Edit `B1` again and the difference updates.
Press `s` to save formulas as well as values.

The terminal title uses the On1x `std.tty` facade, backed by MuLIB terminfo
and terminal styling. Unsupported terminal styles and `NO_COLOR` fall
back to a plain title. The GUI still reads the original unstyled frame
format.

Direct `import kernel` for MuLIB's TUI headers is not currently admitted
by the pinned On1x compiler. The terminal facade is part of the pinned
standard library, not proof of a safe `mulib.tui` KernelBind profile.
`import kernel[dynlib]` does not grant admission; a compatible compiler
must also provide a reviewed callable TUI profile.

To check the boundary and terminal behavior on a local build:

```sh
python3 tests/check_tui_kernel_admission.py --expect-dynlib-syntax
python3 tests/check_poindexter_tty.py
```

The checked-in compiler pin recognizes `kernel[dynlib]` syntax but still
refuses TUI admission. Omit `--expect-dynlib-syntax` only when reproducing
the historical pin that rejected that spelling at parse time.

`make poindexter-tui-review` exercises the separate
[native viewport candidate](native/README.md) using `mulib-tui.h`.
It does not install or link a production workbench backend.

| Key | Action |
|---|---|
| Arrows or `h j k l` | Move; the viewport follows the selection |
| `g` | Go to an address, e.g. `K20` |
| Enter or `e`, `d` | Edit the cell source, or clear it |
| `y`, `p` | Copy and paste a cell, translating relative references |
| `u`, `r` | Undo/redo the most recent edit, paste, or entire script |
| `x`, `@` | Execute a worksheet statement or a multiline script file |
| `s`, `q`, `?` | Save, quit, quick reference |

## Start with a verified pricing run

```sh
summary=$(./bin/finpred run)
id=$(printf '%s\n' "$summary" | sed -n 's/^run_id=//p')
./bin/poindexter --run "$id" --book analysis.pxw
```

Use the same `FINPRED_HOME`. Import calls `bin/finpred poindexter` and
requires successful replay before any cells are created. Row 1 contains
the pricing headers; `G2`, `H2` and `I2` contain current, recommended and
change in nightly EUR cents. Run and artifact references are text cells.
For a v3 own-demand run, `L2` identifies the frozen demand CSV; `M2` is
marginal cost in cents per room-night, `N2` is expected room-nights × 1000,
and `P2` is the scale (`1000`). `O2` preserves the modeled contribution
total as exact `milli_minor:<decimal>` text, even when it is too large
for worksheet arithmetic. See the [v3 column definitions](../README.md#v3-own-demand-contribution-sheet).

The imported row is an **editable working copy**. Subsequent values,
scenarios, and exports are worksheet data, not verified recommendations or
evidence; the values do not stay linked to the archived run.

## Cells and formulas

Addresses run from **A1 to P64**. Each cell holds up to 192 printable ASCII
bytes of source. Enter an integer, a text label, or a formula beginning
with `=`. Prefix an entry with `'` to force text (e.g. `'00123` or `'=A1`).
Names and references are case-insensitive.

| Example | Result or meaning |
|---|---|
| `=(H2-G2)*7` | Seven-night difference in cents |
| `=ROUNDDIV(H2*105,100)` | Apply 5% and round to nearest cent; ties away from zero |
| `=SUM(B3:B12)` | Sum a rectangular range; `MIN`, `MAX`, `COUNT`, `AVG`/`AVERAGE` also take one range |
| `=IF(G2>0,H2*100/G2,0)` | Evaluate only the selected branch |
| `=ABS(I2)` | Absolute change |
| `=$B2+C$1+$A$1` | Column, row, and fully anchored references for copying |
| `=ROW()*COL()` | One-based coordinates of the formula cell |

Arithmetic uses signed integers in **±10¹⁵**, never binary floating-point
money. `+ - * / %`, unary signs, parentheses, and comparisons (`=`, `!=`,
`<>`, `<`, `<=`, `>`, `>=`) are supported. `/` and `AVG` truncate toward
zero; comparisons return 0 or 1. A blank reference contributes zero;
referencing text in arithmetic yields `#VALUE!`. Aggregates ignore blank
and text cells; an empty average yields `#DIV/0!`. Errors such as `#REF!`,
`#CYCLE!`, `#NUM!` and `#SYNTAX!` are displayed in the grid. Fix the source
to recalculate. Evaluation has a bounded nesting/dependency stack and a
per-operation work budget.

## Worksheet code

`x` runs one statement. Use `@` for a file with one statement per line.
For example, with an imported run:

```text
LET X = H2
REPEAT 3
  LET X = ROUNDDIV($X*101,100)
END
SET B5 = $X
FORMULA C5 = B5-$H$2
IF C5 > 0
  TEXT A5 Projected increase
ELSE
  TEXT A5 No increase
END
ASSERT B5 >= H2
```

- `LET X = expr` sets one of 26 script-local integers (`$A`…`$Z`).
- `SET B5 = expr` stores the **computed integer**. `FORMULA B5 = expr`
  stores a **live formula**. Persistent formulas cannot use script locals.
- `TEXT A5 label` stores literal text. `CLEAR A5:B8` empties a rectangle.
- `FILL B5:B11 = expr` sets the same formula in every destination. Use
  `ROW()` or `COL()` for per-cell coordinates. `COPY B5 B6:B11` instead
  translates the source's relative references, retaining `$` anchors.
- `IF expr` / optional `ELSE` / `END`, `REPEAT expr` / `END`, and
  `ASSERT expr` provide control flow. `#` starts a full-line comment.

A script commits as one edit. An invalid statement, failed assertion,
out-of-grid copy or budget error leaves the previous book intact. Code has
only worksheet operations. It cannot execute shell commands or open files.
Limits: 128 lines of up to 256 bytes, eight nested blocks, 256 iterations
per repeat, 4,096 executed statements and 250,000 evaluation/work ticks.

## Batch use and CSV

```sh
# A verified run, a seven-night pricing scenario, and a new saved workbook:
./bin/poindexter --run "$id" --book week.pxw \
  --script plugins/poindexter/workbench/examples/price-check.pxs --get B12
# Default fixture: 121800 (scenario total, EUR cents).
./bin/poindexter --book week.pxw --get H2
./bin/poindexter --book week.pxw --csv > week.csv
./bin/poindexter --import-csv other.csv --book imported.pxw
```

CSV import accepts printable ASCII, quoted fields with doubled quotes,
commas, and LF/CRLF record endings. It imports **values**, never executable
formulas. Noncanonical numbers such as `0042` stay text. Multiline fields
are unsupported. Export writes evaluated display values over the used
rectangle, including text and error markers, not the cell sources.

The separate `poindexter-workbook@1` format preserves original formulas:
a header plus one `address<TAB>source` line per nonempty cell. The terminal
host stages saves in the destination directory. It checks existing books
against their exact bytes when opened or last saved, and creates new books
without replacing files that appear at the chosen path. On a save conflict
the terminal keeps unsaved edits and warns before discarding them. A failed
batch save does not print a result.

Use a separate local file for each editor. The existing-file check detects
stale content but does not lock the path between comparison and replacement.
New saves need a filesystem that supports hard links; there is no overwrite
fallback. A seed import refuses to replace an existing book. With `--script`
or a seed import plus a batch output option, `--book` saves the new state on
success. With neither, the batch result is printed without modifying the
input book.

The Bash host handles terminal keys, selected files, and session state.
Parsing, evaluation, relative copy, program execution, and table rendering
run in the compiled On1x worker. `POINDEXTER_EXE` selects a different
prebuilt worker. To verify it, build both CLIs and run
`python3 tests/check_poindexter_workbench.py` (includes a pseudo-terminal session).
