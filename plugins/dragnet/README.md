# Dragnet: acquisition and offline sources

The [public feeds](PUBLIC_FEEDS.md) tool separately supports ECB reference
rates and Eurostat accommodation aggregates. It is not a pricing engine
input or an extension of Dragnet's frozen CSV SDK descriptor.

## Frozen CSV source

`dragnet.frozen_csv` 1.0.0 emits one normalized `hospitality.offer@1` JSON
envelope per eligible observation, in source order. Run the standalone Linux
host from the repository root:

```sh
plugins/dragnet/build.sh
build/dragnet/dragnet-frozen-csv 3<fixtures/scenario.csv 4<fixtures/offers.csv
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

## Frozen Crossref search and work evidence

For normal offline use, build once and run the replayable launcher:

```sh
plugins/dragnet/build-crossref.sh
fixtures=tests/dragnet_elvi_consumer
plugins/dragnet/crossref import 'hotel & rates' \
  "$fixtures/request.csv" "$fixtures/search.json" "$fixtures/work.json" > evidence.json
plugins/dragnet/crossref verify 'hotel & rates' \
  "$fixtures/request.csv" "$fixtures/search.json" "$fixtures/work.json" evidence.json
```

`DRAGNET_CROSSREF_BIN` overrides the tool directory. `verify` prints
`crossref_replay_ok=true` only after byte-exact recomputation. The launcher
stages bounded copies of trusted local files and generates its own decoder
handoffs. It does not consume cached decodes or touch the FinPRED store.
The [plugin-local schema](contracts/dragnet.crossref-evidence@1.schema.json)
validates the output shape; chronology and evidence equality are runtime
checks, not schema guarantees.

This separate Linux tool pair imports **one saved Crossref works search
response and one saved Crossref work response for a DOI in that search**.
It does not query Crossref, resolve a DOI, download a publisher page, or
parse arbitrary HTML. It uses pinned MuLIB ElviScrape's `compile`, `url`,
and `parse` in a standalone C11 executable using the fixed upstream
`Crossref.elvs` profile. Elvi extracts search hits; MuLIB JSON extracts a
fixed bibliographic projection from the work response. Neither executable
has a fetch command, a caller-provided origin or template, credentials, or
redirect handling. No Elvi or other new foreign import is added to On1x.

From the repository root:

```sh
export TMPDIR="$PWD/build"    # must exist on an executable filesystem
plugins/dragnet/build-crossref.sh "$TMPDIR/dragnet-crossref"
tools="$TMPDIR/dragnet-crossref"
fixtures=tests/dragnet_elvi_consumer
"$tools/dragnet-crossref-capture" search 'hotel & rates' \
  <"$fixtures/search.json" >"$tools/search.decode"
"$tools/dragnet-crossref-capture" work \
  <"$fixtures/work.json" >"$tools/work.decode"
"$tools/dragnet-crossref-import" 3<"$fixtures/request.csv" 4<"$fixtures/search.json" \
  5<"$fixtures/work.json" 6<"$tools/search.decode" 7<"$tools/work.decode"
```

The fixtures are **synthetic**, not records of external requests. For real
snapshots, the operator must be authorized to obtain and retain the bytes
and must supply the query and metadata for that capture. The request file
uses the `dragnet.crossref-request@1` marker and the fixed CSV header shown
in the fixture. Its UTC timestamps (second precision, `Z` only) separately
describe observation and ingestion of each snapshot; ingestion of both
must be at or before `as_of`. Its `terms_ref` and `retention_ref` are 1–64
byte identifiers referring to the operator's policy records, not proofs of
authorization. Select any nonempty subset of `title|publisher|type`, without
repeats. Fields are opaque strings (first title, when present) or `null`
when absent. Field selection filters final output; the local work decode
still contains all three permitted fields.

- Bounds: 1–128 printable ASCII keyword bytes (not all spaces, no
  backslash), 16 hits
  per frozen search page, 262,144 bytes per raw response, 1,024 bytes per
  request file and decoded text field, and 16,384 bytes per decode file.
  Search rows dropped by Elvi cause the batch to fail; this is not a claim
  that the page covers every matching work. The profile uses Crossref result
  DOI links on `https://doi.org/`; the importer admits only a restricted
  ASCII DOI syntax and matches case-insensitively. Duplicate result DOIs,
  an unrelated work, malformed inputs, or late snapshots yield no evidence.
- The On1x entrypoint is `dragnet.frozen_crossref.evidence_as_of`; it takes
  the five inputs as bytes. The standalone host supplies only the five open
  regular files. Output is one JSON `dragnet.crossref-evidence@1` record
  with a BLAKE3 reference for each exact input byte sequence. It verifies
  both raw digests against the decoder handoff. Run the pinned decoder
  yourself and use unchanged files in a trusted directory: the handoff
  is not a signature or proof that a response came from Crossref, matches
  the operator's query, or was captured at the asserted times. Keep the
  five inputs and pinned build for byte-identical replay.
- This is a plugin-local evidence format, not a registered FinPRED contract
  or a persisted recommendation run. It has no validity interval or implied
  freshness beyond the capture times and as-of cutoff. No offer, price,
  publication, or FinPRED store write is produced. No OS sandbox or
  KernelBind admission is claimed.

`python3 tests/check_dragnet_elvi.py` builds both executables in a private
directory and checks real Elvi URL rendering and search parsing, selected
metadata and missing fields, exact-byte replay, work/search association,
resource bounds, and rejection of malformed, late, or mismatched inputs.

**Verification (2026-11-23):** Pinned MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`
and LibStone `b5c962721a32df18b2fb22de136c1f2ef8b6390d`, GCC 16.2.1 on
Linux x86_64, `on1xc` SHA-256
`88428528934039ca7d0eb4064ec10e156235984aeafc3138b43ee19ee18cff20`.
The Crossref and frozen CSV focused tests and shared FinPRED integration
suite exited 0. `strace -f -e trace=network` recorded no network syscalls
for the two decoder commands and the importer on the synthetic fixtures.
