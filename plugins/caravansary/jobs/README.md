# Offline jobs

`finpred-caravansary-jobs` is the native admin and foreground dispatch command.
It uses the pinned MuLIB `std.kron` jobs profile and the pinned native
`std.daemon`/Probe supervision companions. No schedule expressions, executable
paths, callbacks, closure captures, credentials, or operating-system handles
are stored in Kron. A CAF schedule declaration neither registers a job nor
grants authority to run it.

## Build and deployment

```sh
CC=clang CXX=clang++ FINPRED_BUILD_DIR=build/caravansary/W5/out \
  TMPDIR="$PWD/build/caravansary/W5/tmp" sh plugins/caravansary/jobs/build.sh
```

Deploy the three siblings together: `finpred-caravansary-jobs`,
`finpred-caravansary-jobs-runner-v1`, and
`finpred-caravansary-jobs-runner-market-v1`. The native build requires Linux,
Clang, glibc/POSIX file and process APIs, and libcrypto. Only the optional
`market-scrape-v1` profile needs the built `finpred-caravansary-market` sibling
and its packaged fixed siblings, such as `finpred-caravansary-market-probe-v1`
(the fixture-only market build). The executable directory itself must not be
writable by group/other, even if sticky. Deploy into a trusted location where
a different user cannot substitute the executables or any path component.
`PATH` and request data do not resolve executables. Keep each deployed
runner's identity stable while promises for it remain pending.

## Admin and clocks

```sh
parent=$(mktemp -d)
state=$parent/caravansary
jobs() { bin/caravansary jobs --state "$state" "$@"; }
jobs init
printf '%s\n' 'fictional fixture' | jobs source-add demo
jobs profile-add demo-check demo
jobs schedule demo-check --at 2026-12-01T00:00:00Z --every 60
jobs next
jobs dispatch --at 2026-12-01T00:01:00Z
# Use the decimal string ID returned by schedule:
jobs cancel 1
```

Use the same argv after the standalone binary or `bin/caravansary jobs`.
The top-level `bin/caravansary schedule --state DIR PROFILE --at UTC ...`
form is equivalent. There is no daemon service or background wait command;
an external caller uses `next` and drives one foreground `dispatch --at UTC`
step at a time. `--once UTC` sets a deadline no earlier than admission;
`--every SECONDS` first fires one interval after admission. A late interval
dispatch coalesces missed periods and re-arms on its original cadence.
`cancel ID` removes a pending promise, not a running process. A denied
interval occurrence does not cancel its still-pending promise.

`init` creates a **new** directory under an existing trusted parent. Supply
an absolute, canonical, nonsymlink state path on a filesystem that supports
local POSIX `flock`, atomic rename, and `fsync`. The state and its subdirectories
must be owned by the effective user with mode `0700`; state files are private
regular files. Root and the effective user are trusted, including their
ability to replace deployment objects. Ancestors not owned by root or the
effective user, symlinks, and group/other-writable nonsticky ancestors are
rejected. Keep the state path stable. **The OS account running the command is
the administrator**; do not expose it to less-trusted callers through a
service or user-writable launcher. Commands for one state take an exclusive,
nonblocking lock; a competing command fails rather than racing an active run.

`source-add ID` reads 1 byte to 1 MiB from stdin and copies the exact data into
the registry. It accepts no input path, URL, or credentials. `source-show ID`
reports size and SHA-256 but not the contents. `profile-add PROFILE SOURCE`
binds `fixture-check-v1` to that immutable source identity and digest. This
first runner verifies the approved fictional fixture bytes, with no artifact
or collection claim. `profile-show PROFILE` inspects registration;
`profile-disable PROFILE` installs a permanent revocation (use a fresh profile
name to admit new work). IDs are 1–63 ASCII alphanumerics, `_` or `-`, with
an alphanumeric first byte. No identity is overwritten through the admin API.
Authorization and content identity are checked at admission, again after
durable Kron consumption, and independently by the child.

Both clocked commands require an injected, exact `YYYY-MM-DDTHH:MM:SSZ` on
the Gregorian UTC calendar from 1970 through 9999; no offsets, fractions,
leap seconds, ambient real-time fallback, or decreasing time. A durable
clock floor is validated and saved before Kron mutation (an idle dispatch
also advances it). It can advance even if a later operation fails. This is
caller-supplied ordering, not an externally verified timestamp. Recurrence
cannot extend beyond the last representable UTC second. Native supervision
uses separate monotonic budgets for exec (1 s), run (2 s, or 7 s with the
market workflow installed to account for its bounded local Probe call), graceful stop
(100 ms), and reap (1 s per attempt); these are not wall-clock guarantees.

## Scheduled fictional market scrape

`market-profile-add PROFILE MANIFEST_SOURCE` selects the fixed
`market-scrape-v1` runner. The operator first registers the exact script
bytes and the exact HTML profile capture via two `source-add` calls.
Register this manifest as a third source (literal four lines, one ASCII
space between fields, LF after each line and no extra content):

```text
CVSCRAPE1
SCRIPT_SOURCE_ID FIXTURE_ID PROVIDER FICTIONAL_URL OBSERVED_UTC REPORT_AS_OF_UTC
SCRIPT_REGISTRY_ID SCRIPT_SHA256
CAPTURE_REGISTRY_ID CAPTURE_SHA256
```

`SCRIPT_SOURCE_ID` is the declared script source (not the registry ID of
the script itself). `FIXTURE_ID` must match that source's declared fixture.
`PROVIDER` is `booking` or `agoda`. `FICTIONAL_URL` is an exact
`https://PROVIDER.example/...` identity; it is not requested over a network.
Both SHA-256 values are the exact lowercase digests from `source-add` or
`source-show`. The approved capture (maximum 64 KiB) cannot be newer than the
manifest's explicit report `as_of`; that report clock is intentionally
independent of the scheduler clock. For the fictional
`examples/workflows/canal-market.caf` and `examples/providers/booking-profile.html`,
the second line can be:

```text
booking_profile booking-profile booking https://booking.example/fixtures/profile 2026-11-26T09:50:00Z 2026-11-26T10:00:00Z
```

Use the new profile in the same `schedule`/`dispatch` commands. The profile
pins the manifest digest, and the manifest pins script and capture digests.
The child regenerates a host-owned, single-source `scrape` grant and places
only those named bytes under a unique private input root. It replaces itself
with the fixed market executable and no caller-supplied extra executable/argv.
If the market build uses its fixed local Probe companion, the market
executable owns that child; Jobs' native supervisor owns only the direct
foreground market process. The market executable must uphold its fixture-only
interface; native daemon supervision is not a sandbox.
The parent accepts at most 2 MiB from the trusted producer and, only after
a reaped successful exit, atomically commits the intact artifact. Retrieve it
with `jobs result-show ID ORIGINAL_DEADLINE_UTC`. A failed or denied run leaves
no new committed result. No live collection, pricing action, availability
guarantee, or publication is implied.

## Replies and recovery

Success writes one canonical JSON line. `schedule` returns a decimal JSON
string `id`, plus the first UTC `deadline`. `next` reports a nullable deadline.
`dispatch` reports nullable `id` and original `deadline`, and `outcome` of
`idle`, `ran`, `denied`, `failed`, `expired` or `uncertain`. Its optional
market `result_status` describes publication to **private state**, not public
publication (`committed`, `not_committed`, `failed`, `unavailable`, `uncertain`).
It reports the observed process event separately from the artifact commit.
`ran` for the fixture-check runner means only successful verification.
An observed `denied` or `failed` consumes the occurrence and is a successful
dispatch reply (exit 0); check the JSON, not just the exit status.
Usage, authorization, and pre-commit storage errors exit 2; exit 3 denotes
uncertainty. SIGINT/SIGTERM received during a step defer shutdown while the
owned child is reaped and can yield exit `128 + signal`; an already-consumed
occurrence is not rolled back.

Registry records, revocation markers, clock and result files use a synced
staging file, same-directory atomic rename, and directory sync. Kron uses
its own exclusive lock and atomic snapshot. A missing snapshot is not
silently recreated by ordinary commands. Reopening restores pending work,
not a history of attempted processes. No multi-file transaction links the
clock, registry, Kron consumption, process outcome, stdout reply and artifact.
Kron commits **before** authorizing or starting work. A crash can skip a
launch, leave an orphan child or private `.dispatch.*`/`.stage.*` file, or lose
the reply to a completed mutation. No automatic retries, exact-once,
durable outcomes for failures, or crash-cleanup guarantee is made. For a
market attempt, the child writes only its unique staging directory; an orphan
cannot commit a result through the jobs protocol. Reconcile uncertain
operations before retrying. Do not recreate or edit a partial/restored state
over an active registry; treat state repair as an offline owner operation.

## Offline tests

```sh
CC=clang CXX=clang++ TMPDIR="$PWD/build/caravansary/W5/tmp" \
  python3 -B plugins/caravansary/jobs/test_jobs.py \
  build/caravansary/W5/out/finpred-caravansary-jobs
```

Add `--market /absolute/path/to/finpred-caravansary-market` to test the real
fixture-scrape integration and byte-identical output against direct `scrape`.
The default suite requires no On1x compiler, sleeps, network, or service.
