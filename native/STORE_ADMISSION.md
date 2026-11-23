# Decision: durable local publication is not admitted

**Status:** blocked on an upstream callable filesystem profile and independent
review. This is the contract to submit for review, not an ABI or a supported
build option. The existing [private-store protocol](../source/store/README.md)
provides atomic visibility among cooperating publishers, not durable commits.

## Evidence at the pin

MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`, Linux x86-64 C11:

| Candidate | What actually executes |
| --- | --- |
| `on1x/stdlib/{os/OS_FileSys,io/TextIO}.on1x` | `stdlib/runtime/basis_native.c` uses path-based `stat`, `mkdir`, `remove`, `rename`, `fopen("wb")`, `fwrite`, `fclose`; `runtime/on1x_runtime.c:on1x_tool_read_file` uses `fopen("rb")`. No directory handle, regular-file predicate, no-replace flag, or sync. `stdlib/catalog/substructures/Posix.FileSys.json` is explicitly `catalog_only`. |
| MuLIB headers | `manual/mulib-fs.md` specifies truncation. `manual/mulib-artifact.md` describes envelopes, not publication. `manual/mulib-kvdb.md` describes an fsynced **replacement** in a trusted stable parent and an uncertain result on directory sync failure. None is an equivalent FinPRED publication primitive. |
| Project/SDK tools | `on1x/tools/on1x-project.py` and `on1x-contracts.py` use Linux no-replace for their own build outputs. These are not exports linked into an On1x program. |
| KernelBind | `on1x/src/loader.cpp`'s `options.kernel_c11` branch restricts staged safe requests to `mulib.clamp`, `mulib.histprice`, `mulib.priceopt`; raw requests to clamp/framed only. `on1x/KERNEL_DIRECT_USAGE.md` §9.5 explicitly leaves I/O composition unadmitted. `on1x/docs/kernel-review.md` requires an operator-selected independent signer; annotations and test keys do not authorize storage. |

Compiler check (replace `fs` with `kvdb`, `artifact` or `filectl` for
the other candidates). In a scratch directory with `MULIB_ROOT` set:

```sh
printf 'import kernel mulib.fs as Candidate;\nfn main() {}\n' >candidate.on1x
"$MULIB_ROOT/build/on1x/on1xc" --emit-c --kernel-c11 --kernel-stage candidate.on1x
```

Each exited **1**, `ON1X-KERNEL-NOT-ADMITTED`. Staging itself isn't approval.
Supplying a review key to this compiler cannot add an absent lowering.

## Required operations (semantic signatures, not On1x syntax)

The host delegates one pinned store root, read-only for `replay`/`explain`,
read/publish for `run`. The host provisions and durably anchors the root from
a trusted parent. Opening its children must be relative to that root.

| Operation | Contract |
| --- | --- |
| `open(grant) → owned Store` | Pin `artifacts` and `runs` as directories with close-on-exec. A writer may create missing children privately and sync the containing directory, including when another writer just created a child. A reader must never create/repair anything. The grant is not a path string or untyped integer; callers cannot mint or upgrade it. |
| `read(store, kind, id) → owned text` | `kind` is exactly `artifact` or `run`; `id` exactly 64 lowercase hex bytes. Internally derive the existing basename. Return only complete NUL-free bytes, no implicit newline. Artifact limit 2,097,152 bytes inclusive; run exactly 404 bytes. Check the limit during the read (including EOF), not just by initial `stat`. On1x verifies BLAKE3 and canonical v1/v2 manifest and replay semantics as today. |
| `install(write_store, kind, id, text) → CreatedDurable \| IdenticalDurable` | Apply the same key/size/text bounds before allocation or staging. On1x supplies the digest of the artifact, **not** a digest of the manifest for a run ID. Compare complete bytes before reusing an existing entry. No arbitrary filename, replacement, delete, chmod, subprocess or network operation. |
| `close(owned Store)` | Consume once. All call-local descriptors and buffers are released on every outcome; borrows end at return. No callbacks, retained On1x string pointers, process-global fd numbers, or native handles exposed to strategies. |

**Confinement.** Reject symlinks (including dangling and magic links) at all
components, `..`, mount escapes and non-directories during descent. Validate
type on a pinned object before any data I/O; reject directories, sockets,
devices and FIFOs without opening devices for data or waiting on a FIFO. The
descriptor read must address the **same inode** checked. Require dedicated
host-owned regular files/directories, appropriate ownership/ACLs, and reject
external hard-link aliases. Specify the supported local filesystems and
kernel features; fail closed on unsupported semantics. Descriptor confinement
does not stop someone with directory write permission from unlinking a
committed name or moving a directory. Require a protected namespace for
persistence; refuse to issue a durability receipt for an attacker-mutable
namespace. Digest checks are integrity checks, not creator authentication.

**Ordering on a supported filesystem:**

1. Prepare a fresh private inode on the destination filesystem; no opening
   or truncating a preexisting stage. Prefer an unnamed stage linked by
   descriptor, or a protected staging directory and an atomic
   `RENAME_NOREPLACE` transfer. Bind writes and sync to the same descriptor.
   Use a length-checked write loop, reject zero progress, check flush/close
   as applicable. Sync file data and metadata before installation.
2. Commit the final name atomically only if absent. On `EEXIST`, open the
   existing file by the same confined rules and compare all bytes. A mismatch
   is `Conflict`. For **identical** bytes (including legacy files), sync the
   existing file and destination directory before returning durable success:
   another process could have stopped between install and directory sync.
   Never infer durability from a successful equality check.
3. Sync the destination directory after installation. For a cross-directory
   rename also sync the staging directory for durable cleanup. Keep cleanup
   status distinct from final-name durability. Only release/unlink this
   attempt's own stage. No recursive scavenger or deleting final paths.
4. FinPRED installs every referenced object (including all normalized objects
   and v2 lineage) to durable success before installing the manifest. Never
   print a successful run for an uncertain manifest. Old v1/v2 keys, bytes,
   replay and `published=false` remain unchanged. Read-only replay checks
   bytes; it cannot certify a past sync or promote an uncertain commit.

**Errors and bounds.** Distinguish invalid key/text, unauthorized, scope/type
violation, missing, conflict, limit, unsupported, and I/O failure. Report the
phase and whether the final name is known absent from this attempt, already
present, or installation/durability is uncertain (e.g. after install but before
successful parent sync). No blind retry/rollback after uncertainty. A later
explicit install can revalidate identical content and complete the sync.
Read one object per call; cap scratch at one bounded payload plus fixed
metadata; stream comparisons in fixed chunks. At most three persistent dirfds
per grant, a fixed documented per-call descriptor and syscall-retry budget,
no unbounded temp-name search, waits for locks, or recursive directory walk.
Bounded data and retries do not imply a wall-clock deadline for filesystem I/O.

## Acceptance before enabling a writer

1. Supply a canonical upstream profile and target-specific declarations,
   ExoML ownership/effects/errors, compiler lowering for the sealed grant and
   typed outcomes, and one implementation-TU plan. Pin the header/closure,
   toolchain, generated adapter, flags, OS/ABI and filesystem assumptions.
   Have the accountable independent reviewer sign this exact subject; select
   the trust key outside the project. Reject missing, stale, test-only or
   mismatched evidence. No fallback from this profile to plain `rename`.
2. Execute the **compiled On1x** harness with positive and negative grants;
   verified bytes at both size bounds; traversal, swapped entries, links,
   special files, same/different bytes under contention; and descriptor and
   memory accounting on every exit. Check the outside sentinel is untouched,
   readers never observe partial data, and replay never writes or syncs.
3. Inject short write, full disk, interrupt, close failure, file/dir sync
   failure, and process exit before/after each publication boundary. Verify
   named outcome and permissible residue, including another writer reusing a
   visible but unsynced object. Separately test simulated power loss on each
   claimed filesystem: every acknowledged manifest and all its referenced
   bytes survive remount. `kill` alone only tests process death.
4. Run the real On1xfile build and FinPRED integration suite, including both
   legacy v1 replays and byte-identical v2 results. Archive review/build locks
   and crash-test evidence. Until then use the existing private-store mode.
