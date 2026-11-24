# Finite-inventory pricing

`plugins.yieldcraft.inventory_pricing.solve(input)` is a pure On1x planner for one kind of stock over a finite horizon. It consumes an explicit candidate-price grid with externally supplied Bernoulli **net-sale** probabilities. It returns a contingent policy, not a price publication, a demand estimate, or an extension to a FinPRED run format.

For two dates with competing one- and two-night bookings, see the separate [robust coupled-inventory planner](YIELDCRAFT_COUPLED_INVENTORY.md).

## Input and output

Supply `pricing.inventory-input@1` as bounded, unquoted ASCII CSV (LF or CRLF, up to 8192 bytes). Use canonical nonnegative integers:

```csv
pricing.inventory-input@1
initial_stock,unit_cost_minor,terminal_stock_value_minor
1,0,0
period,price_minor,net_sale_bps
1,120,10000
2,400,10000
```

The input includes initial stock (0–12 units), unit cost on sale, and terminal value per unsold unit. Use one currency and one unit consistently; amounts are money minor units up to 10¹⁰. Periods must be contiguous starting at 1 (up to 12). Each has 1–8 prices in strictly increasing order with nonincreasing net-sale probabilities from 0 to 10,000 basis points. Do not pass expected quantities from `pricing.demand@1` as probabilities: that file estimates room-night totals for a different model.

The JSON output is `pricing.inventory-policy`, version `1`. The `states` array is ordered by period then stock, including zero stock and every stock up to the input maximum, whether reachable or not. A state contains `action` (`offer` or `hold`), `price_minor` and `net_sale_bps` (null for hold), and `expected_value_minor_milli`. The top level reports the initial value and its increment over holding all stock to the end. Scaled values use thousandths of a minor unit; `published` is always false. In the example, the planner holds in period 1, offers at 400 in period 2, and returns an initial expected value of 400,000 milli-minor units. With two units the same grid makes offering in both periods optimal.

## Objective and assumptions

If the planner offers at `p`, there is one net sale with probability `q` and otherwise none. A net sale realizes `p − unit_cost` and decreases stock by one. Hold earns nothing now and preserves stock. Unsold units realize `terminal_stock_value × remaining_stock` at the end. The planner maximizes expected contribution inclusive of that terminal value. The gain relative to holding all stock to the end reports the incremental value of the policy under these assumptions.

For positive stock `s`, the Bellman comparison at period `t` is:

```text
hold  = V(t+1, s)
offer = q × (p − unit_cost + V(t+1, s−1)) + (1−q) × V(t+1, s)
```

There is no offer at zero stock. Opportunity cost is endogenous: an offer can sacrifice a better later sale, or the terminal value available for an unsold unit. If a unit's relevant outside value is zero, explicitly use terminal value zero.

The policy assumes the supplied transition probability is valid conditional on the period and action whenever stock is positive, independent of the earlier history beyond the state. Price grids can change by period, but probabilities do not respond to inventory, previous prices, customer substitution, or earlier unsold arrivals. There is no replenishment, time discount, more than one net sale per period, or parallel-channel inventory. Net sales are taken as resolved before the next decision; this does not model booking then later cancellation, refunds, or stock returned after an intermediate period. Use external estimation and validation before treating probabilities as credible. The planner does not infer them from historical or competitor data or optimize under uncertainty in them: this is not robust, empirical, or a validated revenue forecast.

Action numerators are compared exactly with integer basis-point weights applied to the stored continuation values; exact ties prefer hold and then lower price. Only the winning value is rounded half up to milli-minor units at each state, so the policy is for this defined rounded recursion, not arbitrary-precision optimization. An offer can win by less than half a milli-minor unit even when the printed value equals holding. At most 0.5 milli-minor rounding error per step propagates into the reported value relative to the unrounded Bellman value; a near-tied policy can still differ.

## Verify

Run `python3 -B tests/check_yieldcraft_inventory.py` with the pinned On1x compiler available. The compiled test consumer compares every policy state against a separate Python exhaustive policy-tree enumeration using exact fractions. It also checks malformed grids, inventory opportunity cost, ties, fractional rounding, and the maximum input dimensions. The consumer is not a production launcher or an archive writer.
