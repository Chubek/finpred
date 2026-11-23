# Local release verification (Linux x86-64)

The [CI workflow](../.github/workflows/verify.yml) builds `on1xc` from the
[release pins](../INSTALL.md#2-pin-mulib-and-libstone). `tests/run.sh` uses the
compiled CLI and disposable stores. `check_fixtures.py` and `validate_static.py`
are supplementary checks; neither executes On1x.

| Source / feature | Positive execution | Rejection or failure execution |
| --- | --- | --- |
| `source/core/`: CSV, contracts, as-of times, units and serialization | [Integration](run.sh) validates emitted JSON against schemas and the normalized input oracle | [Ingestion](check_ingestion_cli.py) feeds invalid records to the CLI |
| `plugins/yieldcraft/`, `source/algorithms/`: exact room bundles, quantiles, guardrails | [Pricing](check_pricing_cli.py) and [package consumer](check_yieldcraft_package.py) check nightly amounts and archived envelopes | Same tests reject infeasible samples, conflicting guardrails or forbidden modes |
| `source/automat/`: fixed graph and limits | [Fixed runner](check_fixed_runner.py) runs `premium-p75` through a separately built host | Same host refuses changed effects, edges and gate order |
| `source/automat/dag.on1x`: native scalar analysis DAG | [Independent consumer](check_dag.py) checks fork/join, tie-breaking, repeat trace and a single-node plan | Rejects cycle, incompatible edge, missing port, duplicate ID, unknown handler, budget overflow and execution mode |
| `source/automat/dag_replay.on1x`: scalar evidence | [Compiled replay consumer](check_dag_replay.py) checks ordered artifact bytes, BLAKE3 identities and output selection | Rejects altered or incomplete evidence on recomputation |
| `source/automat/scalar_{manifest,decode,verify}.on1x`: frozen scalar runs | [Manifest consumer](check_scalar_manifest.py) reconstructs a run from frozen bytes in a fresh process | Refuses mismatched identities, noncanonical manifests and altered artifacts |
| `source/automat/scalar_memo.on1x`, `dag.on1x`: run-local node reuse | [Memo consumer](check_scalar_memo.py) compares handler counts and evidence for cached and uncached execution | Distinct handler or ordered parent identities miss; hits cannot bypass plan limits |
| Scalar source language features | [On1x feature fixture](check_on1x_features.py) checks exact interpolation bytes and `Some(0)` vs `None` | Compiler rejects unbound interpolation and non-exhaustive matching |
| `source/ottomat/`, `strategies/`: versioned strategy selection | [Parser](check_ottomat_plan.py) checks both header spellings; [profile runs](check_profiles_cli.py) verify all five policies and frozen replay | Invalid source, incompatible graph and mismatched profile parameters |
| `source/ottomat/scalar*.on1x`: native scalar DSL | [V3 consumer](check_ottomat_scalar.py) compares native and DSL execution and evidence | Rejects invalid syntax, unknown and undeclared imports, incompatible edges, cycles, effects and over-budget plans |
| `automat.scalar-dag@2`, `scalar-run@2`, Ottomat v4: pure conditional selection | [Selection consumer](check_scalar_selection.py) checks both branch outcomes, native/DSL parity and frozen replay | Rejects wrong port kinds and arity, cross-version declarations and altered lineage |
| `plugins/scalar_diagnostics/`, native scalar registry and Ottomat v5 | [Registry consumer](check_scalar_registry.py) checks linked dispatch and exact owner/handler lineage; [standalone package](check_scalar_diagnostics_package.py) tests direct midpoint calls | Rejects unavailable imports, forged owners and out-of-range direct arguments |
| `source/sdk/`: static descriptors and compatibility checks | [SDK consumers](check_sdk_packages.py) exercise C11 and On1x against all three packages | Same hosts check incompatible requests; no dynamic invocation claim |
| `source/sdk/registry.on1x`: engine dispatch allowlist | [Registry test](check_plugin_registry.py) exercises registered call sites | Disables four compiled entries, rejects an unregistered manifest and checks direct-use separation |
| `plugins/dragnet/`: host-supplied offline CSV | [Compiled source host](check_dragnet_frozen_csv.py) emits five eligible contract rows | Missing descriptor, malformed and stale observations |
| `plugins/dragnet/`: offline Elvi Crossref evidence | [Elvi and On1x hosts](check_dragnet_elvi.py) render keyword URLs and replay selected fields from saved responses | Reject mismatched digests, unrelated work, unsupported fields and late captures |
| `plugins/dragnet/crossref`: raw-snapshot replay | [Replay command test](check_crossref_replay.py) regenerates decoder handoffs and verifies exact evidence bytes | Rejects changed input or reference bytes, oversized inputs and nonregular files |
| `source/store/`, `source/cli/`: persistence, v1/v2 replay, explain and evidence | [Store](check_store.py), [explain](check_explain_cli.py), [evidence](check_evidence_cli.py) verify frozen inputs and read-only output | [Integration](run.sh) corrupts referenced artifacts; [publication status](check_store_publication_status.py) exercises interrupted writes |
| `source/cli/run_formats.on1x`: current Yieldcraft v2 and archived v1 | [Format boundary](check_yieldcraft_formats.py) checks v2 publication and read-only archive access | Refuses unknown run formats without changing the store |
| `plugins/poindexter/`: verified-run worksheet projection | [Package](check_poindexter_package.py) compares a compiled consumer with archived CSV values | [Projection CLI](check_poindexter_cli.py) rejects invalid run evidence |
| `plugins/poindexter/workbench/`: editable worksheet | [Workbench](check_poindexter_workbench.py) tests terminal edit/save and independent run import | Invalid scripts roll back; malformed CSV creates no book |
| Poindexter MuLIB-backed terminal title | [Terminal conformance](check_poindexter_tty.py) checks the real PTY and unchanged GUI frame | `NO_COLOR` and redirected output contain no styling escapes; [admission probe](check_tui_kernel_admission.py) checks unavailable direct imports |
| `plugins/poindexter/workbench/native/`: isolated MuLIB TUI viewport | [C11 tests](../plugins/poindexter/workbench/native/test_viewport.c) verify clipping, changed cells and no-change rendering | Rejects invalid dimensions, text and output buffers; does not certify KernelBind admission |
| `plugins/poindexter/gui/`: optional ImmGTK local workbook frontend | [GUI conformance](check_poindexter_gui.py) uses the real On1x worksheet worker with a software frame and optional private X11 display | Rejects invalid edits and nonregular or malformed books; no implicit save |
| `native/store.c`: standalone C candidate | [Contract consumer](../native/tests/store_contract.c) installs/reads objects; [archive copy](../native/tests/run.py) compares v1 bytes | Same consumer checks conflicting content, reader write denial and sync errors |

The fixture integration log includes the actual run, recommendation and trace
digests before comparing them to the pinned values. Neither stores nor build
outputs are cached. Other platforms, power-loss/remount behavior and independent
On1x storage admission are outside this workflow.
