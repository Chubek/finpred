# Planning room-night inventory across two dates

`bin/yieldcraft-inventory` is an offline On1x planner, separate from the single-stock `pricing.inventory-policy@1` planner and FinPRED recommendation archives. The estimates in the example are **synthetic**, not an experiment or measured uplift.

```sh
bin/yieldcraft-inventory build
bin/yieldcraft-inventory evaluate fixtures/coupled_inventory.csv
bin/yieldcraft-inventory compare-csv fixtures/coupled_inventory.csv > comparison.csv
bin/poindexter --build
bin/poindexter --import-csv comparison.csv --book comparison.pxw --csv
```

`evaluate` prints [`pricing.coupled-inventory-policy@1`](../contracts/pricing.coupled-inventory-policy@1.schema.json) JSON; `compare-csv` prints the four initial comparisons in a 16-column CSV for Poindexter. In that editable sheet, rows 2–5 are robust, nominal, fixed, and hold. `=C2-C4` would compare robust and fixed **worst-case model values** in milli-minor units. No result certifies the grid or authorizes distribution or execution. Preserve the original grid along with the workbook if you need to reproduce the comparison. The CSV import is not a replay-verified run and subsequent spreadsheet edits are not linked to the model.

For stress testing a static room-night demand estimate rather than managing shared capacity, use [`stress-contribution`](YIELDCRAFT_CONTRIBUTION_STRESS.md).

## Input contract

`pricing.coupled-inventory-input@1` is unquoted ASCII CSV, with LF or CRLF, at most 8192 bytes, and canonical unsigned integer fields. See the fixture for the exact headers.

- The two dates are consecutive service nights, `A` and `B` (not booking periods). Capacity is 0–6 rooms **per night**. Product `1` consumes one room-night on A, product `2` one on B, product `3` one on each on a kept booking. This is fungible capacity, not room assignment or assurance that the same physical room is free both nights.
- All prices are **EUR minor units per complete booking**, including product 3. Cost is in EUR minor units per room-night sold on each date (added for product 3). Terminal value is in EUR minor units per unsold room-night on each date. These input amounts are at most 10¹⁰; use explicit zero for an absent component. Output value is in thousandths of a EUR minor unit (`scale: 1000`), inclusive of terminal value, not gross revenue.
- There are 1–8 contiguous decision periods with 1–12 offers per period. Sort arms within each period by increasing product, then strictly increasing price for that product. Each offer specifies `0 ≤ low_bps ≤ nominal_bps ≤ high_bps ≤ 10000` for one kept booking conditional on offering it with capacity; each curve is nonincreasing within a period/product. The fixed baseline product/price must occur on the same exact grid in **every period**, even for a baseline that cannot book from initial stock.
- The input describes at most one realized kept booking per period, with cancellation/netting already resolved before the next decision. Only one offer can be shown per period. There are no simultaneous channels, substitution among offers, replenishment, time discount, latent cancellation state, or estimates for off-grid prices. The three probabilities are externally supplied assumptions, not confidence bounds calculated by this tool. Do not substitute room-night quantities from `pricing.demand@1` or forecasts of aggregate guest-nights for probabilities; those are different estimands.

## Objective and comparison

At each `(period, stock_A, stock_B)` the planner chooses hold or a feasible offer. A kept booking earns price less the applicable costs, then consumes all legs. No sale leaves capacity intact. For each offer, the value is the weighted sum of its sale and no-sale continuation values. The robust planner maximizes the minimum expected value over the low/high probability interval at every state. The adversary can select any probability in that interval **separately** for each time/state/offer, after seeing the action. The minimum occurs at an endpoint: low when selling helps, high when it hurts. This is a rectangular, time-consistent stress model, not a correlated-demand or shared-parameter uncertainty model.

The nominal policy maximizes the nominal expectation. The fixed policy always offers the supplied product and price when its capacity allows (even at a loss) and otherwise holds. The hold policy collects only terminal value. Each comparator is scored at the same initial state, using both the nominal probabilities and adversarial interval endpoints **without switching its selected actions** for that evaluation. Comparisons measure sensitivity to modeling assumptions only. They do not estimate counterfactual outcomes from sales logs or establish realized gains. There are no sales data, exogenous leakage checks, or deployed price actions in this tool.

The JSON lists the robust actions at all nonterminal states in period, A-stock, B-stock order. Optimize the applicable weighted numerator before rounding; exact ties favor hold, then lower product identifier and lower price. Round each selected value to a milli-minor unit, ties away from zero, before using it in a previous period. The optimized objective is for this rounded recursion (at most half a milli-minor unit of value error per step relative to unrounded optimization, and near-tied actions can differ). Every realized path uses at most 12 room-nights; sales costs and terminal value are bounded by capacity and each offer consumes at least one unit. This keeps the scaled values and weighted comparisons in signed 64-bit bounds.

Run `python3 -B tests/check_yieldcraft_coupled_inventory.py` with `MULIB_ROOT` and `ON1XC` pointed at the pinned MuLIB and compiler. The test separately enumerates small contingent policy trees with exact fractions and endpoint distributions, checks every robust state, tests both objective evaluations of all comparators, and checks malformed and maximum-size grids.
