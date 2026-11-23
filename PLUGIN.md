# Developing a FinPRED plugin

FinPRED integrates **trusted On1x code at build time**. Choose the package by the data you have: Dragnet normalizes frozen offers, Yieldcraft computes a price from snapshots, and Poindexter presents a verified run. Each has a different calling convention. Copying a `plugin.json` into `plugins/` does not register code or add a CLI command.

| Package and descriptor | What the caller supplies | What the caller gets |
| --- | --- | --- |
| [Dragnet `Source`](plugins/dragnet/plugin.json) | Offers CSV contents and a validated scenario | Zero or more `hospitality.offer@1` JSON envelopes, one per line |
| [Yieldcraft `Strategy`](plugins/yieldcraft/plugin.json) | Mode and three CSV snapshots: scenario, offers, valuation | An On1x `Recommendation` record, including the nightly price in EUR cents |
| [Poindexter `View`](plugins/poindexter/plugin.json) | Verified identities and scalar fields from one replayed run | `(true, csv)` for a one-row pricing sheet, or `(false, diagnostic)` |

All three packages declare SDK 1, version `1.0.0`, `effects: ["pure"]` and `host_capabilities: []`. The host selects inputs, opens files, verifies provenance and decides where output goes. The declarations document the reviewed code; they do not sandbox arbitrary code in the host process. A mode string, a descriptor match and a recommendation each grant **no authority to publish a price**.

## Dragnet: import an offline snapshot

From the repository root, with the [pinned On1x toolchain](INSTALL.md) available:

```sh
plugins/dragnet/build.sh "$PWD/target/dragnet"
target/dragnet/dragnet-frozen-csv 3<fixtures/scenario.csv 4<fixtures/offers.csv
```

The shell opens two caller-selected regular files. The Linux host reads `/proc/self/fd/3` (scenario) and `/proc/self/fd/4` (offers); it has no default source. Use frozen files in a trusted directory. Inputs use the exact unquoted CSV headers in [the fixtures](fixtures/), at most 2,000,000 bytes per file and 1–512 offer rows. The [build script](plugins/dragnet/build.sh) stages the shared FinPRED modules and builds a standalone executable.

To embed [the adapter](plugins/dragnet/source/dragnet/frozen_csv.on1x), add `source/` and `plugins/dragnet/source/` to your host's module search paths. Import `core.contracts as C` and `dragnet.frozen_csv as Dragnet`, then call `Dragnet.offers_as_of(offers_csv,C.scenario_csv(scenario_csv))`. Pass **contents**, not paths.

The default fixture emits five eligible offers in source order. Prices include taxes and fees for the **whole stay**. Each envelope names the BLAKE3 digest of the complete original offers CSV as its parent. A valid dataset with no eligible rows succeeds with empty output; malformed input fails before the host prints any envelopes. Retain both snapshots to reproduce the as-of selection. The NDJSON is for consumers of the [offer schema](contracts/hospitality.offer@1.schema.json); Yieldcraft's entry point below expects the original CSV, not this stream.

## Yieldcraft: call the strategy from On1x

```on1x
import plugins.yieldcraft.entry as Yieldcraft;

fn nightly_minor(scenario: string, offers: string, valuation: string) -> i64
{
  let r = Yieldcraft.recommend("recommendation",scenario,offers,valuation);
  return r["recommended_cents"];
}
```

Compile the host with `-I "$PWD/source" -I "$PWD"` from the FinPRED root. The [package build example](plugins/yieldcraft/README.md) shows the C11 driver invocation; the [independent consumer](tests/yieldcraft_package_consumer/main.on1x) also shows serialization. `recommendation` is the only invocation mode. The [return record](source/yieldcraft/strategy.on1x) carries the reason, selected percentile and evidence counts. It contains no store handle or run ID. To emit `pricing.recommendation@1`, the host supplies verified run and parent IDs to `core.serialize.recommendation`; to persist and replay a run, use the [CLI](GUIDE.md).

Each feasible property contributes one cheapest room bundle. Limits include 512 offer rows, 10 eligible rooms per property, 4 selected rooms, 8 adults, 8 children and a search budget of at most 1,000,000. Fewer than the required independent properties yields `insufficient_evidence` via `tool_fail`, not a fallback price. The frozen fixtures return `17100` (`lower_percentile_shortcut`) and `16000` (`guardrail_adjustment`) cents per night. The CLI shares the matcher and strategy implementations and owns its own evidence, lineage and replay path.

## Poindexter: render a verified pricing sheet

To see the complete host flow for the default fixture, start in the repository root after `./bin/build.sh`:

```sh
(
  set -eu
  work=$(mktemp -d)
  trap 'rm -rf -- "$work"' EXIT
  export FINPRED_HOME="$work/store"
  ./bin/finpred run >"$work/run.txt"
  id=$(sed -n 's/^run_id=//p' "$work/run.txt")
  ./bin/finpred poindexter "$id"
)
```

`run` writes a local record. `poindexter` replays that record read-only and prints CSV: `current_minor=17500`, `recommended_minor=17100` and `change_minor=-400` are the values in the default fixture's data row. The difference is nightly EUR cents, not realized revenue.

For a static library integration, the root [On1xfile](On1xfile) declares `dependency "poindexter" local "plugins/poindexter"`. Import `poindexter.sheet as Sheet`. The [public signature](plugins/poindexter/src/sheet.on1xi) takes, in order:

```on1x
let (ok,text) = Sheet.render(run_id,recommendation_digest,valuation_digest,
  currency,basis,current_minor,recommended_minor,reason,published);
if !ok { tool_fail(text); }
```

Pass three bare 64-character lowercase hex IDs. Use the digest of the **normalized valuation envelope**, not the valuation CSV; use the recommendation envelope digest, not the trace digest. The [host call site](source/cli/app.on1x) verifies the [v1 or v2 run](docs/RUN_FORMAT.md) before projecting `EUR`, `room_night` and `published=false`. `render` checks field syntax, bounds and the pricing reason; it does not verify that the values came from a run. Success is a header and one data row (11 columns, at most 512 ASCII bytes total). The sheet is derived output, not an additional stored contract.

## Native callers: inspect the descriptor

The [C11 SDK](source/sdk/README.md) is independently linkable without MuLIB. It describes **only** `yieldcraft.percentile`. Include `<finpred/sdk.h>` and link `-lfinpred_sdk`. The sequence in the [C consumer](tests/sdk_consumer.c) is:

1. `finpred_sdk_lookup_v1(FINPRED_SDK_ABI_V1, "yieldcraft.percentile", &plugin)` obtains an opaque handle. Check for `FINPRED_SDK_OK` before use.
2. `finpred_sdk_describe_v1(plugin)` exposes the version, contracts, effect, required capabilities and numerical limits. The library owns the handle and descriptor; neither is freed by the caller. Both expire when the library is unloaded.
3. `finpred_sdk_check_v1(plugin, "Strategy", "pricing.recommendation@1", "pure", "recommendation", 0)` checks compatibility only. Unknown names return `NOT_FOUND` on lookup; wrong ABI, kind or output contract returns `INCOMPATIBLE`; nonzero capability requests, unsupported effects or modes return `DENIED`. See the [public header](source/sdk/sdk.h) for the full status names.

Both the C check and the [On1x allowlist](source/sdk/sdk.on1x) recognize `analysis`, `recommendation` and `simulation` for this descriptor. Neither invokes pricing. The Yieldcraft package itself requires `recommendation`; `execution` is denied. Building the SDK as a shared library gives native consumers the same descriptor API, not an extension loader.

## Integrate and test a new trusted module

1. **Choose a narrow entry point.** Pass validated values or frozen contents. Keep file selection, output and run verification in the host. Specify units, time cutoffs, failure behavior and bounds. Reuse the [versioned contracts](contracts/) when your data has those semantics.
2. **Make the build explicit.** For a reusable local library, copy the layout of [Poindexter](plugins/poindexter/): `On1xfile` declares `kind library`, `On1xfile.m` lists the implementation, and `On1xfile.i` lists the `.on1xi` interface. Declare the dependency in your host project and import it by name; the [standalone consumer project](tests/poindexter_consumer/On1xfile) stages the dependency under `vendor/poindexter`. For a source with host-specific I/O, use [Dragnet's host](plugins/dragnet/source/host.on1x) as the example.
3. **Document and wire the exact call.** Record the name, package and SDK versions, kind, contracts, entry point, effects, capabilities and bounds in `plugin.json`. These are package descriptions, not a universal manifest parser. An additional CLI feature needs an explicit host call and rebuild. The existing fixed graph and Ottmat declaration do not schedule new packages. Preserve old run identities and replay behavior if changing persisted semantics.
4. **Test across the host boundary.** Compile a separate consumer; compare fixture bytes and units, test malformed inputs and denied modes, and check for unintended writes. For replay views, include missing and corrupted runs as well as valid runs. Trusted linkage does not provide isolation for untrusted native code, network access or an action gateway.

Run from the root on Linux; [INSTALL.md](INSTALL.md) covers `MULIB_ROOT`, `ON1XC` and the Python `jsonschema` test dependency. Set `TMPDIR` to a writable executable filesystem with space for disposable builds.

```sh
python3 tests/check_dragnet_frozen_csv.py   # FD selection, cutoff, provenance, schema
python3 tests/check_yieldcraft_package.py   # fixture envelopes, denied modes, invalid inputs
python3 tests/check_poindexter_package.py   # independent consumer, CSV bounds and rejections
python3 tests/check_sdk.py                  # build/install C SDK, link consumer, compare metadata

./bin/build.sh
python3 tests/validate_static.py
./tests/run.sh                             # includes fixture oracle, replay and Poindexter CLI tests
```

The four focused checks build their own consumers or hosts. For just the replay-to-sheet check against an existing build, run `python3 tests/check_poindexter_cli.py`; `FINPRED_EXE` can select the compiled CLI by absolute path.
