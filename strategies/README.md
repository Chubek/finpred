# Yieldcraft strategies

## Primary: maximize expected contribution

```sh
bin/yieldcraft --demand fixtures/demand_contribution.csv
bin/finpred explain <run-id>
bin/finpred evidence <run-id>
```

The example demand is synthetic; it is not a forecast for a real property.
`bin/yieldcraft` defaults to [`contribution.ottomat`](contribution.ottomat).
The lower-level `bin/finpred run` preserves its historical default; select
the same primary policy there with `FINPRED_STRATEGY=strategies/contribution.ottomat`
and `FINPRED_DEMAND=path/to/demand.csv`.

The policy chooses the feasible **evaluated** price `p` that maximizes
`(p − c) × D(p | x)`: `c` is incremental cost per sold room-night and `D`
is expected net booked room-nights at that price in the fixed decision
context `x`. Compare exact scaled integers, not rounded money, revenue, or
conversion alone. In the example, the recommendation is **19,000 EUR cents
per room-night**: `(19000 − 8000) × 105 = 1,155,000` cents in expected
contribution, better than the 17,500-cent revenue-maximizing price.

Prices must satisfy the valuation floor, cap, and maximum movement from
the current price before comparing scores. The policy never clips a
candidate to an unevaluated price or interpolates/extrapolates demand.
An exact tie prefers the price closest to current, then the lower price.
If no evaluated point is feasible, own-demand evidence is insufficient.
If no feasible point beats the zero contribution of no sale, no price is
recommended. In both cases the command fails without writing a run or
falling back to competitor positioning, including when the demand file is
missing or stale.

### Demand snapshot (`pricing.demand@1`)

Use the unquoted ASCII CSV layout in the [example](../fixtures/demand_contribution.csv):

1. Schema ID `pricing.demand@1`.
2. Metadata header and one row: BLAKE3 of the **exact scenario file bytes**,
   UTC observed and ingested times, `EUR`, `room_night`, evidence method,
   BLAKE3 reference to the backing evidence or model release, and marginal
   cost in minor units per room-night. The observed and ingested times must
   be ordered and no later than `decision_at`; civil-day observation age
   must not exceed the scenario's `max_age_days`.
3. Header `price_minor,expected_room_nights_milli` and 2–64 candidate rows.
   Prices must be unique and increasing; expected quantities, in thousandths
   of a room-night, must be nonincreasing and in `0..1000000`. All prices and
   cost are integer minor units in `0..1000000000000`. The snapshot is at most
   8192 bytes. Prices, cost, current price and guardrails must share the same
   per-room-night basis; use revenue retained by the property, net of
   pass-through taxes, with no double counting of fees in cost.

Admitted methods are `first_party_price_experiment` (first-party offer
experiments that account for exposure, nonpurchase and availability), or
`calibrated_booking_model` (own booking response estimates with documented
price variation and validation). Supply estimates for the **same** property,
product, inventory and decision horizon at each price, accounting for
cancellations where relevant. The snapshot declares upstream provenance;
the engine validates the shape, timing, context and reference, not the
external experiment, causal assumptions or calibration. Posted competitor
prices, booking counts without exposure/availability context, and arbitrary
percentiles are not substitutes for demand.

Successful runs freeze scenario, demand, valuation and strategy bytes and
write a [`pricing.contribution-recommendation@1`](../contracts/pricing.contribution-recommendation@1.schema.json)
output with `published=false`. See [run formats](../docs/RUN_FORMAT.md) for
`finpred-run@3` and replay. The trace lists every evaluated price, its demand,
exact score in thousandths of a minor unit, and guardrail eligibility.

## Secondary: competitor market positioning

```sh
bin/yieldcraft --market-positioning
bin/yieldcraft --strategy strategies/lead-quadratic.ottomat
```

These policies describe relative positioning in the comparable offer
distribution. They do **not** estimate willingness to pay or optimize
contribution. `--capture` and `--dragnet` explicitly choose this competitor
workflow as well; neither can be combined with a demand snapshot.

`FINPRED_STRATEGY` is a file path. For example, from the project root:

```sh
FINPRED_STRATEGY=strategies/lead-quadratic.ottomat bin/finpred run
bin/finpred explain <run-id>
```

Choose one of these five files to set the intended percentile. The table
uses the default fixtures: 26 days to arrival, two nights, five comparable
properties. All amounts are **EUR cents per night**.

| File | Target rule | Intended bps | Intended cents | Selected bps | Final cents |
| --- | --- | ---: | ---: | ---: | ---: |
| `value-p40.ottomat` | Fixed P40 | 4000 | 17100 | 4000 | 17100 |
| `balanced-p55.ottomat` | Fixed P55 | 5500 | 17800 | 5500 | 17800 |
| `premium-p75.ottomat` | Fixed P75 | 7500 | 19000 | 7500 | 19000 |
| `lead-linear.ottomat` | Linear P40 → P75 | 5011 | 17507 | 4000 | 17100 |
| `lead-quadratic.ottomat` | Quadratic P40 → P75 | 4292 | 17217 | 4000 | 17100 |

These policies choose the target independently of the validated scenario's
`target_bps` and `curve`. For `d` civil days to arrival, capped at 90, the
curves add `floor(3500 × d / 90)` or `floor(3500 × d² / 8100)` to 4000 bps.
The matcher contributes one feasible whole-stay bundle per independent
property. Type-7 interpolation rounds half up to whole-stay cents before
division and half-up rounding to nightly cents.

The P40 shortcut applies when moving down saves **strictly less** than
`shortcut_cents`; equality keeps the intended price. Both curves in the
table save less than the fixture threshold of 500 cents. Floor, cap and
maximum movement then constrain the candidate. For example, limiting movement
to 200 cents from 17500 raises the linear policy's 17100 candidate to 17300.
Every recommendation has `published=false`.

The original market policy, `yieldcraft.ottomat`, uses the scenario target,
or its curve when the target is zero. Its `ottmat 1` header is a declaration
syntax version, just as `ottmat 2` is for named profiles. The CLI writes
[`finpred-run@2`](../docs/RUN_FORMAT.md) for both; there is no writer or
option for `finpred-run@1`.

For named profiles, the verified lineage and trace identify
`yieldcraft.<name>@1` and the BLAKE3 digest of the exact declaration bytes;
the recommendation JSON retains the SDK family `yieldcraft.percentile@1`
and its strategy digest. Neither identifier selects a run format.
`replay`, `explain`, `evidence`, and `poindexter` use the stored declaration,
so they work even if the live policy file is unavailable. Archived
`finpred-run@1` records with the scenario policy are read-only.

Selection follows the file contents, not the filename. Each named file has
an `ottmat 2` header, the seven fixed graph declarations, and one versioned
`profile` line. An unknown name, a mismatched target for a known name, or
an incompatible graph is rejected before creating a run. Changing LF to
CRLF retains the declared policy but changes the raw digest and run ID.
The parser also accepts `ottomat` for both header versions. The original
market policy keeps its `ottmat 1` bytes and the named profiles keep
their `ottmat 2` bytes to preserve the pinned `finpred-run@2` IDs. Changing
the header spelling changes the raw digest and therefore the run ID.

## Scalar analysis examples

[`scalar-spread.ottomat`](scalar-spread.ottomat) is a v3 input for the
[native scalar host API](../source/ottomat/README.md#v3-scalar-analysis).
[`scalar-select.ottomat`](scalar-select.ottomat) adds
[v4 typed selection](../source/ottomat/README.md#v4-scalar-selection).
[`scalar-midpoint.ottomat`](scalar-midpoint.ottomat) uses the
[v5 registered diagnostic](../source/ottomat/README.md#v5-registered-scalar-algorithms).
None is a Yieldcraft profile: do not pass them as `FINPRED_STRATEGY`.
