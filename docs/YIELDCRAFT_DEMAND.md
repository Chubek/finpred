# First-party demand estimation for Yieldcraft

`bin/yieldcraft-demand` fits a bounded price-response grid from **operator-supplied first-party randomized exposure counts**. It does not collect customer records, run an experiment, inspect competitors, or publish prices. The output is a `pricing.demand@1` snapshot accepted by the existing contribution optimizer.

## Estimate and replay

```sh
bin/yieldcraft-demand build
bin/yieldcraft-demand scenario-digest scenario.csv
bin/yieldcraft-demand estimate scenario.csv exposures.csv > demand.csv
bin/yieldcraft-demand evidence scenario.csv exposures.csv > demand-evidence.json
bin/yieldcraft --scenario scenario.csv --valuation valuation.csv --demand demand.csv
```

Run each step only after the previous one succeeds. Select the same scenario and completed exposure release for both commands. Preserve the exact bytes of the two inputs and both outputs; record the `blake3:…` evidence ID separately in a trusted catalog. Verify offline:

```sh
bin/yieldcraft-demand replay scenario.csv exposures.csv \
  demand.csv demand-evidence.json "$EXPECTED_EVIDENCE_ID"
```

Replay recomputes the fit and compares the independently selected ID and both frozen outputs. The evidence ID is BLAKE3 of four LF-terminated lines: `yieldcraft-demand-estimation@1`, `yieldcraft.randomized-isotonic@1`, bare scenario BLAKE3, bare exposure BLAKE3. This ID is embedded in the demand CSV. The [evidence report schema](../contracts/pricing.demand-estimation@1.schema.json) covers the linked digests, arm counts and pooled fit. Bounds, chronology and statistical checks run in On1x, not JSON Schema. This is a separate evidence identity, not a FinPRED run or code signature; the optimizer archives the resulting demand CSV as before and does not independently verify the upstream experiment.

## Exposure input: `pricing.first-party-exposure@1`

This is a strict unquoted ASCII CSV profile, at most 8192 bytes, with up to 64 price arms. For example (replace `SCENARIO_DIGEST` with the exact scenario digest; counts are synthetic):

```csv
pricing.first-party-exposure@1
scenario_blake3,property,product,cohort,currency,price_basis,assignment,started_at,ended_at,finalized_at,ingested_at,target_exposures,available_room_nights,marginal_cost_minor
SCENARIO_DIGEST,hotel-1,standard,same-lead-segment,EUR,room_night,randomized,2026-11-15T08:00:00Z,2026-11-18T08:00:00Z,2026-11-19T09:00:00Z,2026-11-20T09:30:00Z,100,120,8000
price_minor,assigned,kept,cancelled,nonpurchase,unavailable,unresolved
16000,20,7,2,11,0,0
17500,60,25,3,32,0,0
19000,50,12,5,33,0,0
```

- The scenario must specify one night and at most one room. All offers must be for the same own property/product and comparable audience, terms, and lead-time cohort; the three identifiers use 1–64 lowercase letters, digits, underscores or hyphens. The legacy scenario has no own property/product fields: the supplier is responsible for the mapping. The digest binds the exact scenario but does not prove the mapping.
- An assignment is one independently randomized eligible opportunity, with at most one room-night booked. Use a predeclared grid, positive assignment probability at every arm, and a single reconciled count for each arm covering all assigned opportunities. Count no-shows or failed bookings as cancelled if they are not net booked room-nights under the chosen accounting rule. `kept`, `cancelled`, `nonpurchase`, `unavailable`, and `unresolved` are mutually exclusive and must sum to `assigned`. Do not drop outcomes based on price, booking, cancellation, or availability; do not use only observed bookings or label an observational price history randomized. Exposure counts are at most 1,000,000 per arm, and at least 20 are required at every arm.
- At least two distinct prices must be supplied, in increasing order. Prices and marginal cost are in EUR minor units per room-night, from 0 to 10¹². Prices must be on the same retained-revenue basis as the optimizer, not gross guest-payable competitor prices.
- Supply real UTC timestamps: `started_at < ended_at ≤ finalized_at ≤ ingested_at ≤ decision_at`. Finalize after the predetermined observation and cancellation window, not merely after the initial purchase signal. The cohort’s start must be within the scenario’s civil-day freshness bound. The output uses `finalized_at` for `observed_at`.
- Target exposures (1–1000) is the **externally estimated** number of eligible first-party opportunities from decision through the target booking horizon, under the same product and offer conditions. The model holds this number constant across all evaluated prices; it does not estimate price effects on traffic. At least that many room-nights must be available to the target cohort; no scarcity or inventory contention is modeled. Any unavailable or unresolved assignment in the historical cohort causes abstention for the whole fit.

## What the fit estimates

Use `kept / assigned` at each price, including cancelled and nonpurchase exposures in the denominator. Weighted binomial isotonic regression pools adjacent increases in booking rate until rates are nonincreasing. Pool weights are assignment counts, not equal per price. For a fitted rate `k/n`, project `k × target_exposures / n` room-nights and round half up to thousandths; no interpolation or extrapolation. A flat rounded grid abstains: the supplied evidence does not support a differentiated price response under this policy. The contribution optimizer independently applies price guardrails, marginal cost, and its no-sale alternative.

Twenty assignments per arm is a minimum input gate, not a power calculation. A nonflat fit is not significance, a calibrated interval, or evidence of profit uplift. Use depends on documented randomization, no interference or shared capacity effects, comparable cohorts, complete follow-up and a defensible future exposure estimate. The estimator cannot verify those assumptions or convert observational correlations into causal estimates. No real-property validation is supplied.

Run `python3 -B tests/check_yieldcraft_demand.py` after a normal `make` to compile the estimator and test the handoff to the existing contribution CLI.
