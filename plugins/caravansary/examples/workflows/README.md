# Offline market workflows

These examples are fictional. `booking.example` and `agoda.example` are fixture
identity labels, not destinations. Nothing here contacts a provider, interprets
a missing quote as unavailability, converts currencies, or publishes a price.
Run the commands from the repository root after `bin/caravansary build`.

## Discover, scrape and collect

```sh
examples=plugins/caravansary/examples
workflows=$examples/workflows
clock=2026-11-26T10:00:00Z

bin/caravansary discover "$workflows/canal-market.caf" \
  --input-root "$examples" --host-grants "$workflows/host-grants.json" --as-of "$clock"

bin/caravansary scrape "$workflows/canal-market.caf" --source booking_profile \
  --input-root "$examples" --host-grants "$workflows/host-grants.json" --as-of "$clock"

bin/caravansary collect "$workflows/canal-market.caf" \
  --input-root "$examples" --host-grants "$workflows/host-grants.json" --as-of "$clock"
```

- `discover` reads the declared discovery sources from fixed local candidate
  captures. It lists four fixture candidates with deterministic IDs, distances,
  statuses and provenance, but does not verify that they are distinct physical
  properties.
- `scrape` reads exactly one explicitly selected profile fixture; it does not
  fetch the listing link.
- `collect` returns normalized results for **all** script sources, including the
  profile. It refuses the entire run if a selected source lacks its own
  `collect` grant. It does not persist a collection or create new grants.

The fixture script declares IDs only. A trusted operator explicitly selects a
local `caravansary.host-grants@1` registry. For each source the registry binds the
exact fixture ID, provider, fictional source URL, capture clock, provider
operation (`candidates` or `profile`), permitted CLI operations, relative file
path, and raw capture SHA-256. Grant paths are relative to the registry. Every
input, including the script and registry, must be inside explicitly approved
`--input-root` directories after lexical and resolved-path checks. Use separate
roots when necessary; do not point a root at unrelated private data. Never
select an untrusted registry as your host policy.

The optional script `profile_url` is inert metadata, and the `schedule` section
neither registers nor runs a job. Market verbs do not accept provider
credentials, live flags, or transport overriders.

## Predict a guarded nightly position

```sh
archive=$(mktemp -d)

bin/caravansary predict "$workflows/canal-market.caf" \
  --input-root "$examples" --host-grants "$workflows/host-grants.json" --as-of "$clock"

bin/caravansary predict "$workflows/canal-market.caf" \
  --input-root "$examples" --host-grants "$workflows/host-grants.json" --as-of "$clock" \
  --pricing-input "$workflows/pricing-input.json" > "$archive/position.json"
```

The first run **abstains**: HTML prices do not establish the exact stay,
occupancy, terms and physical identities needed for comparison. The second
run qualifies the separate `caravansary.market-pricing-input@1` file as synthetic
fixture coverage. It requires an exact policy scope, explicit physical links
to eligible discovered candidates, and supplied planner-row/observation pairs.
It neither turns HTML prices into coverage nor trusts a shape as evidence of
a real booking. The example uses three distinct properties and a one-night
stay; the median is 14,400 GBP minor units, capped to the 12,500 minor-unit
movement guardrail. No price is published.

## Backtest first-party rooms sold, then review artifacts

```sh
bin/caravansary backtest "$workflows/rooms-sold-backtest.json" \
  --input-root "$examples" --as-of "$clock" > "$archive/backtest.json"

bin/caravansary history "$archive/backtest.json" "$archive/position.json" \
  --input-root "$archive"
bin/caravansary explain "$archive/position.json" --input-root "$archive"
```

The separate `caravansary.market-backtest-input@1` fixture holds three target
dates with finalized UTC-day rooms-sold observations and known publication
times. On each fold the fixed 28-day baselines use only training observations
available at that decision time. An intentionally late revision does not
leak into training. The weekly and all-days absolute error sums are 3 and 4
rooms respectively, over the same three scored folds. This measures rooms sold,
not latent demand, elasticity or market viability.

Workflow outputs are one canonical JSON line with
`kind: "caravansary.market.<verb>@1"`, explicit `as_of`, fixture qualification,
input digests, a structured `result`, and `publication_allowed: false`.
`artifact_digest` is SHA-256 of the canonical body without that field.
`history` reads explicitly named artifacts, verifies the digests and sorts by
UTC instant then digest. `explain` displays recorded details, including reasons
for abstention and the exact evidence used when available. Neither command
recomputes a recommendation or treats a digest as a signature. An abstention
is a successful report; malformed, unauthorized or failed fixture acquisition
exits nonzero without a result on stdout.

## Supervise one registered offline scrape

```sh
jobs_parent=$(mktemp -d)
state=$jobs_parent/state
due=2026-11-26T10:01:01Z
bin/caravansary jobs --state "$state" init
bin/caravansary jobs --state "$state" source-add CanalScript \
  < "$workflows/canal-market.caf"
bin/caravansary jobs --state "$state" source-add CanalCapture \
  < "$examples/providers/booking-profile.html"
bin/caravansary jobs --state "$state" source-add CanalManifest \
  < "$workflows/scheduled-scrape.cvs"
bin/caravansary jobs --state "$state" market-profile-add CanalScrape CanalManifest
bin/caravansary jobs --state "$state" schedule CanalScrape \
  --at 2026-11-26T10:01:00Z --once "$due"
bin/caravansary jobs --state "$state" dispatch --at "$due"
# Use the decimal ID returned by schedule:
bin/caravansary jobs --state "$state" result-show ID "$due"
```

`CVSCRAPE1` pins independently registered script and capture bytes, the one
allowed fixture profile and the replay clock. Dispatch uses the fixed native
runner and persists the exact successful scrape artifact. It is identical to
the direct scrape above, although the dispatch deadline is later than the
artifact clock. Dispatch is a foreground, one-at-a-time operation; the example
does not install a service or promise exact-once execution. Script declarations
cannot register a source, enable a profile, or start a process.

Run `python3 tests/caravansary_market.py --with-jobs` with the built launcher
to verify these paths, replay parity and grant/root denials. The native market
binary and its fixed `finpred-caravansary-market-probe-v1` sibling must be
installed together in a trusted executable directory on Linux with procfs,
pidfds and `close_range` support (Linux 5.11 or newer). The immediate directory
and companion must be owned by root or the effective user and not writable by
group or others. Keep all ancestor directories trusted and stable as well.
