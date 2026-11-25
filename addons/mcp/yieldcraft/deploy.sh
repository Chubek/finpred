#!/usr/bin/env bash
# Run from a host PC. No remote command is executed in --dry-run.
set +x
set -Eeuo pipefail
umask 077
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
usage(){ cat <<'HELP'
Usage: deploy.sh USER@HOST [-p|--port 8788] [-r|--reverse-proxy cloudflared|nginx|apache2|caddy]
  [-d|--domain foo.com] [--ssh|--telnet] [--systemd|--sysvinit]
  [--ssh-port 22] [--identity FILE] [--telnet-port 23]
  [--repo https://github.com/Chubek/finpred.git] [--ref FULL_COMMIT_SHA]
  [--email ADDRESS] [--cloudflared-config /remote/path.yml]
  [--no-auth|--auth] [--token-out FILE] [--no-daemon] [--dry-run]
Deploy a fresh Debian/Ubuntu Linux x86-64 service. SSH is the default.
Telnet is supported only through a separately secured loopback management tunnel.
Nginx/Apache2 require a domain pointing at the VPS and --email for Certbot.
Cloudflared without a domain uses a temporary Quick Tunnel (JSON HTTP, not SSE).
For a named tunnel, provision DNS and credentials on the VPS and pass its config.
Its private files can use mode 0640 with a dedicated, empty yieldcraft-mcp group.
Default: --no-auth serves a public synthetic demo without stored runs or live access.
Use --auth for the full service. It generates a local bearer credential and uploads only its hash.
The script refuses to overwrite an existing deployment or token file.
HELP
}
die(){ echo "deploy: $*" >&2; exit 2; }
[[ $# -gt 0 ]] || { usage; exit 2; }; [[ $1 != -h && $1 != --help ]] || { usage; exit 0; }
target=$1; shift
port=8788 proxy=cloudflared domain='' protocol=ssh init=systemd ssh_port=22 telnet_port=23 identity='' email='' cf_config='' repo=https://github.com/Chubek/finpred.git ref=957e9671a14460200318e6285728c2f9904efa8c dry=0 daemon=1 auth=0 token_out_set=0 token_out="$PWD/yieldcraft-mcp.token"
# Prefer the checked-out parent repository if this addon is inside it.
if top=$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null) && [[ -f "$top/bin/finpred" ]]; then ref=$(git -C "$top" rev-parse HEAD); fi
while (($#)); do
 case "$1" in
 -p|--port|-r|--reverse-proxy|-d|--domain|--ssh-port|--telnet-port|--identity|--repo|--ref|--email|--cloudflared-config|--token-out)
  [[ $# -ge 2 && -n $2 ]] || die "$1 requires a value"; key=$1; val=$2; shift 2
   case "$key" in -p|--port) port=$val;; -r|--reverse-proxy) proxy=$val;; -d|--domain) domain=$val;; --ssh-port) ssh_port=$val;; --telnet-port) telnet_port=$val;; --identity) identity=$val;; --repo) repo=$val;; --ref) ref=$val;; --email) email=$val;; --cloudflared-config) cf_config=$val;; --token-out) token_out=$val; token_out_set=1;; esac;;
  --auth) auth=1; shift;; --no-auth) auth=0; shift;;
 --ssh|--telnet) protocol=${1#--}; shift;; --systemd|--sysvinit) init=${1#--}; shift;; --no-daemon) daemon=0; shift;; --dry-run) dry=1; shift;; -h|--help) usage; exit 0;; *) die "unknown argument: $1";; esac
done
[[ $target =~ ^[a-zA-Z_][a-zA-Z0-9_-]{0,31}@[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$ ]] || die 'expected USER@HOST (IPv4/DNS)'
for v in "$port" "$ssh_port" "$telnet_port"; do [[ $v =~ ^[1-9][0-9]{0,4}$ && $v -le 65535 ]] || die 'invalid port'; done
[[ $proxy != clouadflared ]] || proxy=cloudflared
case $proxy in cloudflared|nginx|apache2|caddy) ;; *) die 'unknown reverse proxy';; esac
[[ $ref =~ ^[0-9a-f]{40}$ ]] || die 'use an immutable full Git commit SHA'
[[ $repo =~ ^https://[a-zA-Z0-9.-]+/[a-zA-Z0-9_./-]+\.git$ && $repo != *..* ]] || die 'expected HTTPS Git URL ending in .git'
if [[ -n $domain ]]; then [[ ${#domain} -le 253 && $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || die 'invalid DNS domain'; fi
if [[ $proxy != cloudflared ]]; then [[ -n $domain ]] || die 'domain required'; fi
if [[ $proxy == nginx || $proxy == apache2 ]]; then [[ $email =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || die 'valid --email required for Certbot'; fi
if [[ $proxy == cloudflared && -n $domain ]]; then [[ $cf_config =~ ^/[a-zA-Z0-9_./-]+$ && $cf_config != *..* ]] || die 'named tunnel needs --cloudflared-config remote path'; else [[ -z $cf_config ]] || die 'cloudflared config is for a named tunnel only'; fi
if [[ $protocol == telnet ]]; then [[ ${target#*@} == 127.0.0.1 || ${target#*@} == localhost ]] || die 'Telnet requires a separately secured loopback tunnel; use SSH for public VPS'; fi
if ((auth)); then
 [[ $token_out != *[[:cntrl:]]* ]] || die 'token output path must not contain control characters'
else
 (( ! token_out_set )) || die '--token-out requires --auth'
 daemon=0
fi
if ((dry)); then printf 'target=%s protocol=%s init=%s port=%s proxy=%s domain=%s ref=%s daemon=%s auth=%s\n' "$target" "$protocol" "$init" "$port" "$proxy" "${domain:-dynamic}" "$ref" "$daemon" "$auth"; exit 0; fi
if [[ $protocol == ssh ]]; then command -v ssh >/dev/null || die 'OpenSSH client required on host PC'; fi
if ((auth)); then
 [[ ! -e $token_out && ! -L $token_out ]] || die 'token output already exists'
else
 printf '%s\n' 'deploy: public demo mode; anyone with access to the URL can call the demo tools. Use --auth for private workloads.' >&2
fi
command -v python3 >/dev/null || die 'python3 required on host PC'
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
# Package only known source files, not the checkout, ignored files or operator data.
payload_files=(
 pyproject.toml deployment/install.sh deployment/sysvinit.in deployment/tunnel_config.py
 highlighting/ottomat.js highlighting/ottomat.tmLanguage.json
 native/bridge.on1x native/build.py
 yieldcraft_mcp/{__init__,__main__,artifacts,auth,config,dragnet,engine,highlight,models,ottomat,processes,server}.py
 yieldcraft_mcp/ui/editor.html
)
for dir in deployment highlighting native yieldcraft_mcp yieldcraft_mcp/ui; do
 [[ -d $HERE/$dir && ! -L $HERE/$dir ]] || die 'deployment source directories must not be symlinks'
done
for file in "${payload_files[@]}"; do
 [[ -f $HERE/$file && ! -L $HERE/$file ]] || die "missing or non-regular deployment source: $file"
 mkdir -p "$stage/addon/$(dirname -- "$file")"
 install -m 0600 -- "$HERE/$file" "$stage/addon/$file"
done
payload_entries=(addon)
probe_args=()
if ((auth)); then
 python3 "$HERE/deployment/token.py" --cleartext "$token_out" --records "$stage/tokens.json" --admin
 payload_entries+=(tokens.json)
 probe_args+=("$token_out")
fi
# No plaintext token in archive, SSH commands, or logs.
tar -C "$stage" -czf "$stage/payload.tar.gz" "${payload_entries[@]}"
args=("$port" "$proxy" "${domain:--}" "$init" "$repo" "$ref" "${email:--}" "${cf_config:--}" "$daemon" "$auth")
if [[ $protocol == ssh ]]; then
 sshargs=(-T -p "$ssh_port" -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ForwardAgent=no -o ClearAllForwardings=yes); [[ -z $identity ]] || sshargs+=(-i "$identity")
 remote='set +x; set -eu; umask 077; t=$(mktemp -d) || exit 40; trap '\''rm -rf -- "$t"'\'' 0; trap '\''exit 40'\'' HUP INT TERM; tar --no-same-owner --no-same-permissions -xzf - -C "$t" || exit 40; if [ "$(id -u)" = 0 ]; then set --; else set -- sudo -n; fi; "$@" bash "$t/addon/deployment/install.sh" "$t"'
 for a in "${args[@]}"; do remote+=" '$a'"; done
 # Only the installer's reserved stage statuses pass through. OpenSSH uses 255.
 remote+=' || { rc=$?; case "$rc" in 4[2-9]|5[0-2]) exit "$rc";; *) exit 41;; esac; }'
 # The remote side may echo sensitive diagnostics. Never print or save its transcript.
 url=$(
  ssh "${sshargs[@]}" "$target" "$remote" < "$stage/payload.tar.gz" 2>/dev/null |
   PYTHONIOENCODING=utf-8:replace python3 "$HERE/deployment/probe.py" --candidate "${domain:--}" 2>/dev/null
  statuses=("${PIPESTATUS[@]}")
  if ((statuses[0])); then exit "${statuses[0]}"; fi
  if ((statuses[1])); then exit 53; fi
 ) || {
  case $? in
   255) die 'SSH transport failed; check the host, SSH port, known host key and login credentials' ;;
   40) die 'SSH connected, but VPS staging or archive extraction failed; check tar and temporary disk space' ;;
   41) die 'could not run the VPS installer; check Bash and, for a non-root SSH user, passwordless sudo -n' ;;
   42) die 'VPS preflight failed; check Debian/Ubuntu x86-64, the selected init system, backend port and any named tunnel config' ;;
   43) die 'existing Yieldcraft installation or service definitions on the VPS; inspect for a partial install before retrying' ;;
   44) die 'cloudflared is not available on the VPS; install it from the official package repository first' ;;
   45) die 'VPS package setup or Python 3.11+ check failed; check apt and Python on the VPS' ;;
   46) die 'VPS service account or directory setup failed; check for an existing account or partial install' ;;
   47) die 'FinPRED checkout failed on the VPS; verify that --repo contains --ref and the VPS can fetch it and its submodules' ;;
   48) die 'FinPRED native build or self-test failed on the VPS; check the toolchain, disk space and memory' ;;
   49) die 'Python environment or addon installation failed on the VPS; check package index access and disk space' ;;
   50) die 'MCP service setup or readiness failed; inspect the yieldcraft-mcp service logs on the VPS' ;;
   51) die 'reverse proxy setup failed; inspect the selected proxy and its logs on the VPS' ;;
   52) die 'Quick Tunnel did not report an endpoint; inspect yieldcraft-tunnel and /var/log/yieldcraft-mcp/cloudflared.log on the VPS' ;;
   53) die 'remote command exited successfully but did not report exactly one valid MCP candidate URL' ;;
   *) die 'SSH command did not complete the deployment; check the SSH login and VPS shell locally' ;;
  esac
 }
else
 url=$(python3 "$HERE/deployment/telnet_transport.py" "$target" "$telnet_port" "$stage/payload.tar.gz" "${args[@]}") ||
  die 'Telnet transport or remote install failed; inspect the VPS locally'
fi
python3 "$HERE/deployment/probe.py" "$url" "${probe_args[@]}" || die 'remote service installed but public MCP probe failed; inspect VPS service logs'
printf '\nMCP_SERVER_URL=%s\n' "$url"
if ((auth)); then printf 'TOKEN_FILE=%s\n' "$token_out"; fi
