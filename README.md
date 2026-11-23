# FinPRED: local accommodation pricing

FinPRED’s Yieldcraft CLI recommends a nightly EUR price for a specific stay and party. It reads local CSV snapshots, finds the cheapest feasible room bundle at each independent property, and computes a percentile price subject to the operator’s pricing limits. It records the inputs, recommendation and decision trace locally so the result can be verified later. **A recommendation never publishes a price.**

| Frozen example | Recommendation | Why |
| --- | ---: | --- |
| Default: five comparable properties | **EUR 171/night** | P40 is EUR 4 below P50, less than the EUR 5 shortcut threshold. |
| Multi-room: three comparable properties | **EUR 160/night** | The floor raises the EUR 150 nightly candidate. |

## Start here

1. **[Install and verify](INSTALL.md)** — build the pinned MuLIB/LibStone compiler, then build and test FinPRED with the On1x C11 backend.
2. **[Run the fixtures](GUIDE.md)** — select a private store, replay a recommendation by ID, and inspect the verified price trace and room-by-room evidence.
3. **[Inspect the acceptance record](docs/IMPLEMENTATION.md#acceptance-record)** — see the native results, independent Python oracle, four JSON envelope schemas and replay checks.
4. **[Use the C11 SDK](source/sdk/README.md)** — inspect the built-in strategy's contracts and resource limits and check compatibility from native code.
5. **[Build the native store review target](native/README.md)** — exercise directory-relative reads, no-replace publication and sync failures independently of the CLI.
6. **[Call the Yieldcraft package from On1x](plugins/yieldcraft/README.md)** — pass scenario, offers and valuation snapshots directly to the strategy and receive a recommendation in nightly cents.
7. **[Import frozen offers with Dragnet](plugins/dragnet/README.md)** — select two local snapshots and emit eligible, normalized whole-stay offers as JSON Lines.
8. **[Export a Poindexter pricing sheet](plugins/poindexter/README.md)** — run `./bin/finpred poindexter RUN_ID` to compare the verified recommendation to its frozen valuation in CSV.
9. **[Open the Poindexter spreadsheet](plugins/poindexter/workbench/README.md)** — build with `./bin/poindexter --build`, then edit cells, recalculate formulas and run worksheet scripts with `./bin/poindexter --book prices.pxw`.

For package entry points, permissions and test commands, see [the plugin developer guide](PLUGIN.md).

## What runs today

Choose a [Yieldcraft strategy profile](strategies/README.md) with
`FINPRED_STRATEGY`, for example `FINPRED_STRATEGY=strategies/premium-p75.ottmat ./bin/finpred run`.

The pricing logic is written in MuLIB’s **On1x**. It validates EUR amounts, civil dates and as-of timestamps; counts one whole-stay comparable per property; and applies a Type-7 quantile, a P40 shortcut and floor/cap/movement limits. The checked seven-node graph and [strategy declaration](strategies/yieldcraft.ottmat) support this built-in strategy. There is no general plugin host, network feed, trading or price-publishing gateway. See the [design specification](docs/USER_SPECIFICATION.md) for the broader roadmap.

New runs use [v2 lineage](docs/RUN_FORMAT.md); the reader also verifies original v1 runs. Content digests establish integrity relative to a known run ID, not authorship. The [store protocol](source/store/README.md) supports cooperating writers in a private local directory; it does not guarantee power-loss durability or protection against hostile symlinks. The standard library’s [native bridges](native/README.md) are not independently admitted KernelBind imports.
