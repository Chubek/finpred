# Yieldcraft strategy selection

`FINPRED_STRATEGY` is a file path. For example, from the project root:

```sh
FINPRED_STRATEGY=strategies/lead-quadratic.ottomat bin/finpred run
bin/finpred explain <run-id>
```

Choose one of these five files to set the intended percentile. The table
uses the default fixtures: 26 days to arrival, two nights, five comparable
properties. All amounts are **EUR cents per night**.

| File | Target rule | Intended bps | Intended cents | Selected bps | Final cents |
| --- | --- | ---: | ---: | ---: | ---: |
| `value-p40.ottomat` | Fixed P40 | 4000 | 17100 | 4000 | 17100 |
| `balanced-p55.ottomat` | Fixed P55 | 5500 | 17800 | 5500 | 17800 |
| `premium-p75.ottomat` | Fixed P75 | 7500 | 19000 | 7500 | 19000 |
| `lead-linear.ottomat` | Linear P40 → P75 | 5011 | 17507 | 4000 | 17100 |
| `lead-quadratic.ottomat` | Quadratic P40 → P75 | 4292 | 17217 | 4000 | 17100 |

These policies choose the target independently of the validated scenario's
`target_bps` and `curve`. For `d` civil days to arrival, capped at 90, the
curves add `floor(3500 × d / 90)` or `floor(3500 × d² / 8100)` to 4000 bps.
The matcher contributes one feasible whole-stay bundle per independent
property. Type-7 interpolation rounds half up to whole-stay cents before
division and half-up rounding to nightly cents.

The P40 shortcut applies when moving down saves **strictly less** than
`shortcut_cents`; equality keeps the intended price. Both curves in the
table save less than the fixture threshold of 500 cents. Floor, cap and
maximum movement then constrain the candidate. For example, limiting movement
to 200 cents from 17500 raises the linear policy's 17100 candidate to 17300.
Every recommendation has `published=false`.

With no override, `yieldcraft.ottomat` uses the scenario target, or its
curve when the target is zero. Its `ottmat 1` header is a declaration syntax
version, just as `ottmat 2` is for named profiles. The CLI writes only
[`finpred-run@2`](../docs/RUN_FORMAT.md) for both; there is no writer or
option for `finpred-run@1`.

For named profiles, the verified lineage and trace identify
`yieldcraft.<name>@1` and the BLAKE3 digest of the exact declaration bytes;
the recommendation JSON retains the SDK family `yieldcraft.percentile@1`
and its strategy digest. Neither identifier selects a run format.
`replay`, `explain`, `evidence`, and `poindexter` use the stored declaration,
so they work even if the live policy file is unavailable. Archived
`finpred-run@1` records with the scenario policy are read-only.

Selection follows the file contents, not the filename. Each named file has
an `ottmat 2` header, the seven fixed graph declarations, and one versioned
`profile` line. An unknown name, a mismatched target for a known name, or
an incompatible graph is rejected before creating a run. Changing LF to
CRLF retains the declared policy but changes the raw digest and run ID.
The parser also accepts `ottomat` for both header versions. The packaged
default keeps its original `ottmat 1` bytes and the named profiles keep
their `ottmat 2` bytes to preserve the pinned `finpred-run@2` IDs. Changing
the header spelling changes the raw digest and therefore the run ID.

## Scalar analysis examples

[`scalar-spread.ottomat`](scalar-spread.ottomat) is a v3 input for the
[native scalar host API](../source/ottomat/README.md#v3-scalar-analysis).
[`scalar-select.ottomat`](scalar-select.ottomat) adds
[v4 typed selection](../source/ottomat/README.md#v4-scalar-selection).
[`scalar-midpoint.ottomat`](scalar-midpoint.ottomat) uses the
[v5 registered diagnostic](../source/ottomat/README.md#v5-registered-scalar-algorithms).
None is a Yieldcraft profile: do not pass them as `FINPRED_STRATEGY`.
