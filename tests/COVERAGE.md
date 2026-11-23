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
| `source/ottomat/`, `strategies/`: versioned strategy selection | [Parser](check_ottomat_plan.py) checks both header spellings; [profile runs](check_profiles_cli.py) verify all five policies and frozen replay | Invalid source, incompatible graph and mismatched profile parameters |
| `source/sdk/`: static descriptors and compatibility checks | [SDK consumers](check_sdk_packages.py) exercise C11 and On1x against all three packages | Same hosts check incompatible requests; no dynamic invocation claim |
| `plugins/dragnet/`: host-supplied offline CSV | [Compiled source host](check_dragnet_frozen_csv.py) emits five eligible contract rows | Missing descriptor, malformed and stale observations |
| `source/store/`, `source/cli/`: persistence, v1/v2 replay, explain and evidence | [Store](check_store.py), [explain](check_explain_cli.py), [evidence](check_evidence_cli.py) verify frozen inputs and read-only output | [Integration](run.sh) corrupts referenced artifacts; [publication status](check_store_publication_status.py) exercises interrupted writes |
| `plugins/poindexter/`: verified-run worksheet projection | [Package](check_poindexter_package.py) compares a compiled consumer with archived CSV values | [Projection CLI](check_poindexter_cli.py) rejects invalid run evidence |
| `plugins/poindexter/workbench/`: editable worksheet | [Workbench](check_poindexter_workbench.py) tests terminal edit/save and independent run import | Invalid scripts roll back; malformed CSV creates no book |
| `native/store.c`: standalone C candidate | [Contract consumer](../native/tests/store_contract.c) installs/reads objects; [archive copy](../native/tests/run.py) compares v1 bytes | Same consumer checks conflicting content, reader write denial and sync errors |

The fixture integration log includes the actual run, recommendation and trace
digests before comparing them to the pinned values. Neither stores nor build
outputs are cached. Other platforms, power-loss/remount behavior and independent
On1x storage admission are outside this workflow.
