# Poindexter pricing sheet

For the interactive **spreadsheet with formulas and worksheet scripts**,
see the [terminal workbench](workbench/README.md). The read-only View
below supplies its verified pricing input.
The optional [ImmGTK spreadsheet](gui/README.md) opens and edits the
same local workbook format using the same On1x worksheet engine.

For v1/v2 market-positioning runs, `poindexter.pricing-sheet` 1.0.0 compares **one unpublished recommendation**
with its scenario’s frozen current valuation. It returns a spreadsheet-ready
CSV: a header, one data row, and a final LF. Prices are nightly EUR cents.
The signed `change_minor` is `recommended_minor - current_minor`. For the
main fixture, `17100 - 17500 = -400` cents per night. The change is a price difference, not
earned revenue, an expense or a journal entry.

| CSV column | Meaning |
|---|---|
| `view` | `poindexter.pricing-sheet@1`, the column and calculation version |
| `source_run` | `run:<id>` accepted by host replay; strip `run:` for CLI lookup |
| `source_recommendation`, `source_valuation` | For v1/v2, `blake3:<digest>` of the exact normalized `pricing.recommendation@1` and `pricing.valuation@1` JSON bytes |
| `currency`, `price_basis` | `EUR`, `room_night` |
| `current_minor`, `recommended_minor`, `change_minor` | Signed integer minor units; both input prices are in `[0, 10^12]` |
| `reason`, `published` | Yieldcraft’s reason verbatim and the literal `false` |

### Run the view from a replay host

The CLI integration uses `bin/finpred poindexter RUN_ID` with the same
`FINPRED_HOME` as the original run. Redirect stdout to save the CSV or
import it into a worksheet; interpret the three minor-unit columns as
integers. Source identities have text prefixes so a spreadsheet cannot
round an all-digit digest. The sheet performs no workbook updates or
formula evaluation.

### v3 own-demand contribution sheet

The same command emits `poindexter.contribution-sheet@1` for a
`finpred-run@3` archive. It emits no CSV until replay has verified the
canonical manifest and lineage, loaded all frozen inputs, validated the
strategy, and matched both recomputed output artifacts. This does not
change the archive, replay output, or v1/v2 CSV format.

The first eleven columns retain the same order; `source_recommendation`
identifies the archived `pricing.contribution-recommendation@1` JSON, and
`source_valuation` identifies the **raw valuation CSV** in this v3 archive,
not a normalized valuation envelope. The reason is
`max_expected_contribution`, and `published` is `false`.

| Additional CSV column | Meaning |
|---|---|
| `source_demand` | `blake3:<digest>` of the frozen raw `pricing.demand@1` CSV |
| `marginal_cost_minor` | Variable cost in EUR cents per room-night |
| `expected_room_nights_milli` | Expected demand at the recommended price, in thousandths of a room-night |
| `expected_contribution_minor_milli` | Exact integer text `milli_minor:<decimal>`: `(recommended_minor − marginal_cost_minor) × expected_room_nights_milli`, in thousandths of a EUR cent |
| `scale` | `1000`; divide a scaled quantity by this to get room-nights or EUR cents, respectively |

The contribution total is a modeled expectation, not a price, realized
revenue, or a payable amount. It can be as large as `10^18` scaled units,
so the text prefix prevents rounding by spreadsheet software. The sheet
has one header and one row, and is bounded to 768 ASCII bytes.

### Embed the On1x View

Declare the package inside the host’s On1xfile:

```text
dependency "poindexter" local "plugins/poindexter"
```

Import `poindexter.sheet as Sheet`. The checked [interface](src/sheet.on1xi)
accepts values, never paths. The host verifies the requested ID, frozen
parents, normalized envelopes and recomputed outputs as described in
[the run format](../../docs/RUN_FORMAT.md) **before** calling the renderer.
Use the replayed valuation and recommendation from that same evaluation:

```on1x
let (ok,csv) = Sheet.render(id,rec_digest,nv,sx_text(s["currency"]),"room_night",
  v["current_cents"],r["recommended_cents"],sx_text(r["reason"]),false);
if !ok { tool_fail(csv); }
IO.basis_text_io_print(csv);
```

`nv` is the normalized valuation object digest, not the raw valuation CSV
digest. `rec_digest` is the recommendation object digest, not the trace
digest. The version-1 serializer fixes `room_night` and `published=false`;
the valuation validator checks the currency against the scenario. Both v1
and v2 run formats can supply these values. `render` checks the projected
fields, not the caller's integrity assertions. A caller supplying invented
values does not thereby obtain a verified report.

The same interface exports `render_contribution` for trusted hosts. It
validates field shape, units, bounds and the contribution calculation, but
does not verify the archive. The FinPRED host passes it replayed values and
the raw valuation and demand digests from the verified manifest.

The [descriptor](plugin.json) still describes the v1/v2 pricing view, a pure,
statically linked SDK-1 `View` with no host capabilities. Neither renderer
reads files, writes artifacts or has a publishing path. A successful v1/v2 result is at most 512
ASCII bytes, with fixed/allowlisted text, canonical decimal integers and
three bounded digest fields. It is derived presentation data, not a fifth
stored contract or a change to a historical run. Worksheet code executes
only in the separate workbench, not during replay.

### Verify

From the repository root, with the pinned MuLIB compiler or `MULIB_ROOT`
and `ON1XC` overrides:

```sh
python3 tests/check_poindexter_package.py
# With the host's poindexter replay command built:
python3 tests/check_poindexter_cli.py
```

The package check compiles an independent On1xfile consumer and compares
the CSV to the frozen v1 objects. It exercises nine rejections (identity
syntax, units, publication, out-of-bounds amounts, unexpected reason)
and a positive difference of `10^12` cents. The CLI check covers both
fixtures under both legacy run formats and the v3 contribution fixture,
checks repeatability and store metadata, and rejects missing, corrupt or
inconsistent runs without a sheet. It uses an isolated
temporary store and honors `FINPRED_EXE`.

Verified with MuLIB `49de89acbc97efbee493d6b28d02c8f64ed4f725`,
On1xfile C11 and GCC 16.2.1 on Linux x86_64. The package test exited 0;
the CLI test exited 0 against the shared host (`v1=2 v2=2 rejected=2`).
The ordinary FinPRED build, fixture oracle, static checks and `tests/run.sh`
also exited 0 with the view integrated.
