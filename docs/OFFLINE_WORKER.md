# Bounded offline process worker (Linux x86-64)

The optional `finpred-offline-worker` supervisor is a defensive process boundary
for a narrow class of standalone binary workers. It is not enabled by
`bin/finpred`, is not a plugin discovery mechanism, and does not change the
permissions of any existing linked On1x package.

```sh
cmake -S source/sdk/process -B build/offline-worker
cmake --build build/offline-worker
python3 tests/check_offline_worker.py
```

The host requires Linux x86-64, kernel support for Bubblewrap user namespaces,
seccomp, `memfd_create`, and `close_range`, trusted procfs, and a trusted
`/usr/bin/bwrap` with `--disable-userns` and `--perms` support. The check compiles
a static glibc worker, so development files for static libc are needed to run
it. Run without root privileges; install and configure Bubblewrap through the
operator's security policy. Unsupported or denied sandbox setup fails rather
than falling back to ordinary execution.

To diagnose a runner before running the suite, use
`CC=gcc python3 tests/check_offline_worker.py --preflight` (also works with
`CC=clang`). This first checks that the compiler emitted a static x86-64
`ET_EXEC` with no interpreter and then checks one real isolated round trip.
The full test always runs that preflight and the negative probes. If setup
fails, it reports the trusted Bubblewrap error, version and the host's readable
namespace settings. `bwrap --version` alone does not test namespace access.
On an AppArmor-restricted runner, ask the runner administrator to verify that
the packaged launcher has an approved profile for its namespace operations,
or use an approved runner that supports this configuration. Do not disable
namespace restrictions globally, use a privileged launcher, or skip the probe.

## Wire and authority boundary

The trusted caller supplies an absolute path to a regular, non-symlink static
x86-64 ELF executable (non-PIE `ET_EXEC`, no interpreter; up to 8 MiB) and a
finite stdin stream. The supervisor pins the file and copies bounded bytes into
a sealed snapshot; it does not execute the path itself. Use a protected release
directory. This supervisor does not authenticate the author or approve a binary
for use: the caller still owns code identity, selection and review.

Both input and output are a `finpred.offline-worker@1` header with one LF,
followed by binary payload bytes. EOF ends exactly one frame. Each complete
frame is at most 65,536 bytes, including the header. Start a new supervisor
for each call. The worker gets no caller environment, credentials, mount
of application data, network capability, or external-action authority. Only
stdin and stdout are available for protocol I/O. Return bytes remain untrusted:
an application host must validate contract kinds, semantics, identities,
cutoffs and lineage after a successful call. A valid header is not a
publication, approval token, or compatibility verdict.

## Enforced limits

- Bubblewrap creates a separate namespace set, drops capabilities and
  disables nested user namespaces. The read-only root contains only the
  sealed worker copy with no shell, libraries, or mounted procfs.
- The supervisor closes inherited nonprotocol descriptors before sandbox
  setup, clears ambient capabilities and sets `no_new_privs` before launching
  Bubblewrap, passes a sealed request,
  and supplies an x86-64 syscall allowlist permitting only the protocol
  descriptors for I/O. Stderr carries launcher diagnostics, not worker I/O.
  The worker cannot
  acquire files, sockets, subprocesses, or effect handles. Anonymous virtual
  memory allocation remains available.
- The child has a 128 MiB address-space ceiling, one CPU second and no core
  dumps. The supervisor enforces a two-second execution and capture deadline,
  **after** acquiring the executable and complete input from the trusted caller
  and before delivery of a validated response. On failure it
  kills and reaps the sandbox launcher as needed; Bubblewrap propagates
  parent death to the worker. Stdout is buffered until the child exits zero
  and its complete response passes framing and size checks.

The local regression runs the real isolation boundary and tests successful
binary transport, forbidden operations, memory denial, invalid or oversized
frames, failure after partial output and termination of spinning work. It
does not attest the host kernel or Bubblewrap, verify other architectures,
grant trusted in-process plugins sandbox properties, or certify this profile
for a production multi-tenant service.
