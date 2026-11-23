# Point-in-time guest-night baselines

`forecast_baselines.model` contains two pure analysis models, not pricing
policies. The linking host chooses which handlers to expose and supplies the
code digest of its exact build subject to `descriptor(name, code)`. The
descriptors bind each handler's version and policy digest. No model can open
a source, modify a store, or publish a result externally.

| Handler | Version 1 policy |
| --- | --- |
| `forecast.moving-average-3@1` | Mean of the three consecutive months immediately before the UTC issuance month. |
| `forecast.seasonal-naive-12@1` | Observation for the target calendar month one year earlier. |

Each takes `training` (`analysis.guest-nights-monthly@1`) and `request`
(`analysis.guest-nights-forecast-request@1`) in that order. `training` is one
frozen DATA1 projection, not a live or general series and not a revision
resolver. The host must select the snapshot as of the training cutoff and
verify its bytes and lineage with `core.guest_nights.verifies` or an equivalent
trusted replay path. The model checks the canonical projection profile and
requires its cutoff to equal the SDK request cutoff. Digest comparisons do not
authenticate the source.

The forecast request is canonical JSON in order `issued_at`, `target_month`,
`horizon_months`, no spaces, one trailing LF. The training cutoff is supplied
by the SDK, cannot follow issuance, and is not the scoring cutoff. The only
supported horizon is the calendar month immediately following issuance.
If any month needed by the model is absent or unknown, output is `unknown`
with `insufficient_evidence`; a real zero is usable. An unknown row outside
the model's window does not degrade an otherwise available estimate.
Available estimates are reduced rationals, represented by a numerator and
positive denominator. No intervals are estimated. Output is analysis-only,
with no currency, and includes a digest of the exact training projection.
The graph/host owns request-parent lineage and the published artifact envelope.
The JSON Schemas cover shape; the handler checks canonical bytes and temporal
rules.

`TMPDIR="$PWD/build/tmp" python3 tests/check_forecast_baselines.py` compiles an
independent C11 consumer and invokes both through `sdk.callable`. The fixture
uses synthetic snapshots and a separate frozen scoring cutoff. An independent
Python `Fraction` oracle checks the three chronological origins and two
holdout errors per model. Repeating the invocation checks output bytes
without acquisition, a writable store, or a Graph IR dependency.

`TMPDIR="$PWD/build/tmp" python3 tests/check_forecast_graph.py` compiles a
separate host that runs both model nodes in one Automat financial Graph IR
graph. It also builds the offline Dragnet decoder (`pkg-config`, libxml2
and Jansson required). The host selects one visible snapshot per window
from the frozen fixture, exercises the real decoder and On1x normalization
on synthetic captures, and passes verified DATA1 projections to the graph.
Different processes execute and replay using exact frozen input and
expectation bytes. The test checks both node pins and parents, rejects future
training and a rehashed wrong-parent artifact, and proves that switching
only the March moving-average revision leaves the seasonal artifact
unchanged at the same cutoff. It does not establish a generic revision
catalog, FX support, durable replay storage, or forecast accuracy on real data.
