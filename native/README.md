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
terminator. There are no lock waits or automatic retries on syscall errors.
Transfer loops require positive progress, so even one-byte transfers are
bounded by the object limit plus one EOF check. These are not time limits.

**Admission remains open.** Native tests exercise actual filesystem behaviour
and injected errors; they are not power-cut/remount tests. The pinned On1x
compiler has no callable storage profile. See [STORE_ADMISSION.md](STORE_ADMISSION.md)
for the independent review, lowering, and remaining deployment gates.
