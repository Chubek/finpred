# Yieldcraft strategy selection

`FINPRED_STRATEGY` is a file path. For example, from the project root:

```sh
FINPRED_STRATEGY=strategies/lead-quadratic.ottmat bin/finpred run
bin/finpred explain <run-id>
```

Choose one of these five files to set the intended percentile. The table
uses the default fixtures: 26 days to arrival, two nights, five comparable
properties. All amounts are **EUR cents per night**.

| File | Target rule | Intended bps | Intended cents | Selected bps | Final cents |
| --- | --- | ---: | ---: | ---: | ---: |
| `value-p40.ottmat` | Fixed P40 | 4000 | 17100 | 4000 | 17100 |
| `balanced-p55.ottmat` | Fixed P55 | 5500 | 17800 | 5500 | 17800 |
| `premium-p75.ottmat` | Fixed P75 | 7500 | 19000 | 7500 | 19000 |
| `lead-linear.ottmat` | Linear P40 → P75 | 5011 | 17507 | 4000 | 17100 |
| `lead-quadratic.ottmat` | Quadratic P40 → P75 | 4292 | 17217 | 4000 | 17100 |

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

With no override, `yieldcraft.ottmat` retains the legacy rule: use the
scenario target, or its curve when the target is zero. Named profiles use
v2 runs only. The verified lineage and trace identify `yieldcraft.<name>@1`
and the BLAKE3 digest of the exact declaration bytes; the recommendation
JSON retains the SDK family `yieldcraft.percentile@1` and its strategy
digest. `replay` and `explain` use the stored declaration, so they work
even if the live policy file is unavailable.

Selection follows the file contents, not the filename. Each named file has
an `ottmat 2` header, the seven fixed graph declarations, and one versioned
`profile` line. An unknown name, a mismatched target for a known name, or
an incompatible graph is rejected before creating a run. Changing LF to
CRLF retains the declared policy but changes the raw digest and run ID.
