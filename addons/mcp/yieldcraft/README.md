# Yieldcraft MCP

**Version 0.1.0 — integration candidate**  
Target FinPRED revision: `957e9671a14460200318e6285728c2f9904efa8c` (or a compatible later revision).

A Python Model Context Protocol server for FinPRED's hospitality pricing and research workflows. FinPRED remains the authority for mathematical computation, data contracts, evidence and replay. The addon is **analysis/recommendation only**: no booking, trading, posting prices, arbitrary shell execution, or third-party mutation is exposed.

## Quick start: on the development machine

Copy `finpred/addons/mcp/yieldcraft/` from the archive into the actual FinPRED checkout, without replacing other project files. The ZIP does not contain the FinPRED engine or its dependencies.

From the FinPRED root on Linux x86-64:

```sh
git submodule update --init third_party/mulib
git -C third_party/mulib submodule update --init on1x/third_party/libstone
make mulib && make && make dragnet
bin/yieldcraft-demand build
bin/yieldcraft-inventory build
cd addons/mcp/yieldcraft
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
mkdir -m 700 -p "$HOME/.yieldcraft-mcp/projects"
.venv/bin/python deployment/token.py \
  --cleartext "$HOME/.yieldcraft-mcp/token" \
  --records "$HOME/.yieldcraft-mcp/tokens.json" --admin
cp config.example.toml "$HOME/.yieldcraft-mcp/config.toml"
```

Edit that TOML: point `finpred_root` to your absolute checkout, `state_dir` to the private projects folder, and `token_file` to the generated records file. Optionally set `daemon_config` to the absolute path of `plugins/dragnet/examples/Dragnet.json` and `daemon_autostart=true`. Dragnet's relative fixture paths resolve from the **FinPRED root**, not the config file's directory. Leave live access disabled unless you have independently approved provider terms and host grants. The supplied example is synthetic/offline and has an old fixed cutoff; it is not live market evidence.

```sh
.venv/bin/python -m yieldcraft_mcp --config "$HOME/.yieldcraft-mcp/config.toml"
# In a separate terminal:
curl -fsS http://127.0.0.1:8788/healthz
.venv/bin/python -m pytest -q
```

The server listens only on loopback. `/mcp` uses the official MCP Python SDK's v1 stateless Streamable HTTP with JSON responses; `/editor` serves the standalone highlighter. There is no unauthenticated MCP endpoint. The dependency constraints are in `requirements.in` and `pyproject.toml`; a complete transitive, hash-locked production dependency set still needs to be generated on the target platform. `mcp==1.28.1` is the deliberately selected v1 API, not a claim to be the latest SDK. Review its security advisories before exposure and upgrade with conformance tests.

## Remote deployment

Run `deploy.sh` **on your host PC**, not on the VPS. This is a fresh-install script targeting Debian/Ubuntu GNU/Linux x86-64 with a supported compiler, Python 3.11+, systemd or SysV init, working DNS, package access and root or passwordless `sudo -n`. Ubuntu 24.04 is the intended first test target. Read `AGENTS.md` before using it on a valuable machine: this delivery has not been run against a real VPS.

```sh
# Inspect arguments without connecting or generating a credential:
./deploy.sh root@204.168.206.175 --dry-run

# Quick Tunnel: cloudflared must already be installed from a trusted package source.
./deploy.sh root@204.168.206.175 -p 8788 -r cloudflared --ssh --systemd

# Custom DNS (point the domain to the VPS first; ports 80/443 must be reachable):
./deploy.sh root@204.168.206.175 -r nginx -d foo.com --email ops@foo.com
./deploy.sh root@204.168.206.175 -r apache2 -d foo.com --email ops@foo.com --sysvinit
./deploy.sh root@204.168.206.175 -r caddy -d foo.com

# Named Cloudflare tunnel: provision ingress/DNS and a scoped credential on the VPS.
./deploy.sh root@204.168.206.175 -r cloudflared -d foo.com \
  --cloudflared-config /etc/cloudflared/yieldcraft.yml

# Telnet via an independently secured management tunnel (requires pexpect + telnet locally):
./deploy.sh root@127.0.0.1 --telnet --telnet-port 2323 -r cloudflared
```

| Option | Meaning |
| --- | --- |
| `-p/--port` | Backend port, default `8788` |
| `-r/--reverse-proxy` | `cloudflared` (default; also accepts `clouadflared`), `nginx`, `apache2`, `caddy` |
| `-d/--domain` | Domain for TLS proxy/named tunnel |
| `--ssh`, `--telnet` | SSH by default; Telnet requires a separately secured loopback management tunnel. Never sends credentials to a public Telnet host. |
| `--systemd`, `--sysvinit` | Service manager; systemd default |
| `--ssh-port`, `--identity`, `--telnet-port` | Connection parameters |
| `--repo`, `--ref` | HTTPS Git repository ending `.git`, immutable full commit SHA. Defaults to assessed revision (or parent FinPRED checkout's HEAD). Push commits before deploying. |
| `--email` | Required for Nginx/Apache Certbot |
| `--cloudflared-config` | Existing remote named tunnel config, readable by service account |
| `--token-out` | Private cleartext bearer credential path on deploying PC; refuses overwrite |
| `--no-daemon` | Do not autostart offline demo daemon |
| `--dry-run` | No connection, installation or credential generation |

SSH strict host-key verification is enabled: establish the correct host key before first use. The script sends the addon and **only the hash** of the generated random bearer credential. The remote installer fetches the pinned FinPRED commit and nested gitlinks, builds under the unprivileged service account, then makes the installed executable tree root-owned and read-only to the account. It installs a venv, starts the foreground MCP service, configures the selected reverse proxy and prints a remote candidate URL. The host PC then checks TLS and performs a real MCP initialization and `tools/list`; the final URL is printed only on successful probe. The initial admin token remains in the local `yieldcraft-mcp.token` file (0600); do not share it with ordinary client users.

**Quick Tunnel limitations:** the assigned `trycloudflare.com` hostname is temporary and may change when cloudflared restarts; it supports JSON HTTP but not SSE. Use a named tunnel or your own HTTPS domain for persistent clients. This installer deliberately does not install Cloudflare binaries from unverified downloads or create Cloudflare accounts/DNS/credentials. For named ingress, use `http://127.0.0.1:8788` (or your selected port) and a catch-all `http_status:404`. The authenticated public probe must succeed. For Nginx/Apache, Certbot obtains and renews certificates; Caddy manages HTTPS itself. The script assumes no conflicting sites already serve the chosen domain; agents must qualify that and improve rollback. A failed fresh install can leave diagnostic files, a partially configured proxy or services. It does not overwrite an existing addon deployment. Inspect and clean up manually before retrying; there is no automated update/rollback in this version.

Locations: `/opt/yieldcraft-mcp/{finpred,addon,venv}`, `/etc/yieldcraft-mcp`, `/var/lib/yieldcraft-mcp/projects`, `/var/log/yieldcraft-mcp`. Service names `yieldcraft-mcp` and (cloudflared only) `yieldcraft-tunnel`.

## Client authentication and connection

The endpoint is `https://<domain>/mcp`, not `/sse`. Use a client supporting Streamable HTTP. For a client supporting static authorization headers, configure `Authorization: Bearer <token>` from the local private file. For example, an MCP client's server definition may resemble this (exact config varies by client):

```json
{"url":"https://foo.com/mcp","headers":{"Authorization":"Bearer <token>"}}
```

For ChatGPT/Claude remote connectors that require OAuth, configure an **external** standards-compatible authorization server. The addon implements protected-resource metadata and RFC 7662 access-token introspection, checking active status, issuer, exact resource audience, expiration and subject, then deriving a private project identity from issuer+subject. Its OAuth client secret is read from a private service-readable file. The provider must implement the discovery, registration/client onboarding, consent, PKCE and resource/audience behavior required by the target client. This addon does not issue tokens or implement an authorization server. OAuth/client onboarding has not been tested with ChatGPT or Claude. Do not expose the server anonymously to make a connector work. Static credentials are loaded on startup; rotate the file and restart, using distinct projects and scopes for each client. Do not expose the administrative token to autonomous clients unless needed.

## Tools and artifacts

All input files are submitted as `artifact_upload` text or base64 and referred to by their 64-hex **SHA-256 addon IDs**. Clients cannot submit filesystem paths, executable names, environment variables, shell strings, URL network grants or arbitrary CLI flags. The addon stores exact bytes separately from FinPRED's native BLAKE3 evidence and run IDs. SHA-256 IDs are content-integrity references, not signatures. Results above 128 KiB are available in bounded `artifact_read` chunks. For JSON convenience views, integers beyond JavaScript's safe range become decimal strings; exact original bytes are preserved.

| Tool family | Implemented operations |
| --- | --- |
| Artifacts | `artifact_upload`, `artifact_read`, `artifact_list` |
| Dragnet | `dragnet_status`, `dragnet_start`, `dragnet_stop`, `dragnet_restart`, `dragnet_search`, `dragnet_offline_capture`, `dragnet_verify_capture`, `dragnet_collect_offers` |
| Yieldcraft | `yieldcraft_create_scenario`, `yieldcraft_create_valuation`, `yieldcraft_market_positioning`, `yieldcraft_optimize_contribution`, `yieldcraft_estimate_demand`, `yieldcraft_fit_demand_panel`, `yieldcraft_stress_test`, `yieldcraft_coupled_inventory`, `yieldcraft_competitor_cube`, `yieldcraft_predict_price`, `yieldcraft_backtest`, `yieldcraft_compare_strategies`, `yieldcraft_explain`, `yieldcraft_replay`, `yieldcraft_get_evidence`, `yieldcraft_export` |
| Ottomat | `ottomat_list_strategies`, `ottomat_generate`, `ottomat_validate`, `ottomat_highlight`, `ottomat_execute_scalar`, `ottomat_execute`, `ottomat_replay` |

The underlying runner uses fixed argv vectors, bounded output and timeouts, subprocess groups, a sanitized environment and one private workspace per operation. All recommendation tools preserve `published=false`. The core native CLI validates actual financial contracts. A saved addon artifact is not proof of decision eligibility or commercial performance. See `examples/workflow.md` for a complete synthetic fixture workflow.

Scopes: `research:read`, `artifact:write`, `dragnet:search`, `yieldcraft:analyze`, `yieldcraft:recommend`, `ottomat:generate`, `ottomat:simulate`, `daemon:manage`, `admin`. Administrative daemon control requires `daemon:manage`. OAuth projects derive from subject; bearer tokens have an explicit project. The daemon is single-owner, foreground-managed, and stops on failure; the default auto-start owner is `default`. Captures from another project are not exposed. Live acquisition is opt-in using config `enable_live`, `allowed_hosts` and `offer_hosts`. LLM text egress additionally requires `allow_llm` and the approved endpoint; model credentials are configured by the operator, never a tool request. Basic/GPT page text is untrusted, not a booking quote or a command. Native `dragnet-inspect` validates each full frame before addon storage; incomplete or rejected captures are not committed as successful evidence.

## Ottomat authoring and the native bridge

Known built-in market/contribution profiles and scalar programs are read byte-for-byte from the checkout. `ottomat_generate` can also generate pure v6 declarations from a bounded graph specification: named inputs, versioned handlers, bindings, typed outputs and emits. Python checks token syntax, duplicate names, references and cycles, but **does not replace native lowering**. A generated draft is not executable until the optional On1x bridge is built and accepts it.

The bridge source is provided in `native/bridge.on1x`, with `native/build.py` using FinPRED's existing GrammarEmbed test build flags. It is not installed automatically because this environment cannot compile On1x; agents must build and verify it first:

```sh
# From the actual FinPRED root, after the native compiler/CLI build:
python3 addons/mcp/yieldcraft/native/build.py "$PWD"
```

It is intended to use the existing trusted hospitality graph handlers and contribution adapter, perform v6 lowering, capture/replay native archives and pin bridge/compiler identities. No user-provided On1x code, dynamic plugin loading, filesystem or network effect handlers. `ottomat_execute` and `ottomat_replay` reject if the optional bridge is absent. Until the native acceptance gate passes, use known profiles and scalar tools. `ottomat_validate` otherwise returns a clearly labeled preflight/draft status. The archive digest must be pinned independently for replay; the bridge manifest is not a signed attestation. The addon limits output/archives to its configured byte ceiling (default 2 MB, maximum 26 MB); oversized reports are rejected rather than silently truncated.

## Syntax highlighting and interface

- `yieldcraft_mcp/highlight.py`: Pygments lexer installed with the package.
- `highlighting/ottomat.js`: Highlight.js grammar registration module.
- `highlighting/ottomat.tmLanguage.json`: TextMate grammar for compatible editor extensions.
- `/editor`: standalone browser editor, line numbers, light/dark colors, copy and save source.
- `ui://yieldcraft/ottomat-editor.html`: MCP Apps UI resource linked to generation/highlight tools via `_meta.ui.resourceUri`. A minimal postMessage bridge supports host initialization, tool input/results and server preflight. No remote script dependencies, token handling or direct browser fetches. Compatibility with real ChatGPT/Claude MCP Apps hosts remains a test gate.

A custom `ottomat` fenced block cannot change a third-party website's native Markdown grammar. The MCP Apps resource and standalone editor are the portable mechanisms. Text-only clients receive source and structured results. Financial dashboard UI resources beyond the editor are planned; exported CSV can be imported into Poindexter now.

Resources: `ottomat://grammar`, `ottomat://strategies/{profile}`, `yieldcraft://models`, `finpred://documentation`, and the UI resource. Prompts: `analyze_hotel_market`, `generate_ottomat_strategy`, `audit_financial_decision`.

## Security and limitations

This is a development/integration candidate, not an audited multi-tenant service. Use a dedicated VPS/account, authenticated HTTPS, root-owned executable/config trees, restricted SSH, disk quotas and backups. The Python store assumes private cooperating writers; its quota currently covers addon object bytes, not every native store file or transient workspace. Enforce OS-level filesystem/CPU/memory/network limits and rate limits before accepting untrusted workloads. A single service worker is required; do not scale processes over the same mutable daemon/state without a coordination protocol. Native processes run as the same low-privilege service account, not one OS identity per project. No sandbox admission, power-loss durability, provider authenticity, causal inference or profit uplift is claimed. Data retention and GDPR obligations are operator responsibilities.

See `AGENTS.md` for finishing tasks, exact acceptance criteria and the test results. No real VPS, external financial service, real provider acquisition or client account was accessed in producing this addon.

## References

- FinPRED assessed revision: https://github.com/Chubek/finpred/tree/957e9671a14460200318e6285728c2f9904efa8c
- MCP Python SDK v1 documentation: https://py.sdk.modelcontextprotocol.io/v1/
- MCP Apps 2026-01-26 specification: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
- Cloudflare Quick Tunnel constraints: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
- OAuth protected resource metadata: https://www.rfc-editor.org/rfc/rfc9728 ; introspection: https://www.rfc-editor.org/rfc/rfc7662
