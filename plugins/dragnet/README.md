# Dragnet: frozen CSV source

`dragnet.frozen_csv` 1.0.0 emits one normalized `hospitality.offer@1` JSON
envelope per eligible observation, in source order. Run the standalone Linux
host from the repository root:

```sh
plugins/dragnet/build.sh "$PWD/target/dragnet"
target/dragnet/dragnet-frozen-csv 3<fixtures/scenario.csv 4<fixtures/offers.csv
```

The shell selects the frozen scenario (fd 3) and offers (fd 4). Supply
regular files in a trusted directory, unchanged during reading; the Linux
host reads the open files via `/proc/self/fd`. There is no default selection.
Each file may contain at most **2,000,000 bytes**; the offers CSV must have
the FinPRED v1 header and 1–512 rows. The build uses `MULIB_ROOT` and `ON1XC`
like the root build and stages the shared source modules in a temporary
project. `OUTPUT_DIRECTORY/.on1x-build.json` fingerprints the built sources.

The [Source entrypoint](source/dragnet/frozen_csv.on1x) takes the **contents**
of the offers CSV and a host-validated `core.contracts.Scenario`. It uses the
engine's dataset checks, contract parser, `eligible` predicate, and JSON
serializer. Observed and ingested times must both be at or before `decision_at`;
the stay dates, validity interval, freshness and bookability checks also apply.
Gross prices are EUR cents for the whole stay, including fees and taxes. The
sole parent in each envelope is the BLAKE3 of the **entire original offers CSV**.
For byte-identical results retain both input snapshots and the pinned build.

Malformed input or duplicate eligible inventory fails with a nonzero exit
and no output envelopes. A valid dataset with no eligible rows succeeds with
empty stdout; pricing sample adequacy belongs downstream. The main fixture
emits five offers (properties 101–105) and omits the stale and nonbookable rows.

The [SDK v1 descriptor](plugin.json) declares zero host capabilities for the
adapter. Only the small host reads the two selected files and writes the
result to stdout. This is trusted, statically compiled On1x, not an OS sandbox
for third-party native code. Offline import grants no authority to access a
live provider. No network connector, store write, recommendation, or action
is part of this command.

To embed the entrypoint, include `source/` and `plugins/dragnet/source/`
in the host's On1x module search paths:

```on1x
import core.contracts as C;
import dragnet.frozen_csv as Dragnet;

fn import_snapshot(offers: string, scenario: string) -> string
{
  return Dragnet.offers_as_of(offers,C.scenario_csv(scenario));
}
```

`python3 tests/check_dragnet_frozen_csv.py` builds in a private directory and
checks schema/monetary parity, as-of cutoffs, replay from copied bytes,
provenance changes, input denial and atomic output on validation failure.

**Verification (2026-11-23):** MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
`third_party/mulib/build/on1x/on1xc` SHA-256
`0d63fc81d978f1588df8700cf4222ceb0b4425af26a97a591395b751d331a9af`,
On1xfile C11, GCC 16.2.1, Linux x86_64. The focused test, `tests/check_fixtures.py`,
`tests/validate_static.py`, and `tests/run.sh` against a separately built
FinPRED executable all exited 0. The existing CLI still replayed 17100 and
16000 cents/night; the standalone Source doesn't create or change those runs.
