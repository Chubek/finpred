# FinPRED v1 implementation notes and review checklist

## Provenance

- User-supplied design: `docs/USER_SPECIFICATION.md`.
- Inspected public MuLIB repository `Chubek/mulib`, `master` at
  `49de89acbc97efbee493d6b28d02c8f64ed4f725` (23 November 2026).
- Reviewed paths through GitHub connector: `on1x/README.md`,
  `on1x/KERNEL_DIRECT_USAGE.md`, On1x sample programs, On1xfile guide,
  `on1x/stdlib/{io,os,crypto,collections,text}`.
- On1x compile/link status: **not verified** (no checkout or compiler in the
  current environment). This document never treats source inspection as an
  independent signed ABI review.

## Architecture and isolation

```text
CSV/fixtures (local-only) -> On1x CSV/schema contract validation
                        -> As-of eligibility filter
                        -> Stay matching: room subset -> occupancy DP
                        -> One whole-stay gross price/property
                        -> Type-7 quantiles and curve
                        -> Shortcut and independent guardrails
                        -> pricing.recommendation@1 + explanation
                        -> immutable snapshots + run manifest
replay(manifest ID) -----^ (no artifact mutations or external actions)
```

`source/core/` owns validated scenario/offer/valuation values, date checks,
minor-unit money, serialization, CSV. `source/yieldcraft/` owns the bounded
whole-stay matcher and recommendation strategy. `source/automat/` checks the
first fixed typed DAG. `source/ottmat/` is a version 1 exact descriptor
frontend, not a second runtime. `source/sdk/` holds a closed-by-default
manifest policy. `source/store/` handles BLAKE3 identity, file snapshots and
run manifests. `source/cli/` performs the only allowed local file access.

The SDK stub admits exactly the built-in pure Yieldcraft strategy. It does
not load arbitrary plugins, map untrusted C pointers, or turn `unsafe` into
an authorization capability. It is a restrictive preparation for a future
SDK, *not* the cross-language plugin system described for phase 3.

## Exactness and economic semantics

- Every monetary input is a signed 64-bit **minor-unit integer**. Parsed
  prices, fees and taxes are bounded at 10^12 cents each; the gross sum must
  remain at most 10^12. The maximum four-room bundle is at most 4×10^12.
- A source row is already one **observed bookable room inventory unit**,
  with whole-stay base, total fees and taxes; the model makes **no** live
  availability or child policy inference. Separate adult, child and combined
  occupancy capacity are honored exactly by bounded DP.
- Only matching arrival/departure and currency, valid economics and
  as-of observations can enter the distribution. `observed_at` is the source
  timestamp; `ingested_at` is when that observation arrived, and both must
  precede `decision_at`. Recency uses an explicitly declared calendar-day
  bound, not an implicit 24-hour floating duration.
- Each eligible property contributes **one cheapest feasible whole-stay
  bundle**, preventing room-count bias. Cases without a bundle contribute
  no observation; infeasible property count is included in the trace.
- We compute quantiles in exact whole-stay minor units using
  Hyndman–Fan **type 7**, `h=(n-1)*p`, linear interpolation, half-up cent
  rounding. All observations in a scenario cover the same exact number of
  civil nights. Effective night rate uses a second half-up division by that
  number of nights. Prices are never stored as binary float.
- A scenario can pin target percentile (basis points 0..10000). If zero,
  the curve applies. Linear: `4000+3500*d/90`, quadratic:
  `4000+3500*d*d/8100`, with lead `d` clipped to [0,90]. All divisions
  truncate positive intermediate integers. P40 is the shortcut baseline.
- The monetary shortcut selects P40 only when `Ptarget-P40` is strictly
  less than `shortcut_cents`. The guardrail operation clamps the result into
  `max(floor,current-max_move)..min(cap,current+max_move)` and fails if this
  intersection is empty. A guardrail-adjusted reason supersedes shortcut.
- **No publishing happens**, regardless of input. Execution mode fails and
  no Action node is exposed in the fixed graph.

## Resource and security bounds

CSV at most 512 room rows and 2 MiB per file; 10 admitted offers per
property; at most 4 selected rooms and 8 adults/8 children; scenario
search_budget at most one million enumerated subsets. Each occupancy DP has
at most 81 states. Unknown CSV columns, quoted inputs and other currency
values fail closed. Script path selection is operator-controlled, not plugin
authority. The BLAKE3 digest syntax is checked when used as a filesystem
object name, preventing IDs that escape the artifact directory.

The local store uses `artifacts/blake3-{hex}.txt` and
`runs/{hex}.txt`. Existing paths are never deliberately overwritten with
different content; replay independently rehashes all fetched snapshots and
recomputes the output and trace from immutable inputs. However, file writes
are **not atomic**, storage is not locked against racing processes, directory
symlink safety is not enforced, and no authenticated audit ledger is claimed.
These must be upgraded before operational production usage.

## Module and kernel decision

MuLIB's `mulib-staymatch.h`, `mulib-pricecurve.h`, `mulib-contract.h` and
other headers are useful future integration targets, but in the checked
On1x repository they do not have admitted general callable KernelBind
profiles. Instead of silently claiming approval, the bounded matching,
quantile and policy computations are implemented in On1x. MuLIB's
standard-library C11 bridges provide local I/O, i64 array handles and
BLAKE3 hashing; they are treated as raw trusted SDK facilities and require
operator review. The existing Histprice/PriceOpt reviewed profiles are not
needed for this price-by-comparables vertical and no dummy forecast model is
invented.

## Acceptance record

| Gate | Artifact | Status |
|---|---|---|
| P0 units/dates/contracts | Strict On1x CSV semantic validation and four versioned JSON Schemas | Source implemented; not compiled |
| P1 local store/CLI | Immutable BLAKE3 snapshots, as-of input filtering, deterministic run manifests and replay | Source implemented; not executed |
| P2 Yieldcraft | Bounded exact multiroom matching, property dedup, Type-7 quantile, curves, shortcut, guardrails, trace | Source implemented; Python fixture oracle passed |
| P3 Automat | Typed checked fixed DAG, action/effect denial | Narrow source implementation |
| P3 Ottmat | Typed exact v1 strategy descriptor | Narrow source implementation |
| P3 SDK | Closed descriptor allowlist | Narrow source implementation; **not** plugin loading/ABI/isolation |
| P4/P5 | durable scheduler, approvals, action reconciliation, Poindexter/FX/etc. | Not implemented |

## Next build verification

1. Populate `third_party/mulib` with the recorded commit, including required
   LibStone submodule; build the On1x compiler with CMake.
2. Run `bin/build.sh` and fix compile/signature issues against that exact
   compiler version. There has been no opportunity to perform this step.
3. Run `tests/run.sh`; inspect output artifact JSON against all four schemas,
   verify replay, and record exact compiler, C ABI and compiler warnings.
4. Add malformed, overbudget, tie, integer-overflow, DST, inventory and
   plugin-denial tests against the actual On1x runtime. The selftest, fixture
   oracle and shell integration script are a **starting set**, not the full
   mandatory acceptance matrix in the design.
5. Introduce a durable transactional store and host-controlled permission
   gateway before adding any external source, plugin or action.
