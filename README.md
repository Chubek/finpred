# FinPRED — On1x / MuLIB local Yieldcraft MVP

This is an **implementation-oriented source package**, not a claim of a complete
multi-domain FinPRED product or a production-certified build. Application
algorithms and orchestration are written in MuLIB's **On1x** language. The
compiler and its standard-library raw adapters are expected at
`third_party/mulib/`; the checkout is intentionally **not bundled**.

## What is implemented in On1x

- Four versioned contract kinds: `hospitality.scenario@1`,
  `hospitality.offer@1`, `pricing.valuation@1`, `pricing.recommendation@1`,
  with strict CSV readers, exact UTC and Gregorian date validation, source
  provenance, units, money bounds, and JSON output schemas.
- Deterministic, local-only import of one scenario, valuation and a bounded
  set of room offers. Stale, nonbookable, out-of-stay and expired offers are
  excluded, without fabricating prices. Non-EUR source data and malformed
  schemas are rejected.
- Exact bounded, adult/child/total-capacity room-subset matching for whole
  stays: no room unit reuse, at most 10 room offers/property, at most 4
  selected rooms, and one cheapest feasible bundle per independent property.
- Hyndman–Fan Type-7 quantiles over guest-payable **whole-stay** prices in
  integer cents, converted to rounded EUR/night by exact civil-night count.
- Linear and quadratic lead-time target-percentile curves, the P40 one-step
  monetary shortcut, floor/cap/movement guardrails, and detailed trace.
- A checked, acyclic, fixed On1x Automat graph and a tiny strict Ottmat
  declaration which validates against the same graph. The SDK MVP has a
  closed allowlist and permits **no external actions**.
- Local BLAKE3 content-addressed artifacts, validated JSON envelopes,
  immutable run manifests, and byte-for-byte, as-of **replay** by run ID.
  Recommendation mode never publishes anything.

## Build

Requirement: a compatible MuLIB checkout, including On1x, at
`third_party/mulib` (or select one via `MULIB_ROOT`). The inspected MuLIB
reference is Git commit
`49de89acbc97efbee493d6b28d02c8f64ed4f725` on `master`. Pin this
revision for repeatable build comparisons. Build the On1x compiler with CMake
following `third_party/mulib/on1x/README.md`; initialization of the nested
LibStone submodule may be necessary.

```sh
# In the finpred project root, assuming a populated third_party/mulib:
git -C third_party/mulib submodule update --init on1x/third_party/libstone
cmake -S third_party/mulib/on1x -B third_party/mulib/build/on1x -DBUILD_TESTING=OFF
cmake --build third_party/mulib/build/on1x --parallel 4
./bin/build.sh
```

`bin/build.sh` uses `ON1XC` to select an existing compiler executable. It
invokes the documented On1xfile project build and requests the MuLIB source
root; it does not download dependencies. The output executable is expected at
`target/dev/finpred`.

## Run and replay

```sh
./bin/finpred selftest
./bin/finpred run
# Copy the hexadecimal run_id from the printed output:
./bin/finpred replay YOUR_64_CHARACTER_RUN_ID
./tests/run.sh
```

The default inputs are `fixtures/scenario.csv`, `fixtures/offers.csv`,
`fixtures/valuation.csv`, and `strategies/yieldcraft.ottmat`. Override them
with `FINPRED_SCENARIO`, `FINPRED_OFFERS`, `FINPRED_VALUATION`, and
`FINPRED_STRATEGY` (paths; environment variables). Set `FINPRED_HOME` to
change the local state directory (default `.finpred/`).

The frozen workbook-compatible example is expected to produce:

```text
recommendation_minor=17100
currency=EUR
reason=lower_percentile_shortcut
published=false
```

These are **cents**: EUR 171.00 per room-night. P50 is EUR 175, P40 is EUR
171, and the P40 saving of EUR 4 is below the EUR 5 shortcut threshold. The
hard floor is EUR 160. The second fixture demonstrates a two-room bundle,
an infeasible child's room, and a hard floor, yielding EUR 160/night.

The full program output also includes a stable run ID, recommendation digest
and trace digest. `replay` reads only stored snapshots and rejects any
mismatch. Stored JSON recommendations explicitly have `published: false`.

## CSV contract fields

All files use an **intentionally strict, non-quoted ASCII CSV subset**: exact
header and field count, comma separators, no embedded quotes/commas/newlines,
no extra columns, and one room-inventory unit per offer row. An ISO timestamp
must be the 20-byte `YYYY-MM-DDTHH:MM:SSZ` UTC form. Dates must be valid
`YYYY-MM-DD`, in 1970–2399. Monetary fields are nonnegative **EUR cents**.

- Scenario: `scenario_id`, `observed_at`, `ingested_at`, `decision_at`,
  `arrival`, `departure`, `adults`, `children`, `max_rooms`, `min_properties`,
  `target_bps`, `curve`, `currency`, `max_age_days`, `search_budget`.
- Offer: `property_id`, `room_id`, `arrival`, `departure`, `adult_cap`,
  `child_cap`, `total_cap`, `total_cents`, `fees_cents`, `taxes_cents`,
  `currency`, `observed_at`, `ingested_at`, `valid_from`, `valid_to`, `bookable`.
  `total_cents` is the base stay amount and fees/taxes are added to get the
  final guest-payable whole-stay comparable. A property/room pair must be
  unique among accepted offers.
- Valuation: `valuation_id`, `observed_at`, `ingested_at`, `currency`,
  `current_cents`, `floor_cents`, `cap_cents`, `max_move_cents`, `shortcut_cents`.
  These are all EUR **nightly** amounts.

`target_bps=0` uses the selected `linear` or `quadratic` curve (40% at lead
zero days, 75% at 90 or more days). Otherwise the scenario can pin a
percentile, e.g. `5000` = P50. The shortcut compares the chosen quantile
with P40 and applies P40 only for a **strictly smaller** saving than the
threshold. The effective hard guardrails are the intersection of the
valuation floor/cap and the previous-price movement range. Empty intersection
is a hard error. A minimum of 3 independent feasible properties is required;
the default fixture requires 5.

## Verification status and boundaries

The accompanying Python **fixture oracle passed**, checking P40/P50,
selection, gross price, freshness filtering and the multiroom example. It
is not a substitute for compiling the On1x source. The runtime in the
artifact-producing environment did **not** include a MuLIB checkout or an
`on1xc` binary, so On1x compilation, linking, runtime tests and independent
KernelBind review **have not been performed**. Run `bin/build.sh` and
`tests/run.sh` with the specified MuLIB toolchain before using the program.

This is a source-level first vertical slice, **not the full phases 3–5**:
no generic arbitrary DAG scheduler, no general Ottmat language, no versioned
C plugin host, no independently isolated native/Lua plugins, no network
Dragnet feed, no Poindexter UI, no brokerage/publishing gateway, no database
migrations, and no distributed service. Artifact writes are single-writer
local filesystem operations and are not crash-atomic or concurrency-safe.
The current On1x standard library's native array, filesystem, and hashing
adapters are not certified safe KernelBind imports. No unreviewed MuLIB
StayMatch/Contract/PriceCurve symbol is presented as an admitted On1x kernel.

For semantics, assumptions and limitations, see `docs/IMPLEMENTATION.md`.
