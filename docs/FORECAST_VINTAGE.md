# Revision-aware guest-night forecast archives

This bounded, analysis-only API is in `forecast_baselines.vintage_replay`.
The existing `analysis.guest-nights-{forecast,score,evaluation,holdout}@1`
contracts, readers, policies and archival identities are unchanged. The new
family is `analysis.guest-nights-vintage-{catalog,request,forecast,evaluation}@1`.
None is a price input. There is no network, file, publication or store authority
in the module.

The legacy forecast CLI ranks a *single* snapshot for a requested window,
favoring coverage before provider update and ingestion. This API resolves each
required month independently, so a visible one-month revision can supersede
one row in an earlier complete release without losing the other rows.

## Host inputs and evidence boundary

1. Freeze and separately pin the training catalog at issuance. Each catalog is
   a canonical object with keys `kind`, `version`, `snapshots`, in that order.
   `snapshots` is an array of 0–64 distinct raw snapshot BLAKE3 IDs sorted
   lexicographically (ascending ASCII). Use compact JSON with one trailing LF.
   The catalog ID is BLAKE3 of those exact bytes. A pure `Entry` callback
   returns the exact canonical offline Dragnet guest-night snapshot and its
   ID at each index. Each snapshot is bounded at 4096 bytes/three observations.
2. Supply the canonical request with keys `kind`, `version`, `issued_at`,
   `target_month`, `horizon_months`, in that order, and the independently
   chosen `training_cutoff`. The cutoff may equal but cannot follow issuance.
   `target_month` must be exactly `horizon_months` UTC calendar months after
   the issue month. Horizons 1–11 are accepted; this keeps even the seasonal
   lag before the issue month. A required lag outside the snapshot calendar
   is absent. The underlying UTC calendar supports years 1970–2399, and
   scoring requires that the following month boundary also be representable.
3. Supply expected model/scorer code pins in `Selection`, separately from the
   trusted linked code subjects in `Linked`. A host integrating this API
   should derive pins from exact linked build subjects (including the
   resolver, projection and arithmetic dependencies); the synthetic harness
   uses explicitly test-only source pins. The host must not obtain trust
   roots by rehashing the candidate archive alongside it.

`Guest.project` rechecks raw bytes, fixed series dimensions (Eurostat
`tour_occ_nim`, EU27_2020, I551–I553, TOTAL, guest-nights), digests, the canonical
source profile, and that the provider publication follows the end of each
observed month. The resolver validates **all** catalog members, including
future ones, but only lets a row participate when the snapshot's checked
`source_as_of` is at or before the requested cutoff. The source as-of is not
earlier than ingestion, receipt, or publication. An older release captured
later does not override a newer provider release. The latest eligible
provider instant for each *required* month wins. Explicit provider null
supersedes a known value; an omitted month does not. Equally recent candidates
must agree on value and flag, or the operation fails for ambiguity. Equivalent
captures choose the earliest local `source_as_of`, then lexicographically
smallest digest; conflicting obsolete revisions do not block a newer one.

BLAKE3 is an integrity check, not provider authentication, proof of
completeness, or evidence of authorized use. A trusted host is responsible
for provider authenticity, the completeness of the admitted vintage history,
and validation of actual rights/terms, retention, capture and source-byte
records referenced by the snapshot. The API checks reference syntax/profile,
not legal entitlement. If a source cannot lawfully be retained, do not
onboard it or claim durable replay. The tests use synthetic snapshots only.

## Issue, evaluate, replay

| Model ID | Point method |
| --- | --- |
| `forecast.vintage-moving-average-3@1` | Mean of three consecutive complete months strictly before the UTC issue month. The estimate is flat across supported horizons. |
| `forecast.vintage-seasonal-naive-12@1` | Target calendar month minus twelve. |
| `forecast.vintage-last-complete-month@1` | Exact month before issuance, not the most recent nonmissing value. Flat across horizons. |

`issue` verifies the input catalog and emits an independently content-addressed
forecast. It records the original request digest, issue and training times,
calendar target and horizon, selected per-month raw snapshot identities,
source clocks and provider flags, and model/code/resolver policies. Only
selected inputs enter forecast bytes: adding a valid future or irrelevant
snapshot does not change the numerical forecast or its ID. The host must
retain the separate training catalog ID alongside issuance, to pin the exact
candidate set for later replay.

`evaluate` takes the original request, the original training catalog, and the
trusted forecast ID and archived bytes. It reissues the exact forecast and
requires byte and identity agreement before using the independently pinned
actuals catalog. The scoring cutoff must be after issuance and at/after the
UTC target month end; actuals obey the same per-month resolver as training.
Output binds both catalog IDs, both cutoffs, the issue/target/horizon, the
forecast ID, model/scorer code and policy pins, the selected actual vintage,
and exact signed (`estimate - actual`) and absolute error. `replay` also
requires the expected evaluation ID and the old evaluation bytes to match
recomputation. Changing even the unselected catalog members changes the
evaluation identity. Successful output is compact newline-terminated JSON,
with no floating-point conversion. Reduced fractions have integer numerators
and denominators of 1 or 3. Individual counts are at most `999999999999`.

`available` rows include a real count (zero is valid); `unknown` rows include
the provider's explicit null and its provenance; `absent` rows carry neither
value nor provenance. No imputation or probability distribution is inferred.
A forecast with any missing required input is `unknown` /
`insufficient_evidence`. An evaluation with missing actuals is `unknown` /
`missing_actual`, even if the forecast was also unknown; with an available
actual and unknown forecast, the reason is `insufficient_evidence`. Unknown
evaluations have null errors and must be counted, not silently filtered, in a
future aggregation.

Return status: `0` artifact with detached BLAKE3 ID and exact bytes, `1`
invalid request, chronology, pin or catalog bounds/ID syntax, `2` invalid
catalog membership or evidence, `3` ambiguous latest eligible revision, `4`
wrong archived forecast ID or bytes, `5` wrong archived evaluation ID or
bytes. Rejection returns neither ID nor bytes. Use the forecast schema with
the evaluation schema in a local Draft 2020-12 registry; no schema network
fetch is required. Schemas check shape, not canonical bytes, chronology,
fraction reduction or provenance; use recomputation for those.

For downstream consumers, the lossless comparison keys are model/pins,
request and archive IDs, origin/cutoffs, target/horizon, and the exact
guest-night fractions. This API is not wired into the CLI/registry or storage.
It does not implement schedule-wide model selection, sample coverage
aggregation, prediction intervals, calibration, probabilistic metrics, or
empirical validation. A host evaluating many origins should freeze splits and
candidate choices independently of holdout outcomes, preserve individual
unknowns, and group by horizon and scoring-vintage policy rather than pooling
unlike rows.
