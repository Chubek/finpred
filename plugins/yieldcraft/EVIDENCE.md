# Exact-stay match evidence

```on1x
import plugins.yieldcraft.matcher as Match;
let report = Match.audit_report(scenario, offers_raw);
```

`audit_report(scenario: core.contracts.Scenario, offers_raw: string) -> string`
takes a scenario already validated by `scenario_csv` and frozen offer CSV
bytes. It returns canonical ASCII text, including the final LF. It performs
no I/O. It diagnoses the match even when there are too few comparables to
recommend a price. Invalid sources, duplicate eligible inventory, room caps
and exhausted search budgets are errors. For integration with pricing, use
these in place of `ingest` and `distribution` on the same inputs:

```on1x
let out = buffer_new();
let pool = Match.ingest_with_evidence(offers_raw, scenario, out);
let dist = Match.distribution_with_evidence(pool, scenario, out);
# Use dist for the recommendation; destroy dist and pool as usual.
```

The first function appends the `row` lines and the second appends property,
bundle, allocation and sample lines. Use the same buffer and evidence-enabled
pool for both calls. The caller owns framing, including the version line;
expose buffered evidence only after all matching and run checks succeed.
The standalone wrapper includes the version line itself.

Grammar in emission order (commas are literal; integers are unpadded decimal):

```text
evidence_version=yieldcraft.property-evidence@1
row=<data_row>,<property_id>,<room_id>,<eligibility>
property=<property_id>,<status>,<eligible_rows>,<inspected_subsets>
bundle=<property_id>,<whole_stay_gross_minor>,<selected_rooms>
allocation=<property_id>,<data_row>,<room_id>,<adults>,<children>,<room_whole_stay_gross_minor>
sample=<feasible_properties>,<required_properties>,<adequate|insufficient_evidence>
```

One `row` per observation in source order, numbered from 1 after the header.
Its value is `eligible` or the first applicable reason: `not_bookable`,
`stay_mismatch`, `currency_mismatch`, `future_observed`, `future_ingested`,
`validity_mismatch`, `stale`. Unsupported currencies currently fail contract
validation before matching.

Next comes one `property` per property with eligible rows, in order of first
eligible source row. `matched` is immediately followed by one `bundle` and
its `allocation` lines in source order. `no_feasible_bundle` means no subset
within the room and occupancy constraints can house the party. Properties
having only rejected rows follow, once each in first-source-row order, with
status `no_eligible_rows` and zero subsets. The final `sample` counts each
matched property once. All prices include fees and taxes in EUR cents for the
entire stay.

The winning subset minimizes gross price, then room count, then the numeric
subset mask (least-significant bit = earliest eligible row at this property).
Each occupied room gets at least one adult. When several assignments fit a
winning subset, use the first predecessor reached in ascending already-seated
adult count, then child count, at each room. Source order is significant.

Evidence uses the same subset loop and occupancy DP as pricing. In evidence
mode each reachable DP cell carries its first allocation path as at most four
base-81 digits (one `(adults,children)` per room, plus a leading sentinel).
There are still at most two 81-cell layers live; no second search or extra
subset budget is needed. The eligible-row mapping and all-row property IDs
add two arrays of at most 512 integers, both owned by `Pool` and released
by `Match.destroy`. A complete report adds at most 512 of each line type
(`row`, `property`, `bundle`, `allocation`), plus framing and sample: less
than 256 KiB of ASCII under the validated integer bounds.
