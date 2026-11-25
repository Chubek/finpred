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
umask 077
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

The server listens only on loopback. `/mcp` uses the official MCP Python SDK's v1 stateless Streamable HTTP with JSON responses; `/editor` serves the standalone highlighter. Hand-written configs require authentication by default; the deployment script defaults to the limited public demo described below. The dependency constraints are in `requirements.in` and `pyproject.toml`; a complete transitive, hash-locked production dependency set still needs to be generated on the target platform. `mcp==1.30.0` retains the v1 API and includes security fixes missing from 1.28.1, including [HTTP client credential forwarding](https://github.com/advisories/GHSA-5h93-6whr-6q8j) and [server-side bearer-token audience handling](https://github.com/advisories/GHSA-w4fh-qvv9-3v23). Review security advisories again before exposing the service.

## Remote deployment

Run `deploy.sh` **on your host PC**, not on the VPS. Fresh installs target Debian/Ubuntu GNU/Linux x86-64 with a supported compiler, Python 3.11+, systemd or SysV init, working DNS, package access and root or passwordless `sudo -n`. Ubuntu 24.04 is the intended first test target. Read `AGENTS.md` before using it on a valuable machine: this delivery has not been run against a real VPS.

```sh
# Generate a distinct UUIDv4 for every new installation. Save the IDs.
ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
SECOND_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')

# Inspect arguments without connecting or generating a credential:
./deploy.sh "$SERVER_IP" --id "$ID" --dry-run

# Quick Tunnel: cloudflared must already be installed from a trusted package source.
./deploy.sh "$SERVER_IP" --id "$ID" --port 8788 --no-auth

# A second instance with bearer authentication and a different backend port:
./deploy.sh "$SERVER_IP" --id "$SECOND_ID" --port 8789 --auth

# Alternative fresh-install proxy options (point DNS at the VPS first):
# -r nginx -d mcp.example.com --email ops@example.com
# -r apache2 -d mcp.example.com --email ops@example.com --sysvinit
# -r caddy -d mcp.example.com

# Optional Telnet transport for fresh installs only, over an independently
# secured loopback tunnel (requires pexpect and telnet locally):
# ./deploy.sh root@127.0.0.1 --id "$ID" --telnet --telnet-port 2323
```

| Option | Meaning |
| --- | --- |
| `--id UUID` | Mandatory lowercase UUIDv4 for a fresh install; selects which instance to manage |
| `-p/--port` | Backend port, default `8788` on install; optional match check for ID-based management |
| `-r/--reverse-proxy` | `cloudflared` (default; also accepts `clouadflared`), `nginx`, `apache2`, `caddy` |
| `-d/--domain` | Domain for TLS proxy/named tunnel |
| `--ssh`, `--telnet` | SSH by default; Telnet requires a separately secured loopback management tunnel. Never sends credentials to a public Telnet host. |
| `--systemd`, `--sysvinit` | Service manager; systemd default |
| `--ssh-port`, `--identity`, `--telnet-port` | Connection parameters |
| `--repo`, `--ref` | HTTPS Git repository ending `.git`, immutable full commit SHA. Defaults to assessed revision (or parent FinPRED checkout's HEAD). Push commits before deploying. |
| `--email` | Required for Nginx/Apache Certbot |
| `--cloudflared-config` | Existing remote named tunnel config and credentials readable only by root and the service account |
| `--no-auth` | Default: public synthetic demo; no token or daemon |
| `--auth` | Require authentication and enable the full tool set |
| `--token-out` | With `--auth` only: private local token path; refuses overwrite |
| `--no-daemon` | With `--auth`: do not autostart the offline Dragnet daemon |
| `--patch --no-auth` | Switch an existing SSH deployment at the selected port to the limited demo |
| `--show-endpoint` | Print the existing HTTPS `/mcp` URL over SSH, without modifying the installation |
| `--configure --id UUID --- TASKS` | Change daemon autostart and/or reverse proxy settings |
| `--uninstall --id UUID` | Stop only that instance and remove its services, proxy route and runtime |
| `--dry-run` | No connection, installation or credential generation |

SSH strict host-key verification is enabled: establish the correct host key before first use. The upload contains only explicitly listed addon source files and, in `--auth` mode, the **hash** of the generated random bearer credential. The remote installer fetches the pinned FinPRED commit and nested gitlinks, builds under the instance's unprivileged service account, then makes the installed executable tree root-owned and read-only to the account. The host PC validates the reported destination against the configured domain or Quick Tunnel hostname pattern, then checks TLS directly and performs MCP initialization and `tools/list` using the selected mode, without following redirects or printing the remote transcript. It prints the final URL only on successful probe. With `--auth`, the initial admin token remains in the local `<prefix>.token` file (0600); prefer `--token-out` with a path outside the checkout and do not share it with ordinary client users.

**Public demo:** Connect to the printed `/mcp` URL without an `Authorization` header. Anyone who can reach that URL can use the demo. It exposes native `yieldcraft_demo` for the checked-in synthetic `contribution`, `market`, and `multiroom` fixtures, plus Ottomat highlighting, preflight, and the built-in strategy list. Pricing runs are not retained. Uploads, saved runs, live acquisition, native strategy execution, and daemon controls are not exposed. Use `--auth` for private data or the full workflow.

For a named tunnel, use `-r cloudflared -d mcp.example.com --cloudflared-config /etc/cloudflared/instance.yml` and provision DNS and a scoped tunnel credential on the VPS. `--dry-run` shows `prefix=...`: an operator can pre-create a dedicated empty group with that name and give root-owned config and credential files mode `0640` with that group. Keep ancestors non-writable by other accounts and traversable by the instance. The installer verifies access as the service account and requires exactly one ingress mapping for the configured hostname to `http://127.0.0.1:<port>`, followed by `http_status:404`. Nginx and Apache proxy the MCP service only over HTTPS.

**Proxy limits:** a Quick Tunnel's `trycloudflare.com` name can change when it restarts, and it supports JSON HTTP but not SSE. Use a named tunnel or your own HTTPS domain for persistent clients. The installer doesn't create Cloudflare accounts, DNS, or credentials. Certbot obtains certificates for Nginx and Apache; Caddy manages HTTPS itself. Multiple instances can share the same direct web server on different hostnames. Nginx, Apache, and Caddy can't all bind the same public ports: before switching proxy types, make sure the new server can bind ports 80/443 without stopping a server another instance or site needs. Don't select a domain already managed outside this script.

Each ID maps to a unique `yc-…` prefix derived from the UUIDv4. Install paths
are `/opt/<prefix>/{finpred,addon,venv}`, `/etc/<prefix>`, `/var/lib/<prefix>`,
and `/var/log/<prefix>`. Service names are `<prefix>-mcp` and (Cloudflare
only) `<prefix>-tunnel`. The VPS serializes deploy/manage operations and
rejects a duplicate ID, reserved backend port, or duplicate managed domain.
To clean up a partial install that reserved the ID, run `--uninstall` for it.

### Manage an existing deployment

```sh
./deploy.sh "$SERVER_IP" --show-endpoint --id "$ID"
./deploy.sh "$SERVER_IP" --configure --id "$SECOND_ID" --- --no-daemon
./deploy.sh "$SERVER_IP" --configure --id "$ID" --- --reverse-proxy caddy --domain mcp.example.com
./deploy.sh "$SERVER_IP" --patch --id "$SECOND_ID" --no-auth
./deploy.sh "$SERVER_IP" --uninstall --id "$ID"
```

These commands use SSH. Pass `USER@HOST` to choose the login explicitly, or
just `HOST` to use SSH's configured user. `--show-endpoint` prints one URL
and does not test reachability or restart anything. It reads the installed
domain or the latest Quick Tunnel hostname reported in recent VPS logs.
On a non-root admin login it uses `sudo -n -u <prefix>` for read
access. `--domain` can assert the hostname for lookup or patch.

`--configure` accepts only `--daemon`, `--no-daemon`, or a proxy selection
with its required flags after `---`; no shell commands. `--daemon` controls
offline Dragnet autostart and requires an authenticated deployment with a
daemon config. Changing a proxy can briefly interrupt the endpoint; for
OAuth deployments, changing the public hostname is refused. The script
tries to restore the previous config and proxy if applying the changes
fails. Use `--show-endpoint` afterward and test the URL with your MCP client;
configure does not use or require a bearer token.

`--patch --no-auth` restarts only `<prefix>-mcp` and switches it to a separate public-demo state
directory; it leaves the installed software, proxy, private projects and
token files untouched. The installed addon must already support demo mode.
The previous config is saved as a root-only
`/etc/<prefix>/config.pre-patch-*.toml` file and restored automatically
if the new service fails its local startup check. If only the external HTTPS
probe fails, the demo stays active and the command reports the probe failure.
To return to private mode, restore the intended backup as
`/etc/<prefix>/config.toml` (owner `root`, group `<prefix>`, mode
`0640` for a standard deployment) on the VPS and restart `<prefix>-mcp`.

`--uninstall` retains the instance's config, credentials, private state,
logs and user account, as well as any certificates, packages and DNS.
The port can be reused, but a retired ID cannot. Older installs without
an ID can still use `--patch` and `--show-endpoint` without `--id`; they
are not automatically migrated or selected by `--configure` or `--uninstall`.

### Troubleshoot a failed SSH deployment

The deploy script reports the failed stage without printing or saving the
SSH transcript. To see SSH's own error without installing anything, test
the connection from your host PC:

```sh
ssh -o StrictHostKeyChecking=yes -p 22 USER@HOST true
```

Use the same host, port and `-i FILE` (if you passed `--identity`) as your
deployment. If the host key is missing or has changed, verify its fingerprint
through a trusted VPS console before updating `known_hosts`. For a non-root
login, the installer runs under `sudo -n`; check that your account is allowed
to do so without prompting.

If SSH connects but the install fails, check the reported stage. The default
`cloudflared` proxy needs `cloudflared` installed on the VPS beforehand. For a
checkout failure, compare `./deploy.sh USER@HOST --id "$ID" --dry-run` (same options) with
the commit available from `--repo`; local-only commits cannot be fetched.
For service failures on systemd, inspect `journalctl -u <prefix>-mcp` on the
VPS (and `journalctl -u <prefix>-tunnel` for Cloudflare). Keep raw logs
private. If the failure left a partial installation, inspect it before
retrying. An `--auth` run may also have already written the local token file;
the script will not overwrite it.

## Client authentication and connection

The endpoint is `https://<domain>/mcp`, not `/sse`. Use a client supporting Streamable HTTP. For a client supporting static authorization headers, configure `Authorization: Bearer <token>` from the local private file. Keep token and client credential files outside the source checkout and never put a bearer token in a URL or query string. For example, an MCP client's server definition may resemble this (exact config varies by client):

```json
{"url":"https://foo.com/mcp","headers":{"Authorization":"Bearer <token>"}}
```

For ChatGPT/Claude remote connectors that require OAuth, configure an **external** standards-compatible authorization server in authenticated mode. The addon implements protected-resource metadata and RFC 7662 access-token introspection, checking active status, issuer, exact resource audience, expiration and subject, then deriving a private project identity from issuer+subject. Its OAuth client secret is read from a private service-readable file. The provider must implement the discovery, registration/client onboarding, consent, PKCE and resource/audience behavior required by the target client. This addon does not issue tokens or implement an authorization server. OAuth/client onboarding has not been tested with ChatGPT or Claude. Do not expose private workflows anonymously to make a connector work. Static credentials are loaded on startup; rotate the file and restart, using distinct projects and scopes for each client. Do not expose the administrative token to autonomous clients unless needed.

## Tools and artifacts

All input files are submitted as `artifact_upload` text or base64 and referred to by their 64-hex **SHA-256 addon IDs**. Clients cannot submit filesystem paths, executable names, environment variables, shell strings, URL network grants or arbitrary CLI flags. The addon stores exact bytes separately from FinPRED's native BLAKE3 evidence and run IDs. SHA-256 IDs are content-integrity references, not signatures. Results above 128 KiB are available in bounded `artifact_read` chunks. For JSON convenience views, integers beyond JavaScript's safe range become decimal strings; exact original bytes are preserved.

| Tool family | Implemented operations |
| --- | --- |
| Artifacts | `artifact_upload`, `artifact_read`, `artifact_list` |
| Dragnet | `dragnet_status`, `dragnet_start`, `dragnet_stop`, `dragnet_restart`, `dragnet_search`, `dragnet_offline_capture`, `dragnet_verify_capture`, `dragnet_collect_offers` |
| Yieldcraft | `yieldcraft_create_scenario`, `yieldcraft_create_valuation`, `yieldcraft_market_positioning`, `yieldcraft_optimize_contribution`, `yieldcraft_estimate_demand`, `yieldcraft_fit_demand_panel`, `yieldcraft_stress_test`, `yieldcraft_coupled_inventory`, `yieldcraft_competitor_cube`, `yieldcraft_predict_price`, `yieldcraft_backtest`, `yieldcraft_compare_strategies`, `yieldcraft_explain`, `yieldcraft_replay`, `yieldcraft_get_evidence`, `yieldcraft_export` |
| Ottomat | `ottomat_list_strategies`, `ottomat_generate`, `ottomat_validate`, `ottomat_highlight`, `ottomat_execute_scalar`, `ottomat_execute`, `ottomat_replay` |

The underlying runner uses fixed argv vectors, bounded output and timeouts, subprocess groups, a sanitized environment and one private workspace per operation. All recommendation tools preserve `published=false`. The core native CLI validates actual financial contracts. A saved addon artifact is not proof of decision eligibility or commercial performance. See `examples/workflow.md` for a complete synthetic fixture workflow.

Scopes: `research:read`, `artifact:write`, `dragnet:search`, `yieldcraft:analyze`, `yieldcraft:recommend`, `ottomat:generate`, `ottomat:simulate`, `daemon:manage`, `admin`. OAuth projects derive from issuer and subject; the resulting project namespace is reserved and cannot be assigned to static bearer tokens. The operator's Dragnet config and daemon belong to the `default` project, and daemon control also requires `daemon:manage`. The daemon stops on failure and does not expose its activity or captures to other projects. Live acquisition is opt-in using config `enable_live`, `allowed_hosts` and `offer_hosts`. LLM text egress additionally requires `allow_llm` and a grant for `api.openai.com`; live GPT is pinned to `https://api.openai.com/v1`. Model credentials are configured by the operator, never a tool request. Basic/GPT page text is untrusted, not a booking quote or a command. Native `dragnet-inspect` validates each full frame before addon storage; incomplete or rejected captures are not committed as successful evidence.

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
- `ui://yieldcraft/ottomat-editor.html`: MCP Apps UI resource linked to generation/highlight tools via `_meta.ui.resourceUri`. A minimal postMessage bridge supports host initialization, tool input/results and server preflight. Only the source-free initialization can use a wildcard target; preflight sends the draft to the connected parent origin you are using. An opaque parent origin cannot connect, so use standalone or text-only mode there. No remote script dependencies, token handling or direct browser fetches. Compatibility with real ChatGPT/Claude MCP Apps hosts remains a test gate.

A custom `ottomat` fenced block cannot change a third-party website's native Markdown grammar. The MCP Apps resource and standalone editor are the portable mechanisms. Text-only clients receive source and structured results. Financial dashboard UI resources beyond the editor are planned; exported CSV can be imported into Poindexter now.

Resources: `ottomat://grammar`, `ottomat://strategies/{profile}`, `yieldcraft://models`, `finpred://documentation`, and the UI resource. Prompts: `analyze_hotel_market`, `generate_ottomat_strategy`, `audit_financial_decision`.

## Security and limitations

This is a development/integration candidate, not an audited multi-tenant service. Use a dedicated VPS/account, authenticated HTTPS, root-owned executable/config trees, restricted SSH, disk quotas and backups. The Python store assumes private cooperating writers; its quota currently covers addon object bytes, not every native store file or transient workspace. Enforce OS-level filesystem/CPU/memory/network limits and rate limits before accepting untrusted workloads. A single service worker is required; do not scale processes over the same mutable daemon/state without a coordination protocol. Native processes run as the same low-privilege service account, not one OS identity per project. No sandbox admission, power-loss durability, provider authenticity, causal inference or profit uplift is claimed. Data retention and GDPR obligations are operator responsibilities.

See `AGENTS.md` for finishing tasks, exact acceptance criteria and the test results. No real VPS, external financial service, real provider acquisition or client account was accessed in producing this addon.

### Local leak regression checks

From this addon directory, after activating the environment with `.[test]`
and building the FinPRED CLI and Dragnet as above, run:

```sh
FINPRED_NATIVE_ROOT="$(git rev-parse --show-toplevel)" python -m pytest -q -rs
node --test tests/editor_bridge.test.cjs
bash -n deploy.sh
bash -n deployment/install.sh
sh -n deployment/sysvinit.in
./deploy.sh root@vps.example --id "$(python3 -c 'import uuid; print(uuid.uuid4())')" --dry-run
```

The local SDK checks exercise authenticated Streamable HTTP in-process
and over a loopback TCP socket, including concurrent calls from different
projects. The native checks use tracked pricing and offline Dragnet
fixtures, including daemon supervision, and verify that another project
cannot read the results or control the daemon. These checks do not qualify public
OAuth onboarding, live acquisition, real MCP Apps hosts, SSH/Telnet,
systemd/SysV, or any proxy's public TLS configuration. The optional native
Ottomat bridge remains unqualified and is not auto-deployed.

This pass was tested from FinPRED `f00169a` on Linux x86-64 with Python
3.14.7, MCP 1.30.0, HTTPX 0.28.1, Pydantic 2.14.4, and Node.js 26.9.0:
77 Python and 3 Node tests passed with no skips, plus shell syntax and SSH
and loopback Telnet dry runs. The parent repository's `./tests/run.sh
storage` also verified historical replays and the golden v2 pricing IDs.
These results do not replace the deployment and independent review gates
in `AGENTS.md`.

## References

- FinPRED assessed revision: https://github.com/Chubek/finpred/tree/957e9671a14460200318e6285728c2f9904efa8c
- MCP Python SDK v1 documentation: https://py.sdk.modelcontextprotocol.io/v1/
- MCP Apps 2026-01-26 specification: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
- Cloudflare Quick Tunnel constraints: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
- OAuth protected resource metadata: https://www.rfc-editor.org/rfc/rfc9728 ; introspection: https://www.rfc-editor.org/rfc/rfc7662
