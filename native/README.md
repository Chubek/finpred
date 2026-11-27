# Native store review target (Linux C11)

[`store.h`](store.h) and [`store.c`](store.c) implement bounded directory-relative
storage for FinPRED artifacts and manifests. This is a standalone C library for
host testing and independent review. The FinPRED CLI still uses its On1x
[private-store protocol](../source/store/README.md) and MuLIB's standard array,
file and BLAKE3 bridges. It does not link this target.

## Build and exercise it

From the FinPRED root, on Linux with C11, kernel headers for `openat2`, CMake,
Python 3, and a GNU-compatible linker for the fault-injection tests:

```sh
mkdir -p build/tmp
export TMPDIR="$PWD/build/tmp"
cmake -S native -B build/native -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
cmake --build build/native --parallel 4
ctest --test-dir build/native --output-on-failure
```

This builds `libfinpred_native_store.a`. Tests create private temporary trees
**on the build directory's filesystem**. Use a local Btrfs, XFS or ext-family
filesystem that implements `O_TMPFILE`, hard links and file/directory `fsync`.
Only Btrfs has been exercised here. The candidate rejects other filesystem
types, including tmpfs, overlayfs and network filesystems. A trusted Linux
procfs mounted at `/proc` is required.

## Host contract

1. The trusted host provisions a private root, durably anchors it from a
   protected parent and passes an open directory fd to `fp_store_open`. The
   fd is borrowed during open; the caller may close it afterward. `FP_READER`
   never creates directories, syncs, or publishes. `FP_WRITER` prepares the
   two direct children and syncs the root before returning a handle.
2. Use `FP_ARTIFACT` or `FP_RUN` and a 64-character lowercase hex ID. Artifacts
   may be empty and are capped at 2 MiB. Both run formats require 404 bytes.
   Text may not contain NUL. Successful reads return an owned `char *` with a
   convenience terminator beyond the reported size; release it with `free`.
   The host remains responsible for digest verification, semantic validation,
   and installing every referenced object successfully **before** the manifest.
3. `fp_store_install` compares or installs one object. A new unnamed inode is
   written and synced before `linkat` creates the final name without replacement.
   An existing file must match byte-for-byte; both identical and new paths
   require a directory sync before success. Identical reuse also syncs the
   file. Short writes advance by the actual byte count. Failed staging has
   no named payload to clean up.
   The unnamed inode is set to mode `0600` before file sync even when the
   host's umask removes owner permissions. If setting that mode fails,
   publication stops before the final name is installed. Existing entries'
   modes are never changed. Hosts provisioning new directories still need a
   umask that preserves owner access.
4. Check `result.status` before issuing a receipt. `phase` locates a failure;
   `name` distinguishes no install by this call, an already existing name,
   a created name, and uncertain installation. For example `{FP_IO,
   FP_DIR_SYNC, FP_CREATED}` means the entry is visible but its persistence
   was not confirmed. Do not roll it back or report a successful run.
   An explicit subsequent install can compare and finish syncing it.
5. `fp_store_close` consumes the handle. Do not share it with an untrusted
   plugin, copy it as an integer, or race close with a borrowed operation.

**Scope and limits.** The root must be owned by the effective user with no
group/other access. Children and regular files must be owned by that user
and not group/other writable; files must have one link. The host controls
the namespace, ACLs, credentials and mounts. Descents use `openat2` with
`RESOLVE_BENEATH`, `NO_XDEV`, `NO_SYMLINKS` and `NO_MAGICLINKS`. For existing
entries the library pins an `O_PATH` fd, validates the inode before data I/O,
and reopens the pinned inode through its own `/proc/self/fd` entry. Procfs is
also used to publish a live unnamed inode without requiring a privileged
`AT_EMPTY_PATH` link. No caller-controlled path goes through procfs.

Two directories remain pinned per handle. At most three extra fds are held in
an install (staged inode plus pin and reader when another writer wins).
Comparisons use an 8 KiB buffer; reads allocate at most one payload plus its
terminator. There are no lock waits. Byte transfers allow at most three
`EINTR` retries total per read/compare (including the EOF probe) or staged
write. An exhausted budget returns `FP_IO` at `FP_READ` or `FP_WRITE`. Other
syscall errors, including errors at installation, sync, or close, are not
retried. Transfer syscalls are bounded by the object limit, an EOF check on
reads, and the retry budget. These are not time limits.

## Process-death regression

`ctest --test-dir build/native -R native_store_process_death -V` uses separate
processes and test-only linker wrappers around real syscalls. With each
artifact and synthetic run, it sends `SIGKILL` after a partial write, after
file sync, after the final name is linked, and after directory sync but before
the caller returns. Readers must observe either absence or exact bytes,
without syncing. Recovery must leave no named staging residue, retain any
visible inode, reject different bytes, and explicitly install or re-sync
identical bytes. The run test installs its referenced artifact first; the
native API does not enforce run lineage.

The same test parks two contenders before `linkat` and a third just after its
successful link. It checks the actual existing-name race: the different
payload cannot replace the winner, and the identical contender must sync the
winning inode and destination directory before reporting success. No sleeps
are used to arrange the interleavings.

## Optional point-in-time evidence

Enable the separate host-only `finpred_native_temporal` C target by adding
`-DFINPRED_TEMPORAL_MULIB_ROOT=/path/to/mulib` to the CMake configure command.
The review dependency is MuLIB `cbb7d66f217f188493f25b38c10101aa26469c48`;
the target uses its C AsOf and BLAKE3 implementations (BLAKE3's header also
links the SHA implementation). It does not need LibStone or `on1xc`, and
does not change the base store ABI or admission status.

[`temporal.h`](temporal.h) offers publish, read-only replay and explicit
resume for the new [temporal evidence contract](../contracts/native.temporal-evidence@1.md).
After validating the commit plan, publication verifies and syncs each
distinct catalog parent, then the catalog, before creating the commit
name. A result's `stage` names the operation that produced its underlying
`fp_result`; if it is not `FP_TEMPORAL_COMMIT`, the underlying name state
describes a prerequisite, not the commit. A commit ID in an error result
is the recomputed plan's ID, not a receipt. `FP_CONFLICT` at validation
also covers the AsOf snapshot rejection: upstream does not separately
report ambiguity and allocation failure.

The optional `native_temporal_oracle_and_recovery` CTest compares exact
bytes against a Python selector/serializer independent of the C selector,
checks published BLAKE3 vectors, and checks which inodes sync before link.
It injects sync failures and kills child publishers before prerequisite
sync, before commit link, after link, and after commit-directory sync.
Read-only replay must never sync. Recovery either reuses the same verified
visible inode or publishes the original plan, without staging debris.

**Admission remains open.** These are live-mount process-death and fault
injection tests, not evidence of persistence across power loss or remount.
The On1x compiler has no callable storage profile for this candidate. See
[STORE_ADMISSION.md](STORE_ADMISSION.md) for the independent review, lowering,
and remaining deployment gates.
