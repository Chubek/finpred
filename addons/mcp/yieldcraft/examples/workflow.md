# Synthetic integration workflow

This is an MCP tool-call recipe, not empirical hotel research. Use the exact bytes of FinPRED's tracked fixture files at the supported revision.

1. Upload `fixtures/scenario.csv` using `artifact_upload` (text, including final LF). Save the returned `artifact_sha256` as `SCENARIO`.
2. Upload `fixtures/valuation.csv` as `VALUATION` and `fixtures/demand_contribution.csv` as `DEMAND`. The synthetic demand file references the exact scenario BLAKE3 digest, so do not reserialize either input.
3. Call `yieldcraft_optimize_contribution` with `{"scenario":"SCENARIO","valuation":"VALUATION","demand":"DEMAND"}` after replacing placeholders with actual SHA-256 IDs.
4. The pinned engine's expected recommendation is `19000` EUR cents/night, expected contribution `11550` EUR, `published=false`. This is a fixture expectation, not a result verified by this addon in the delivery environment. Retain the returned native `run_id`; use `yieldcraft_explain`, `yieldcraft_get_evidence`, `yieldcraft_replay` and `yieldcraft_export` with it.
5. Upload `fixtures/offers.csv` as `OFFERS`. Call `yieldcraft_market_positioning` with `scenario`, `valuation`, `offers` and `profile="scenario"`. Expected fixture result: `17100` cents/night. Never combine this competitor evidence with the contribution demand estimate or call it willingness to pay.
6. For daemon testing use operator's offline `plugins/dragnet/examples/Dragnet.json`. Call `dragnet_status`, `dragnet_offline_capture`, then `dragnet_verify_capture` with an eligible cutoff and the capture artifact. Basic extraction does not produce price offers. The fixture is offline, not real-time market information.
7. Call `ottomat_generate` with `profile="scalar-spread"`, or generate a v6 draft using `examples/contribution_graph.json` as the `graph` argument. The optional native bridge must pass its acceptance test before running v6. For the scalar program, use `ottomat_execute_scalar` with `first=17`, `second=42`, `budget=16`.
8. Call `ottomat_highlight` with generated source. An MCP Apps client can show the editor; a text-only client can return source. Standalone `/editor` works independently.
