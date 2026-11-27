# Core overhaul verification

## Baseline and release gates

The baseline is FinPRED `f2fc160349a8e83e62ede88557c9a4cb026387d3`,
MuLIB `cbb7d66f217f188493f25b38c10101aa26469c48`, and LibStone
`4e60694e341977ebf39b3344cb5fb3bcb2684af2`. Use a freshly built
`on1xc` and its matching `stdppx/on1x-ppx-GrammarEmbed` and
`stdppx/category.schema.json`. Hash all three before qualifying either the
baseline or a candidate. Reuse this toolchain, not old FinPRED binaries or
stores, when comparing the two revisions.

From each checkout:

```sh
export MULIB_ROOT=/path/to/pinned/mulib
export ON1XC=/path/to/pinned-build/on1xc
export FINPRED_BUILD_DIR=build/verify TMPDIR="$PWD/build/verify-tmp"
unset FINPRED_EXE
./bin/build.sh
./tests/run.sh storage
./tests/run.sh pricing
python3 tests/check_reproducible_build.py
make native-test NATIVE_BUILD_DIR=build/verify-native
```

- Storage pins four v2 run/recommendation/trace digest triples and checks
  the frozen v1 archive's own independent checksum, both v1 replays and
  explanations with live paths absent, and no store changes. Also check
  corruption, unknown formats, and write-failure behavior. The v2 results
  are 17,100, 16,000, 18,000 and 17,001 minor units. Do not regenerate
  expectations to fix a mismatch.
- Reproducibility compares `finpred`, `finpred-cube`, and
  `finpred-forecast` from separate output/scratch paths on one host with
  one installed toolchain. The app build selects the C11 backend.
  This is not evidence for other backends, cross-host reproducibility,
  or compiling the toolchain reproducibly.
- Native CTests check the standalone store and process-death behavior on
  a live mount, not On1x runtime admission or power-loss persistence.
  The real Bubblewrap/seccomp offline-worker test is not an IPC test.
- Preserve `check_price_properties.py`'s seeded exact-arithmetic oracle
  and `check_ingestion_cli.py`'s valid/invalid boundary cases. Use
  `tests/benchmark_price_backtest.py` with explicit baseline/candidate
  executable paths for exploratory timing; check output digests first.
  Report sample counts and distributions, including warmup policy and
  peak RSS where measured. Don't use elapsed time as a correctness gate.

Fresh baseline checks on Linux x86-64: all three standalone native CTests,
all four Python fixture-price oracles, static validation and the full real
offline-worker check passed. The compiled baseline and candidate gates
are separate from these results. `strace` is available; the full plugin
suite additionally needs `Xvfb` and `xvfb-run`, absent on this host.

## Development coordination IPC

This is a separate Linux development utility, not a FinPRED runtime
backend. `tests/check_core_overhaul.py` accepts the coordinator path and
creates randomly named test sessions, each with its own journal under
`build/`. It is intentionally separate from existing release selectors.
Run without `-O`:

```sh
python3 tests/check_core_overhaul.py --coord /path/to/bin/overhaul-coord.py
```

The gate uses real libc message queues and shared memory, an independent
canonical wire encoder, and subprocess checks of the coordinator CLI.
It exercises role/peer mismatches, malformed envelopes, the text and
kernel message-size boundaries, request/grant/queued-frame expiry,
repeated sends/receives/acks, full-queue failure and drain/retry, and
concurrent publication. The fault child alone instruments the writer:
it kills the real process after it copies a slot payload but before its
header write, testing fallback to the preceding slot, lock release,
and cleanup of interrupted initialization. Cleanup/reinit proves that an
old-epoch frame is rejected even with the correlation ID reused.

A session requires headroom for eight queues. In the presence of the
live eight-worker session, initialization returned `EMFILE`, both
directly and in an unprivileged isolated user/IPC namespace. An isolated
namespace with a delegated subordinate UID likewise created only two of
eight probe queues; those two private names were removed. Do not touch
unrelated queues. Run the full gate after the live session is closed or
with sufficient independently provisioned quota.

### Independent source audit

Reviewed broker coordinator SHA-256
`517bec8d47e583e57d89d7278b0fb23773b1acf38dbda74a7ec1718491a0ae2b`.
`0600` IPC objects scope access to the OS account under ordinary ownership
rules. Within that account, roles are caller-provided integers, not
authenticated process identities. Canonical bytes, epoch, expiry,
correlation, peer and digest checks provide protocol consistency among
cooperating callers. They do not protect against another process with the
same UID modifying IPC or impersonating a role.

The alternating checksummed slots and lock can recover the previous
published state when a writer dies before committing the new header.
That recovery does not make three distinct side effects transactional:

- Journal append precedes slot publication. A killed writer may leave an
  attempted event that never became committed state, and a retry may
  reuse that sequence. Do not use the journal alone as a commit receipt.
- `mq_send` precedes the published `sent` state. Death in that window can
  leave a queued frame that the receiver cannot accept. If a retry sends
  the same envelope, the receiver may accept one copy and reject another.
- The receiver dequeues before publishing `received`. Death in that
  window may leave a `sent` exchange without a message to receive; a
  normal resend for that correlation is refused. Use a new admission
  after reconciling state; there is no exactly-once guarantee.

Normal cleanup opens the bound journal to record the closing state.
Keep that private journal available, at the same inode, until cleanup;
deleting or substituting it can prevent cleanup before queue unlink.
An interrupted init with no valid slot is handled separately. The queue
poll deadline does not bound all I/O, lock acquisition, or CLI startup.
