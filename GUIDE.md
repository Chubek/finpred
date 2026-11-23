# Operate the local FinPRED CLI

Start with a tested executable from [INSTALL.md](INSTALL.md). The [overview](README.md) describes the scope. Run the examples below from the FinPRED root, in the same shell, so all commands share one store.

## Choose an engine

| Command | Inputs | Result |
| --- | --- | --- |
| `./bin/finpred run --engine legacy` (default) | Frozen hospitality CSVs and Ottomat v1/v2 | EUR recommendation recorded as `finpred-run@2` |
| `./bin/finpred run --engine scalar` | Two unitless integers and Ottomat v3/v4/v5 | Typed value, output digest, and node trace on stdout; no store access |

Set `FINPRED_ENGINE=legacy` or `FINPRED_ENGINE=scalar` to choose a default
for `run` (also supported by the direct executable). An explicit `--engine`
overrides it. `replay`, `explain`, `evidence`, and `poindexter` always use
the legacy engine for archived pricing runs; they ignore `FINPRED_ENGINE`.
An incompatible strategy is an error. The CLI never switches engines on
your behalf.

The scalar engine defaults to [`scalar-spread.ottomat`](strategies/scalar-spread.ottomat),
input values `17` and `42`, and a budget of `16` nodes. This example prints
`value=29` and `output_kind=scalar.level@1`:

```sh
FINPRED_SCALAR_FIRST=17 FINPRED_SCALAR_SECOND=42 \
  FINPRED_STRATEGY=strategies/scalar-midpoint.ottomat ./bin/finpred run --engine scalar
```

`FINPRED_SCALAR_FIRST` and `FINPRED_SCALAR_SECOND` accept decimal integers
from `0` through `1000000000000`. `FINPRED_SCALAR_BUDGET` accepts `1` through
`16`. No signs, spaces, or leading zeros are allowed. The scalar engine
does not read the pricing CSVs or create a saved run. Its output digest
identifies the selected node and its inputs, not a run ID or recommendation.

## Run the default fixture

Use an empty private directory for this walkthrough. If `mktemp` fails, choose a writable `TMPDIR` with enough space before continuing. Keep the printed path if you want to come back to the run. `run` writes only `finpred-run@2`; there is no v1 writer or format-selection option.

```sh
umask 077
FINPRED_HOME=$(mktemp -d "${TMPDIR:-/tmp}/finpred-guide.XXXXXXXX")
export FINPRED_HOME
printf 'Store: %s\n' "$FINPRED_HOME"
unset FINPRED_MODE FINPRED_RUN_ID FINPRED_ENGINE FINPRED_SCENARIO FINPRED_OFFERS FINPRED_VALUATION FINPRED_STRATEGY
./bin/finpred selftest
summary=$(./bin/finpred run)
printf '%s\n' "$summary"
id=$(printf '%s\n' "$summary" | sed -n 's/^run_id=//p')
```

`selftest` prints `selftest_ok=true`. The run prints these fields, plus a `run_id`, `recommendation_digest` and `trace_digest`:

```text
recommendation_minor=17100
currency=EUR
reason=lower_percentile_shortcut
published=false
```

`17100` means **EUR 171.00 per night**. Five properties have eligible rooms for the two-night stay; two other offers are rejected (one stale, one not bookable). P50 is EUR 175/night; P40 is EUR 171/night. Saving EUR 4 is strictly below the EUR 5 threshold, so the strategy selects P40.

## Verify the decision

```sh
./bin/finpred replay "$id"
./bin/finpred explain "$id"
```

Use the **run ID**, not either output digest. IDs are 64 lowercase hex characters. `replay` reads the manifest and snapshots from the same `FINPRED_HOME`, checks their integrity and recomputes the decision without reading today’s input files or writing to the store. Success prints `replay_ok=true` and the original summary. `explain` performs the same checks, then prints the stored decision trace between `trace_begin` and `trace_end`. Look for `decision_at`, `independent_properties`, `rejected_offers`, `intended_nightly_minor`, `candidate_nightly_minor` and `recommended_nightly_minor`. A missing or altered object is an error, not a partial explanation.

Archived `finpred-run@1` records still work with `replay`, `explain`,
`evidence`, and the `poindexter` export. These commands do not modify the
store.

To export this verified comparison for a spreadsheet, run:

```sh
./bin/finpred poindexter "$id" > pricing-sheet.csv
```

The CSV contains a header and one row. For the default fixture, the current
valuation is `17500`, the recommendation is `17100`, and the signed change
is `-400` EUR cents/night. The sheet references the exact recommendation and
valuation artifacts. See the [Poindexter column definitions](plugins/poindexter/README.md).

To work with the result interactively, build the worksheet once with
`./bin/poindexter --build`, then run `./bin/poindexter --run "$id" --book analysis.pxw`
using a new workbook path. Press `e` to enter a formula, `@` to run a
worksheet script, and `s` to save your working copy. The [workbench guide](plugins/poindexter/workbench/README.md)
includes a runnable seven-night pricing example.

## Try the multi-room fixture

```sh
multi=$(FINPRED_SCENARIO=fixtures/scenario_multiroom.csv \
       FINPRED_OFFERS=fixtures/offers_multiroom.csv ./bin/finpred run)
printf '%s\n' "$multi"
multi_id=$(printf '%s\n' "$multi" | sed -n 's/^run_id=//p')
./bin/finpred explain "$multi_id"
```

The party is two adults and one child. Property 201 needs both rooms and contributes a **single** comparable of 23,000 cents for the stay. The other feasible totals are 30,000 and 35,000 cents; property 204 cannot house the child. The median of 30,000 cents over two nights gives a candidate of EUR 150/night. The EUR 160 floor produces `recommendation_minor=16000`, `reason=guardrail_adjustment`, `published=false`.

To check which rooms housed the party:

```sh
./bin/finpred evidence "$multi_id"
```

After verified replay, `evidence` prints a report between `evidence_begin` and `evidence_end`. For this fixture, look for:

```text
bundle=201,23000,2
allocation=201,1,1,1,0,11000
allocation=201,2,2,1,1,12000
```

Room 1 houses one adult for 11,000 cents; room 2 houses the other adult and the child for 12,000 cents. `sample=3,3,adequate` counts three feasible properties for a required three. The [report grammar](plugins/yieldcraft/EVIDENCE.md) defines every field, including rejected rows and properties with no feasible bundle. Unlike the stored decision trace, this report is **derived on demand from verified frozen inputs** on both v1 and v2 runs. It does not add an artifact or change the run ID.

## Supply your own local inputs

Set paths on the `run` command as above. The [launcher](bin/finpred) changes to the repository root; use absolute paths for files elsewhere.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `FINPRED_SCENARIO` | [`fixtures/scenario.csv`](fixtures/scenario.csv) | One stay, decision timestamp, party, target and matching limits. |
| `FINPRED_OFFERS` | [`fixtures/offers.csv`](fixtures/offers.csv) | One inventory unit per row, with capacities, validity, fees and taxes. |
| `FINPRED_VALUATION` | [`fixtures/valuation.csv`](fixtures/valuation.csv) | One row: current nightly price, floor, cap, maximum movement and shortcut threshold. |
| `FINPRED_STRATEGY` | [`strategies/yieldcraft.ottomat`](strategies/yieldcraft.ottomat) | The default uses `ottmat 1` syntax and follows the scenario target. [Named profiles](strategies/README.md) use `ottmat 2` syntax and override target selection while retaining the same evidence checks and guardrails. Both are inputs to `finpred-run@2`. |
| `FINPRED_HOME` | `.finpred/` | Private local state; the parent directory must exist. Use the same home when replaying. |

Use the launcher arguments for the command and run ID; it sets `FINPRED_MODE` and `FINPRED_RUN_ID` for the executable. `FINPRED_MODE=execution` is explicitly denied. No mode books rooms or changes a listed price.

**Format and timing.** Copy the exact headers and column order from the fixtures. CSV is unquoted printable ASCII, with LF or CRLF rows, unsigned decimal integer fields, and `0`/`1` for `bookable`. No quoted commas, missing values, BOM, or extra columns. Civil dates use `YYYY-MM-DD` (1970–2399); UTC timestamps use `YYYY-MM-DDTHH:MM:SSZ`. Qualifying offers match both stay dates, were observed **and** ingested by `decision_at`, cover the stay with `valid_from`/`valid_to`, and meet `max_age_days` in calendar days. A well-formed but ineligible observation is excluded; malformed data or unsupported currency fails the run.

**Money and selection.** All monetary fields are nonnegative EUR cents. The offer’s `total_cents` is the base **whole-stay** amount: add `fees_cents` and `taxes_cents` once. Each independent property contributes its cheapest feasible bundle; rooms are not reused. The strategy interpolates the Type-7 quantile in whole-stay cents, rounds half-up, then divides by **civil nights** and rounds half-up again. Valuation limits and the recommendation are **nightly**, even when a comparable needs several rooms. `target_bps=5000` requests P50; `0` selects a linear or quadratic lead-time curve from P40 at day 0 to P75 at day 90 or later. Explicit targets below P40 are unsupported. A saving equal to the shortcut threshold does **not** trigger P40. The final price must satisfy both floor/cap and the movement limit from `current_cents`.

**Bounds and failures.** Inputs are capped at 2,000,000 bytes per file and 512 offer rows. Matching admits at most 10 rooms per property, selects up to 4 rooms, and supports up to 8 adults and 8 children. `search_budget` caps inspected subsets at 1,000,000. Duplicate eligible `(property_id, room_id)` pairs fail. `min_properties` is 3–32; several rooms at one property do not satisfy it. `insufficient_evidence`, an exhausted search budget, or an empty guardrail intersection means **there is no recommendation**.

## Keep and recover a run

- `runs/<run_id>.txt` is the commit record. `artifacts/blake3-<digest>.txt` holds exact raw inputs, normalized [contract envelopes](contracts/), outputs and traces. A `finpred-run@2` ID hashes the lineage record, which binds the raw digests, ordered normalized parents (including rejected offers), graph and policy versions. To migrate an archive, run its verified snapshots to create a new v2 identity; leave the original v1 record and artifacts unchanged. See [formats and migration](docs/RUN_FORMAT.md).
- Back up the **whole home** while writers are stopped; copying the manifest alone loses its inputs. Verify a restored copy with `replay` using a previously saved run ID. `unknown id` can mean the wrong home. For missing snapshots, digest mismatches or immutable path conflicts, stop and check the backup; replay does not repair or overwrite published files.
- Use a private local POSIX directory with trusted ancestors. Cooperating writers reserve `<destination>.pending`, close and rename the staged payload on the same filesystem, then publish the manifest last. If a staged write or rename reports failure, the writer cleans up its own payload and reservation or reports a cleanup error. A busy reservation can fail explicitly. Rename makes a complete file visible, but does not prevent another program from replacing it. Power-loss durability and hostile-symlink confinement still require a [reviewed storage interface](native/STORE_ADMISSION.md). Content digests are not signatures.
- After an interrupted writer, **stop all writers before cleanup**. Inspect the named reservation. Remove only a confirmed abandoned `payload` and its `.pending` directory (it may already be empty). Never promote a staged file or delete a published conflict. Rerun with the same inputs and verify the resulting ID by replay. Complete artifacts left without a manifest may be reused. See the [publication and recovery protocol](source/store/README.md).
