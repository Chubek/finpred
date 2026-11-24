# Developing a FinPRED plugin

FinPRED integrates **trusted On1x code at build time**. Dragnet produces web
captures, Yieldcraft computes a price from snapshots, and Poindexter presents
a verified run. Copying a `plugin.json` into `plugins/` does not register code
or add a CLI command.

The [engine registry](source/sdk/README.md#engine-registry) admits only
host-registered call sites. It does not dynamically load packages from disk.

| Package and descriptor | What the caller supplies | What the caller gets |
| --- | --- | --- |
| [Dragnet capture reader](plugins/dragnet/dragnet_batch.on1x) | Frozen `dragnet.batch@1` bytes and consumer cutoff | Validated batch metadata and ordered page records; no network handles |
| [Yieldcraft `Strategy`](plugins/yieldcraft/plugin.json) | Mode and three CSV snapshots: scenario, offers, valuation | An On1x `Recommendation` record, including the nightly price in EUR cents |
| [Poindexter `View`](plugins/poindexter/plugin.json) | Verified identities and scalar fields from one replayed run | `(true, csv)` for a one-row pricing sheet, or `(false, diagnostic)` |

The host selects inputs, opens files, verifies provenance and decides where
output goes. Declarations document the reviewed code; they do not sandbox
arbitrary code in the host process. A mode string, a descriptor match and a
recommendation each grant **no authority to publish a price**.

## Dragnet: consume a capture from any module

From the repository root, with the [pinned On1x toolchain](INSTALL.md) available:

```sh
make dragnet
./bin/dragnet --handoff --config plugins/dragnet/examples/Dragnet.json > capture.jsonl
./bin/finpred dragnet-inspect capture.jsonl 2026-11-24T00:00:00Z
```

For your own On1x consumer, compile from the repository root with
`-I "$PWD/source" -I "$PWD"` and import
`plugins.dragnet.dragnet_batch as Dragnet`. Pass **bytes**, not a path, to
`Dragnet.read(bytes, cutoff)`, then use `Dragnet.page()` to access records.
The [compiled example](tests/dragnet_batch_consumer.on1x) links no acquisition
or pricing code. The [wire contract](plugins/dragnet/README.md#consumer-contract)
also works for readers outside On1x. Digests bind bytes, not publisher
identity; consumers validate data for their own domain and choose their own
destinations. The reader is not a dynamically registered SDK Source.

## Yieldcraft: call the strategy from On1x

```on1x
import plugins.yieldcraft.entry as Yieldcraft;

fn nightly_minor(scenario: string, offers: string, valuation: string) -> i64
{
  let r = Yieldcraft.recommend("recommendation",scenario,offers,valuation);
  return r["recommended_cents"];
}
```

Compile the host with `-I "$PWD/source" -I "$PWD"` from the FinPRED root. The [package build example](plugins/yieldcraft/README.md) shows the C11 driver invocation; the [independent consumer](tests/yieldcraft_package_consumer/main.on1x) also shows serialization. `recommendation` is the only invocation mode. The [return record](source/core/contracts.on1x) carries the reason, selected percentile and evidence counts. It contains no store handle or run ID. To emit `pricing.recommendation@1`, the host supplies verified run and parent IDs and the strategy identity to `core.serialize.recommendation`; to persist and replay a run, use the [CLI](GUIDE.md).

Each feasible property contributes one cheapest room bundle. Limits include 512 offer rows, 10 eligible rooms per property, 4 selected rooms, 8 adults, 8 children and a search budget of at most 1,000,000. Fewer than the required independent properties yields `insufficient_evidence` via `tool_fail`, not a fallback price. The frozen fixtures return `17100` (`lower_percentile_shortcut`) and `16000` (`guardrail_adjustment`) cents per night. The CLI shares the matcher and strategy implementations and owns its own evidence, lineage and replay path.

The market-positioning CLI writes
[`finpred-run@2`](docs/RUN_FORMAT.md#v2-market-positioning-writer-and-verifier).
Expected contribution uses its separate [`finpred-run@3`](docs/RUN_FORMAT.md#v3-expected-contribution)
format. Neither format versions this plugin or its output contract. The pure
package neither selects a run format nor accesses archives.

For a pure algorithm registered with the scalar graph (also available via
`run --engine scalar`), see the [scalar diagnostics package](plugins/scalar_diagnostics/README.md).
It is linked by the host, not discovered through an SDK descriptor.

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

The [C11 SDK](source/sdk/README.md) is independently linkable without MuLIB.
For built-in SDK v2 descriptors, use `<finpred/sdk_v2.h>`: look up the package,
then check its requested use against the host's linked dependencies, resource
ceilings and grants. The [built-in On1x hosts](source/sdk/static_host.on1x)
perform this check before dispatch and grant no external capabilities.
The [installation instructions](INSTALL.md#install-the-descriptor-sdk)
also cover a relocatable CMake package and metadata-only Python bindings.

The legacy v1 API describes **only** `yieldcraft.percentile`. Include `<finpred/sdk.h>` and link `-lfinpred_sdk`. The sequence in the [C consumer](tests/sdk_consumer.c) is:

1. `finpred_sdk_lookup_v1(FINPRED_SDK_ABI_V1, "yieldcraft.percentile", &plugin)` obtains an opaque handle. Check for `FINPRED_SDK_OK` before use.
2. `finpred_sdk_describe_v1(plugin)` exposes the version, contracts, effect, required capabilities and numerical limits. The library owns the handle and descriptor; neither is freed by the caller. Both expire when the library is unloaded.
3. `finpred_sdk_check_v1(plugin, "Strategy", "pricing.recommendation@1", "pure", "recommendation", 0)` checks compatibility only. Unknown names return `NOT_FOUND` on lookup; wrong ABI, kind or output contract returns `INCOMPATIBLE`; nonzero capability requests, unsupported effects or modes return `DENIED`. See the [public header](source/sdk/sdk.h) for the full status names.

Both the C check and the [On1x allowlist](source/sdk/sdk.on1x) recognize `analysis`, `recommendation` and `simulation` for this descriptor. Neither invokes pricing. The Yieldcraft package itself requires `recommendation`; `execution` is denied. Building the SDK as a shared library gives native consumers the same descriptor API, not an extension loader.

## Integrate and test a new trusted module

1. **Choose a narrow entry point.** Pass validated values or frozen contents. Keep file selection, output and run verification in the host. Specify units, time cutoffs, failure behavior and bounds. Reuse the [versioned contracts](contracts/) when your data has those semantics.
2. **Make the build explicit.** For a reusable local library, copy the layout of [Poindexter](plugins/poindexter/): `On1xfile` declares `kind library`, `On1xfile.m` lists the implementation, and `On1xfile.i` lists the `.on1xi` interface. Declare the dependency in your host project and import it by name; the [standalone consumer project](tests/poindexter_consumer/On1xfile) stages the dependency under `vendor/poindexter`. For a source with host-specific I/O, see [Dragnet's acquisition host](plugins/dragnet/source/main.on1x).
3. **Document and wire the exact call.** Record the name, package and SDK versions, kind, contracts, entry point, effects, capabilities and bounds in `plugin.json`. These are package descriptions, not a universal manifest parser. An additional CLI feature needs an explicit host call and rebuild. The existing fixed graph and Ottomat declaration do not schedule new packages. Preserve old run identities and replay behavior if changing persisted semantics.
4. **Test across the host boundary.** Compile a separate consumer; compare fixture bytes and units, test malformed inputs and denied modes, and check for unintended writes. For replay views, include missing and corrupted runs as well as valid runs. Trusted linkage is not isolation. The [optional offline process worker](docs/OFFLINE_WORKER.md) is separate from these in-process entry points and grants no network or action authority.

Run from the root on Linux; [INSTALL.md](INSTALL.md) covers `MULIB_ROOT`, `ON1XC` and the Python `jsonschema` test dependency. Set `TMPDIR` to a writable executable filesystem with space for disposable builds.

```sh
make                                # build the pricing CLI used by the Dragnet test
make dragnet-search-test            # capture framing, cutoff, provenance, independent consumers
python3 tests/check_yieldcraft_package.py   # fixture envelopes, denied modes, invalid inputs
python3 tests/check_poindexter_package.py   # independent consumer, CSV bounds and rejections
python3 tests/check_sdk.py                  # build/install C SDK, link consumer, compare metadata

./bin/build.sh
python3 tests/validate_static.py
./tests/run.sh                             # includes fixture oracle, replay and Poindexter CLI tests
```

The four focused checks build their own consumers or hosts. For just the replay-to-sheet check against an existing build, run `python3 tests/check_poindexter_cli.py`; `FINPRED_EXE` can select the compiled CLI by absolute path.
