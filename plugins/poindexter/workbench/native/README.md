# Poindexter text viewport — C11 review candidate

This standalone renderer turns trusted, already formatted text into **in-memory
ANSI diffs**. It is not linked by Poindexter or FinPRED, and does not open or
write a terminal, select a terminfo path, handle input, or own workbook files.
The current Bash/On1x workbench is unchanged.

## Candidate C API

[`viewport.h`](viewport.h) is a same-target C11 source interface, not a stable
binary ABI or a KernelBind profile. The handle is opaque; sizes/lengths use
native `size_t`, and the result record and status enum have normal target C
alignment and representation. Tested target: Linux x86-64 (8-bit bytes).

- `px_viewport_create` creates one owned handle, initially blank with a hidden
  cursor. Size is fixed until `px_viewport_destroy`; do not copy an owned handle
  or destroy it more than once. Destroying `NULL` does nothing.
- `px_viewport_set_text` replaces the pending frame. The caller supplies a
  readable span for the duration of the call; the candidate retains no pointer.
  Only bytes `0x20`–`0x7e` and LF are accepted. There is no UTF-8 layout,
  tab expansion, or interpretation of escape sequences. LF separates rows.
  Lines are clipped at the right edge (never wrapped); rows past the bottom
  are clipped. Unfilled cells are spaces. All supplied bytes, including clipped
  text, are validated before mutation. `NULL, 0` requests a blank frame.
- `px_viewport_render` captures a full first frame or a changed-cell diff.
  `{NULL, 0}` means no visual change. Nonempty bytes are read-only and borrowed
  until the next successful render or destroy on that handle. Copy them if a
  longer lifetime is needed. Success advances the comparison framebuffer,
  not any terminal. Subsequent diffs assume earlier batches were applied in
  order to the same in-memory receiver; there is no transport recovery API.

The limits are 1–240 columns, 1–80 rows (at most 19,200 cells per buffer), and
32,768 input bytes per frame. With default style, each changed run uses one
cursor address of at most 9 bytes, then one byte per changed cell, plus fixed
reset/hide sequences. Even charging for a separate run at every cell bounds
captured data to under 200 KiB per render. Renders do not accumulate a history.

`PX_VIEWPORT_ARGUMENT`, `PX_VIEWPORT_LIMIT`, and `PX_VIEWPORT_TEXT` distinguish
null arguments, exceeded limits (including zero dimensions), and disallowed
bytes. `PX_VIEWPORT_BACKEND` indicates setup or rendering failure; a failed
render can be retried with the same pending frame. Errors leave caller output
records and existing pending/rendered state untouched. Callers must supply
valid live handles and naturally aligned, writable output records that do not
alias internal storage. Serialize calls and use of borrowed bytes on a given
handle; this API does not defend against arbitrary invalid C pointers.

[`viewport.c`](viewport.c) is the only implementation translation unit for the
pinned MuLIB GRID, UTF8, STRBUF, TERMINFO, VTERM and TUI switches. Do not link
another copy of those implementations into the same executable. The terminfo
implementation includes a file loader, but the candidate calls `mulib_tui_render`
with `NULL` for the built-in ANSI fallback and never uses the loader. This is
not process isolation. **Native tests are not independent review or
KernelBind admission**; there is no compiled On1x import or live TUI backend.

## Reproduce the native tests

From the FinPRED root, point `MULIB_ROOT` at MuLIB
`49de89acbc97efbee493d6b28d02c8f64ed4f725`. CMake uses that checkout's real
headers; it does not fetch dependencies or verify the checkout revision.
LibStone and `on1xc` are not needed for the native build.

```sh
export TMPDIR="$PWD/build"
export MULIB_ROOT="$PWD/build/s0.rkjIOB6G/project/third_party/mulib"
git -C "$MULIB_ROOT" rev-parse HEAD
review=plugins/poindexter/workbench/native
cmake -S "$review" -B "$review/.build" -DMULIB_ROOT="$MULIB_ROOT" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
cmake --build "$review/.build" --parallel 4
ctest --test-dir "$review/.build" --output-on-failure
```

Three CTests check exact ANSI bytes and replay them into a separate MuLIB vterm
screen for visible clipping, blanking and zero-byte diffs; malformed/control
bytes (including beyond the clip) and rejected arguments preserving a pending
frame and prior capture; and zero, over-limit, and exact maximum bounds.
Observed 3/3 passing with GCC 16.2.1 Release and with Clang 22.1.8
AddressSanitizer/UndefinedBehaviorSanitizer. Allocator failures and real
terminal behavior are not tested.
