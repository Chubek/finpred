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

## Staged component check

Independently extracted broker commit
`34a34eb8521a852332f81ebb5fe24bc40318f558` into a private `git archive`
snapshot. The MuLIB and LibStone checkouts matched the pins above; the
fresh toolchain fingerprints were:

| Tool | SHA-256 |
| --- | --- |
| `on1xc` | `b27704b426e3f3546be246b2c18e5251798caa41c978faf1384532a35c24e774` |
| `on1x-ppx-GrammarEmbed` | `7353cdd5e341e0368137af3aff863ce459d3c5b3fa0a82a24bc7d4f12603806b` |
| `category.schema.json` | `e2a26a3ca3620e43ec2289ef749746b1f6a956d087e0676cd225d02bb7fadeaa` |

`tests/check_core_numerics.py` (native exact-rational oracle),
`tests/check_core_numerics_on1x.py` (compiled C11 consumer),
`tests/check_python_sdk.py` (relocated C/CMake and Python diagnostics,
with legacy-symbol compatibility), and `tests/check_build_paths.py` passed.
These are component checks, not validation of an assembled release.

At this staged commit, plain `make native-test` selected only the three
standalone store CTests. The following explicit configuration passed all
four tests, including `native_temporal_oracle_and_recovery`:

```sh
cmake -S native -B build/verify-temporal -DBUILD_TESTING=ON \
  -DFINPRED_TEMPORAL_MULIB_ROOT="$MULIB_ROOT" \
  -DCMAKE_C_FLAGS='-Wall -Wextra -Werror -pedantic'
cmake --build build/verify-temporal --parallel 4
ctest --test-dir build/verify-temporal --output-on-failure --no-tests=error
```

## Assembled core candidate

Compared the broker-built `finpred` executables for the pinned baseline
and candidate `fb67fe4d0b2f8d15f9e956c4a2e112100d7cc4da`, using private
scratch and an archive of that candidate revision. `cmp` found them
byte-identical; both have SHA-256
`c6568e181dbc23977891d3bb8ac37e2f44c8a784305f6bf90a733ba65e7818e0`.
No plugin, fixture, or submodule paths differ between these revisions.

- The baseline passed `./tests/run.sh storage`; the candidate passed
  `make test-storage`. Both matched all four v2 triples and both read-only
  v1 archives, passed runtime JSON validation, and handled interrupted
  publication and concurrent writers. The contention probe allows partial
  success with exact serial recovery (observed 8/8 baseline, 7/8 candidate);
  it is not a throughput or success-rate comparison.
- Candidate `make test-storage` ran 3/3 standalone store CTests and the
  newly wired 1/1 native temporal CTest. `native-test` by itself remains
  store-only; `native-temporal-test` selects temporal.
- The candidate's `security` selector invokes the standalone IPC gate.
  The IPC gate was run independently; this record does not claim a full
  security or plugin suite pass, performance for the new library APIs,
  or validation of the later SDK launcher delta.

### Descriptive CLI benchmark

Each measurement used the same scratch inputs and direct executables
(no shell launcher), with two warmups and 16 timed runs per binary,
alternating execution order. Wall time includes process startup. A small
C parent used Linux `wait4` to record each child's peak RSS. Results are
min / median / max. Output bytes matched for both binaries, and replay
left the prebuilt store's file bytes, inodes, mtime and ctime unchanged
with live inputs unavailable.

| Workload | Binary | Wall ms | Peak RSS KiB |
| --- | --- | --- | --- |
| Frozen v2 replay | Baseline | 3.175 / 3.364 / 3.609 | 3104 / 3224 / 3276 |
| Frozen v2 replay | Candidate | 3.212 / 3.399 / 3.632 | 3032 / 3228 / 3284 |
| 256-point ensemble backtest, horizon 7, 240 scored folds | Baseline | 28.308 / 28.909 / 29.257 | 3316 / 3580 / 3768 |
| 256-point ensemble backtest, horizon 7, 240 scored folds | Candidate | 28.340 / 28.880 / 29.399 | 3384 / 3634 / 3736 |

These are short same-host measurements of identical executable bytes.
The differences are run-to-run variation, not evidence of a speedup,
regression, or statistical equivalence for any new code path.

## Development coordination IPC

This is a separate Linux development utility, not a FinPRED runtime
backend. `tests/check_core_overhaul.py` accepts the coordinator path and
creates randomly named test sessions, each with its own journal under
`build/`. It also runs under the assembled candidate's `security`
selector. Run independently without `-O`:

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
unrelated queues. **After broker shutdown, the full gate passed in the
normal Linux queue namespace.** `strace -f` confirmed `mq_open`,
`mq_timedsend`, `mq_timedreceive`, `mq_unlink`, expected `EMSGSIZE` and
`EAGAIN`, both forced `SIGKILL`s, and queue activity only under the two
unique test prefixes. The gate verified 29 concurrent updates and checked
that all of its IPC names were absent after cleanup. The archived
candidate contained byte-identical test and coordinator scripts and
also passed the standalone test using its default coordinator path.

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

## Combined C11 gates and descriptive timings

The combined candidate at `fdb7bc3` (including the SDK launcher) passed
`compiler`, `pricing`, `forecasting`, `storage`, and `security`. The checkout
used the pinned compiler fingerprints above. New gates exercised seven
financial-type rejections, native Ottomat v7 parity and v6 compatibility,
106 SDK policy diagnostics plus malformed wire inputs, exact-rational
forecast and score oracles, and IPC crash recovery. The four v2 triples and
the two read-only v1 archives still passed. Legacy Dragnet search and source
adapter suites passed separately; native storage (3), native temporal (1),
and Poindexter viewport (3) CTests passed as well.

The plugin selector reached the final display prerequisite after its offline
checks, including Caravansary, Dragnet, package/SDK, and Poindexter terminal
checks. It exited 2 because `xvfb-run`/`Xvfb` are unavailable. The standalone
GUI native/worksheet check passed with the real-window test explicitly skipped.
No external financial action or hosted CI run was performed.

The broker's supplemental IPC gate passed with four forced deaths: status
publication, initialization, after `mq_send` and after `mq_receive`. It
exercised an orphan-frame rejection followed by retry, and broker revocation
plus fresh admission for a frame removed before the recipient committed.

Two independent output layouts produced the following SHA-256 identities:

| C11 host | SHA-256 |
| --- | --- |
| `finpred` | `9f61110f3684ffe9853ead520a6ced326224a1e599bd9248d498d852c3ce1827` |
| `finpred-cube` | `47c4018be68ed666d70e99d822c9f9f0e14e7661069db4d8480dd3d4998ad2db` |
| `finpred-forecast` | `495bbd13979e2439d539b1215691934f3a0d8c658347b0095cbffc2645d3bd43` |

`tests/check_cli_release.py` separately confirmed deterministic USTAR/gzip
output across two builds with different paths and umasks, rejected eight
malformed archives, and replayed from a relocated bundle. This uses one
installed compiler, not two independently reproduced compiler builds.

For the five-node financial fixture, five 20-iteration batches gave median
CPU times of 0.90 ms (`prepare`), 0.98 ms (`compile`), and 4.23 ms
(`execute`, including compilation and handlers). A 1,000-iteration process
exceeded the exploratory timeout. This is not a throughput or speedup
claim for long-lived workers.

`python3 -B tests/benchmark_coord.py` includes Python startup, journal
appends, slot access, and queue system calls. In one local run, 64 status
updates gave 45.4 ms median and 21.4 updates/s with one process at a time;
with eight concurrent lanes, 61.1 ms median and 115.3 updates/s. Sixteen
already-admitted send/receive/ack exchanges took 136.7 ms median across the
three CLI invocations. These are development tool timings, not kernel-only
latencies or isolated serialization costs.
