# AGENTS.md — Yieldcraft MCP integration handoff

## Objective and scope

Finish `finpred/addons/mcp/yieldcraft` as a supported, remotely deployable Python MCP service for Dragnet, Yieldcraft and Ottomat. Target the actual checked-out FinPRED revision (this draft was aligned against `957e9671a14460200318e6285728c2f9904efa8c`). Read `README.md`, the parent's `INSTALL.md`, `GUIDE.md`, `strategies/README.md`, `plugins/dragnet/README.md`, `source/ottomat/README.md`, and the integration audit before editing. Reconcile differences if the parent has advanced. Do not replace native financial algorithms with Python substitutes. Preserve existing run IDs, schemas, fixtures, historical replay and dependencies. The user requests recommendations and strategy simulation, never live financial effects.

## Delivered files and honest verification

- Official MCP SDK v1 server registration, scopes, per-project addon/native stores, artifact exchange, resource/prompt endpoints, typed native wrappers, and daemon supervisor.
- `deploy.sh` argument handling, SSH transfer, secured-loopback Telnet transport, root remote installer, systemd/SysV init, four proxy paths, credential generation and external MCP probe.
- Pygments/Highlight.js/TextMate syntax highlighters, standalone browser editor, candidate MCP Apps UI bridge, structured graph generator.
- Optional `native/bridge.on1x` and build script for real v6 lowering, capture and replay with existing handlers. **Not compiled or admitted yet; do not auto-deploy it until conformance passes.**
- Local delivery verification: Python 3.13, Pydantic 2.13.5, httpx 0.28.1, 10 pytest tests passed with mocked native executables and ASGI middleware. Two integration gates were skipped: the MCP SDK test module (SDK unavailable because network/DNS was disabled) and the opt-in native pricing test (compiled FinPRED checkout not available). Shell syntax, dry-run checks, JSON grammar parsing and JavaScript syntax checks passed. No actual FinPRED binaries, real Dragnet acquisition, public OAuth server, ChatGPT/Claude UI host, SSH/Telnet VPS, service manager or reverse proxy was executed. Transitive dependencies are not hash locked. Do not call these gates passed until actually run.

## Six-worker finishing plan

Use six isolated worktrees. Agree on schemas and shared interfaces before coding. Worker 1 integrates. Do not push secrets, modify unrelated FinPRED code or deploy to the supplied example address without explicit authorization. Prefer disposable VMs and offline fixtures. Every worker must provide actual test commands, revision and results; report unsupported environments honestly.

### Worker 1 — integration, packaging, deployment

1. Install the pinned SDK in an isolated environment; generate a reproducible, platform-specific hash-locked dependency set and package the addon. Inspect current SDK security advisories and upgrade if necessary with compatibility tests.
2. Test `deploy.sh` on clean disposable Ubuntu 24.04 and Debian hosts using SSH (root and sudo), systemd and actual SysV init. Verify package prerequisites including compiler, GrammarEmbed, Python version, submodule URLs, root-owned read-only runtime tree, startup and shutdown. Test local/remote privilege boundaries, partial install cleanup and log permissions.
3. Qualify all four proxies including real certificate issuance, preserved authorization, body limits, timeout behavior, DNS and TLS validation, Quick Tunnel URL extraction, and preconfigured named tunnel. Test malformed inputs, existing port/domain conflicts, and invalid certs. Implement transactional install/rollback, safe update/uninstall and health checks without clobbering unrelated configs. Ensure only local final verified `MCP_SERVER_URL` is treated as success. Test Telnet only in a separately encrypted loopback management tunnel. Never auto-accept SSH host keys or store remote passwords.
4. Add addon CI job(s) for unit, real MCP transport, native fixture parity, frontend JS and disposable deployment smoke tests. Verify old FinPRED CI remains unchanged. Produce a release artifact and a real acceptance report.

### Worker 2 — MCP transport, auth, API contracts

1. Run the real SDK test (`pytest -m sdk`) with `mcp==1.28.1` or an explicitly qualified upgrade. Verify FastMCP metadata, schema generation, ASGI lifespan exactly once, and authenticated principal propagation through stateless SDK tasks. Test tools/list, calls, structured errors, resources, prompts, cancellation, concurrency and restart. No auth bypass on missing context.
2. Test actual ChatGPT/Claude connector auth with a separate real OAuth authorization server, including PKCE, discovery, client registration/onboarding, scope consent, audience checks, issuer validation, expiration/revocation and introspection failure. Use stable HTTPS domains. Add separate admin/user tokens, rotation/revocation lifecycle and public rate limiting. Keep private workflows authenticated; `deploy.sh` defaults to a limited anonymous demo that must not expose uploads, stored runs, daemon controls, live acquisition, or arbitrary native inputs.
3. Harden ASGI request/Origin/Host validation, duplicate headers, bounded OAuth calls, request timeouts, project quotas, metrics and sanitized errors. Add strict MCP argument bounds and output schemas, ensure annotations reflect actual persistence/egress. Add project-level jobs/progress/cancel if needed; do not let callers pass arbitrary executable paths, arguments, environment, URLs or capability grants.
4. Review multi-tenant threat model: project dirs are cooperative isolation, not OS sandbox. Either restrict to one trusted operator or implement real isolated workers, filesystem/CPU/disk/network quotas, authenticated audit records and retention/deletion procedures. Keep authorization separate from financial recommendations.

### Worker 3 — Dragnet

1. Verify real `bin/dragnet --daemon --handoff --config ...` and `finpred dragnet-inspect` framing on frozen fixtures. Test fragmented/large/truncated/malformed/empty frames, count/digest mismatch, native rejection, cancellation, daemon death and restart. Confirm relative paths from repo root. Add bounded spool, rate limits, robust cycle status and capture catalogs. Do not restart failed acquisition without explicit policy.
2. Add safe parameterized daemon configuration using immutable versions and administrator review; do not accept arbitrary `fixtures`, `env_file`, credential, endpoint or host grants from model calls. Support owner-aware configuration and restart, list/get/search verified captures without leaking other projects' evidence. Return bounded text views; page/LLM text is untrusted and cannot instruct the service.
3. Complete public-feed tools via current frozen adapter/permission interface; use lawfully retained data, exact source clocks and permission grants. Live search is opt-in only and separately test provider terms, rate limits, SSRF defenses, DNS rebinding, redirects, LLM egress permission and safe secrets. Never promote basic/GPT extraction to offer evidence.

### Worker 4 — Yieldcraft and FinPRED adapters

1. Execute native parity tests using exact tracked fixtures: contribution EUR 190/night and expected EUR 11,550, market positioning EUR 171/night, multiroom EUR 160/night, all unpublished. Verify actual summary formats, evidence IDs, CLI flags, default paths, model limits and replay without current files. Test invalid chronology/currency, stale and absent demand, no eligible offers, infeasible guardrails and exact integers. Do not use default fixture inputs in user recommendations.
2. Finish input schema validation and native return/error parsing. Link randomized demand reports to upstream evidence before marking them eligible; keep observational panels distinct, do not accept invented experiments. Add separate validated inventory/forecast/cube replay tools as supported, safe native adapter for finite stock, typed results and Poindexter CSV export. Provide scenario/valuation schema resources and exact data format guidance.
3. Ensure all native operation inputs/results/build identities are archived using separate versioned addon metadata, not by changing FinPRED historical bytes. Measure process/output timeouts, partial failures and native store quotas. Distinguish modeled stress values from calibrated uncertainty and empirical uplift.

### Worker 5 — Ottomat, Automat, strategy authoring

1. Compile `native/build.py` against the actual pinned MuLIB/On1x, using repo GrammarEmbed flags. Check bridge API names, module resolution, code pin format (BLAKE3 of domain-separated executable SHA-256, not a raw binary signature), native syntax/port rules, archive wire and budgets against exact source. Add real positive and negative tests. Use immutable build manifests with actual compiler and bridge identities, host-supplied code trust; validate all independently expected digest roots. Do not accept graph/handler identity from untrusted callers. Do not claim native validation until compiler passes.
2. Qualify v6 example `examples/contribution_graph.json` and native hospitality fixture, validate all roots and cutoff, compare exact decision outputs against direct native runs, capture output artifacts and replay against independently pinned digest. Add typed result extraction from native archive framing, handler catalog generated from real descriptors, and canonical lowering/graph visualization. Restrict to pure registered handlers; reject unknown imports, incompatible port types, capability/effect escalation, cycle, budget excess, drift and tampered archive. Keep bridge optional until verified.
3. Support authoritative validation for dialects 1–5 using real legacy/scalar lowerers, not textual matching. Expand generation by composing registered v6 handlers only. New financial algorithms must be implemented and reviewed natively before they become callable. Provide safe formatting without altering archived bytes, versioned strategy registry and typed resources. No dynamic Python execution or shell eval of generated strategies.

### Worker 6 — syntax highlighting, MCP Apps and workbench

1. Test Pygments, Highlight.js and TextMate grammars on all six dialects, preserve exact source bytes, highlight malformed syntax and show native line/column diagnostics. Package a VS Code grammar extension if desired; do not imply third-party native fenced-code registration is controlled by MCP.
2. Validate `ui://yieldcraft/ottomat-editor.html` with the real MCP Apps extension in supported ChatGPT/Claude hosts. Prefer the official pinned/bundled MCP Apps JS SDK for lifecycle, secure messaging, size negotiation, cancellation and accessibility. The provided minimal bridge is a candidate, not certified. Keep standalone mode and text-only structured fallback. Do not insert untrusted HTML or expose bearer tokens to the iframe.
3. Implement pricing, demand, forecast, inventory and evidence visualizations as MCP Apps resources, using structured typed results, decimal-safe financial values, units, labels, uncertainty provenance and replay status. Add graph visualization, explicit simulation action and diagnostics; never silently publish prices. Connect verified Poindexter exports, but distinguish editable copies from verified archives.

## Acceptance gates (all must be explicitly reported)

- Core tests, actual SDK tests and native fixture tests pass; no skipped required gates hidden as success. Verify native bridge compiled or leave capability unavailable. Preserve old FinPRED golden archive IDs, fixtures and CI.
- Disposable SSH deploy and each supported proxy passes TLS + authenticated MCP initialize/tools/list/tool call; actual SysV/systemd and secured-loopback Telnet tested or explicitly marked unsupported. Repeated deploy safely refuses or performs reviewed upgrade. No credentials in logs or output. Verify service startup, daemon supervision, shutdown, and failure recovery.
- OAuth onboarding with at least one intended client works without exposing private MCP workflows anonymously. Cross-project read and daemon controls denied. Input/output/time limits and hostile requests fail closed. Independent threat review before public production use.
- Real native Yieldcraft results and replay match fixture expectations; no arbitrary program execution, live financial action or misleading empirical claims. Live data/network/LLM egress requires explicit operator grants. Do not certify untested commercial performance.
- Real MCP Apps host/editor handshake or clearly documented text-only fallback. All source rendering is escaped and native validation status accurate.
- Document verified platform/dependency versions, reproducible install, credentials, operations, update/rollback, remaining risks and exact test evidence. Commit only reviewed source/test/docs, not environment, credential, generated build or captured private customer/provider data.

## Quick local checks

```sh
python3 -m pip install -e '.[test]'
python3 -m pytest -q
bash -n deploy.sh deployment/install.sh
sh -n deployment/sysvinit.in
./deploy.sh root@204.168.206.175 --dry-run
```

Use `README.md` for real native build commands. `examples/workflow.md` and `examples/contribution_graph.json` are starting acceptance fixtures, not evidence of a completed deployment. The server is a candidate until these gates are met.
