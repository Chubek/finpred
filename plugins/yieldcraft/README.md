# `yieldcraft.percentile` — built-in On1x strategy

## Run `bin/yieldcraft`

From the repository root:

```sh
make
./bin/yieldcraft
```

This uses the existing FinPRED CSV inputs and writes a local, replayable
recommendation. It does not start Dragnet unless requested. To acquire one
Dragnet batch and price from its structured offers:

```sh
make dragnet
./bin/yieldcraft --scenario scenario.csv --valuation valuation.csv \
  --dragnet Dragnet.json --save-capture captured-offers.jsonl
```

Use an [`offer-csv-v1` Dragnet config](../dragnet/README.md#optional-yieldcraft-adapter).
Basic and GPT extraction are not pricing inputs. For live acquisition, also
pass `--allow-host HOST` for each search/result host and `--allow-offer-host HOST`
for each trusted offer provider. The decision time in the scenario must not
precede the capture cutoff or live observations. No network access is granted
automatically.

To reuse saved evidence without invoking Dragnet:

```sh
./bin/yieldcraft --scenario scenario.csv --valuation valuation.csv \
  --capture captured-offers.jsonl
```

Select only a trusted capture. The launcher validates against the scenario's
`decision_at`, then supplies the verified offers to the existing pricing
engine. Empty, invalid, or late captures never fall back to `FINPRED_OFFERS`.
Optional `--strategy FILE` selects an existing strategy. Path flags are
relative to the caller; existing `FINPRED_*` inputs keep their normal
conventions. `--save-capture` keeps a separate, private verified capture
without overwriting an existing file, even if pricing subsequently fails.
The unchanged pricing archive stores the projected CSV, not the raw capture.
Nothing publishes a price or books a room.

## Call the On1x strategy

Call `plugins.yieldcraft.entry.recommend` with **snapshot contents**, in the
order scenario, offers, valuation. It accepts the same unquoted CSV profile as
FinPRED and returns the shared `core.contracts.Recommendation` record.
For example, inside an On1x host:

```on1x
import plugins.yieldcraft.entry as Yieldcraft;

fn nightly_minor(scenario: string, offers: string, valuation: string) -> i64
{
  let r = Yieldcraft.recommend("recommendation",scenario,offers,valuation);
  return r["recommended_cents"];
}
```

The only invocation mode is `recommendation`. The package checks the built-in
SDK descriptor, validates the scenario and valuation, and passes the offers
through the same bounded matcher, percentile strategy and guardrails as the
CLI. Errors such as `insufficient_evidence` use the existing `tool_fail`
path; no fallback price is returned. The entry point releases the pool and
distribution on successful evaluation. No array handles escape to the caller.

The host owns file access, snapshot identity, serialization and replay.
The package reads no files, writes no store and provides no publishing
operation. The [manifest](plugin.json) names a **compile-time** entry point;
FinPRED does not interpret it to load code. For the legacy engine the CLI
checks its registry binding and supplies `entry.recommend_profile` to the
plugin-independent runner. This typed handler takes validated scenario and
valuation records, offers CSV bytes, a profile name, an evidence collection
flag, and a buffer; the trusted host owns authorization and any persisted
lineage. For the persisted `pricing.recommendation@1`
envelope use `core.serialize.recommendation` with the host's verified IDs,
as illustrated by the [test consumer](../../tests/yieldcraft_package_consumer/main.on1x).

## Build and test from the FinPRED root

Use the pinned MuLIB checkout and compiler described in
[AGENTS.md](../../AGENTS.md). To link your own `host.on1x`, point the compiler
at the existing FinPRED modules and the package:

```sh
export MULIB_ROOT="${MULIB_ROOT:-$PWD/third_party/mulib}"
export ON1XC="${ON1XC:-$PWD/build/mulib/on1x/on1xc}"
export TMPDIR="${TMPDIR:-$PWD/build/tmp}" PYTHONDONTWRITEBYTECODE=1
mkdir -p "$TMPDIR" build
python3 "$MULIB_ROOT/on1x/tools/on1x-build.py" host.on1x --backend c11 \
  --on1xc "$ON1XC" --mulib-root "$MULIB_ROOT" \
  -I "$PWD/source" -I "$PWD" -o build/yieldcraft-host
```

To build and exercise the supplied independent consumer:

```sh
./tests/check_yieldcraft_package.py
```

The test uses temporary build and run directories under `$TMPDIR`. It compares
the serialized recommendation bytes for both fixtures to the historical
envelopes (with the corresponding v1 or v2 run ID), checks denied modes and
invalid evidence, and checks that the run directory stays empty.

### Verification, 2026-11-23

MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
`third_party/mulib/build/on1x/on1xc` SHA-256
`0d63fc81d978f1588df8700cf4222ceb0b4425af26a97a591395b751d331a9af`;
Linux `6.18.52-1-lts` x86_64 SysV, GCC `16.2.1`, C11. All of these checks
exited 0:

| Command | Observed result |
| --- | --- |
| `./tests/check_yieldcraft_package.py` | 4 matching envelopes, 5 denied modes, 5 invalid inputs |
| `python3 tests/check_fixtures.py` | 17100 cents/night (`lower_percentile_shortcut` in package output); 16000 cents/night (`guardrail_adjustment`); both envelopes `published:false` |
| `python3 tests/validate_static.py` | 16 application modules, 4 schemas |
| Isolated project build + `./tests/run.sh` (below) | Native selftest, both v1 fixture replays and both v2 fixture replays, unchanged stores on replay, all four JSON kinds validated, 32 pricing and 65 ingestion cases; `on1x_integration_ok=true` |

```sh
mkdir -p target
work=$(mktemp -d "$PWD/build/yieldcraft-host.XXXXXXXX")
export TMPDIR="$work" PYTHONDONTWRITEBYTECODE=1
FINPRED_BUILD_DIR="$work/app" ./bin/build.sh
FINPRED_EXE="$work/app/finpred" ./tests/run.sh
```
