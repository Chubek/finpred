# Local publication protocol

The store runs on a local POSIX filesystem under an operator-controlled
`FINPRED_HOME`. Use a private directory and protect its ancestors. All writers
must use the same reservation protocol. Replay reads only published paths.

`put_at` publishes bytes at a host-selected artifact or manifest name.
The Yieldcraft CLI only writes v2 manifests; it can still read v1 archives
at their original paths. A byte-identical existing file is reused without
changing its inode or creating a reservation. A different file at that name
is an immutable conflict.

1. Reserve a missing destination by creating the sibling directory
   `<destination>.pending` with `mkdir`. Only its creator may write inside it.
2. Recheck the destination: another writer may have completed before this
   process acquired the reservation. Otherwise write `payload` inside the new
   empty directory and check the result (including `fclose`).
3. Rename the closed file into place on the same filesystem, then remove the
   empty reservation. The CLI publishes the run manifest last.

Readers see either no entry or a complete file across a writer process exit.
A competing writer can reuse the completed file or fail with `publication
reservation unavailable`. Failure also covers an inaccessible reservation:
the stdlib returns a boolean, not `errno`. There is no automatic retry.

For errors on a validated key, `artifact:` identifies a snapshot and
`run:` a manifest (`replay:` for the manifest length and directory checks).
`key=` gives its digest or run ID. For example, `run: staged
write failed; key=<id>` identifies the manifest attempt, not a failed
write of one of its parents. Errors raised inside the stdlib, such as NUL
in text input, retain the runtime's own diagnostic.

`store: expected directory: home|artifacts|runs` identifies a non-directory
at that position. A writer checks all three positions before creating
missing directories. A reader checks the relevant parent on a failed
lookup, reporting `directory unavailable` when it cannot confirm the
directory exists. If it sees a `.pending` name but no published entry,
it reports `publication reservation present; no published entry observed`.
These are observations, not a determination that a writer has died.
Readers do not open staged payloads or create missing directories.

If a staged write (including close) or rename **returns failure**, the
writer removes its own `payload` and empty reservation before reporting
the error. No final file is removed. A cleanup error is explicit; if the
rename succeeded but removing the reservation failed, the diagnostic says
`file published`. Abrupt process exit can still leave a reservation.

**Recovery:** stop all writers first. Inspect the store. A `.pending`
directory left by a stopped process may contain an incomplete `payload`, or
it may be empty if the rename already succeeded. Remove only the known
abandoned payload and its directory; never promote a staged file. Rerun
with the original inputs and verify with replay. Completed, unreferenced
artifacts left before a manifest commit can be reused. A conflict at a
published name is an integrity failure, not an invitation to overwrite it.

## Boundaries of this protocol

At MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
`on1x/stdlib/os/OS_FileSys.on1x`, `io/TextIO.on1x` and their
`runtime/basis_native.c` bridge expose `stat`, `mkdir`, `fwrite`/`fclose`,
`rename` and `remove`. These are the existing trusted SDK bridges used by
the project, not independently admitted storage kernels.

- POSIX rename gives **atomic visibility**, not power-loss durability:
  there is no file or directory `fsync` in these interfaces.
- Exclusive `mkdir` serializes **cooperating** publishers per name. The
  rename itself is not no-replace. This protocol cannot exclude a legacy
  writer or another program that modifies final names directly.
- Store keys are checked lowercase hex, but `stat` and reads follow
  symlinks. The interfaces have no `lstat` or trusted directory descriptors
  with which to reject symlink traversal and path swaps. Never use this
  store in a directory writable by an untrusted party. Neither the reservation
  nor the content digest establishes filesystem confinement.
- Full P1 needs a reviewed, bounded directory-relative interface for regular
  files, no-follow opens, no-replace publication, and file/directory sync.
  See the [admission decision and required interface](../../native/STORE_ADMISSION.md)
  for compiler evidence, error outcomes, publication ordering and acceptance
  tests. No new native adapter or build dependency is used here.

The optional [native temporal evidence review target](../../native/README.md#optional-point-in-time-evidence)
is separate from this On1x protocol. It establishes parent-before-commit
ordering for its new point-in-time format only; it does not migrate or
grant native storage access to the CLI.

## Short-write regression (Linux)

From the project root, build with `bin/build.sh` and run
`python3 tests/check_write_failure.py`. It forces a real 404-byte
manifest write to hit a 128-byte `RLIMIT_FSIZE`, with `SIGXFSZ` ignored so the
writer can handle the error. The CLI must fail without a committed manifest
or stale reservation; a normal retry must reproduce the original bytes and
replay successfully.

`python3 tests/check_store_publication_status.py` checks known bad layouts,
directory-valued entries and keyed errors, then exercises two distinct
failure paths: a handled short write of the first raw snapshot, and an
actual `SIGXFSZ` exit during the final manifest write. The latter verifies
read-only rejection of the pending manifest, offline cleanup after the
writer exits and byte-identical recovery of the committed store.

Verification (2026-11-23): in an isolated archive of `af96ea7` plus the
store changes, the focused status test, `bin/build.sh`, `tests/run.sh`,
`python3 tests/check_fixtures.py` and `python3 tests/validate_static.py`
all exited 0 on Linux x86-64 with GCC 16.2.1 and
`third_party/mulib/build/on1x/on1xc` at the pin above. Baseline reproduction:
a file at `runs` caused `run` to leave a new `artifacts/` sibling;
replay of that layout returned `unknown id`. A directory at a raw input's
published name produced the runtime's `input read failure`.

Verification (2026-11-23): in a scratch copy of the P1 tree with `MULIB_ROOT`
pointing to the pinned checkout and `TMPDIR` on the scratch volume,
`bin/build.sh`, `python3 tests/check_fixtures.py`, `python3 tests/validate_static.py`,
the short-write regression and `tests/run.sh` all exited 0. The same focused
regression failed on the pre-fix binary (write error reported, `.pending`
still present). Both archived v1 runs replayed, and the v2 fixtures remained
17,100 and 16,000 cents/night with `published=false`. These were process-level
checks on Linux x86-64, not hostile-directory or power-loss tests.
