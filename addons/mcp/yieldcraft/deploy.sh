#!/usr/bin/env bash
# Run from a host PC. No remote command is executed in --dry-run.
set -Eeuo pipefail
umask 077
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
usage(){ cat <<'HELP'
Usage: deploy.sh USER@HOST [-p|--port 8788] [-r|--reverse-proxy cloudflared|nginx|apache2|caddy]
  [-d|--domain foo.com] [--ssh|--telnet] [--systemd|--sysvinit]
  [--ssh-port 22] [--identity FILE] [--telnet-port 23]
  [--repo https://github.com/Chubek/finpred.git] [--ref FULL_COMMIT_SHA]
  [--email ADDRESS] [--cloudflared-config /remote/path.yml]
  [--token-out FILE] [--no-daemon] [--dry-run]
Deploy a fresh Debian/Ubuntu Linux x86-64 service. SSH is the default.
Telnet is supported only through a separately secured loopback management tunnel.
Nginx/Apache2 require a domain pointing at the VPS and --email for Certbot.
Cloudflared without a domain uses a temporary Quick Tunnel (JSON HTTP, not SSE).
For a named tunnel, provision DNS and credentials on the VPS and pass its config.
A bearer credential is generated locally; only its hash is uploaded.
The script refuses to overwrite an existing deployment or token file.
HELP
}
die(){ echo "deploy: $*" >&2; exit 2; }
[[ $# -gt 0 ]] || { usage; exit 2; }; [[ $1 != -h && $1 != --help ]] || { usage; exit 0; }
target=$1; shift
port=8788 proxy=cloudflared domain='' protocol=ssh init=systemd ssh_port=22 telnet_port=23 identity='' email='' cf_config='' repo=https://github.com/Chubek/finpred.git ref=957e9671a14460200318e6285728c2f9904efa8c dry=0 daemon=1 token_out="$PWD/yieldcraft-mcp.token"
# Prefer the checked-out parent repository if this addon is inside it.
if top=$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null) && [[ -f "$top/bin/finpred" ]]; then ref=$(git -C "$top" rev-parse HEAD); fi
while (($#)); do
 case "$1" in
 -p|--port|-r|--reverse-proxy|-d|--domain|--ssh-port|--telnet-port|--identity|--repo|--ref|--email|--cloudflared-config|--token-out)
  [[ $# -ge 2 && -n $2 ]] || die "$1 requires a value"; key=$1; val=$2; shift 2
  case "$key" in -p|--port) port=$val;; -r|--reverse-proxy) proxy=$val;; -d|--domain) domain=$val;; --ssh-port) ssh_port=$val;; --telnet-port) telnet_port=$val;; --identity) identity=$val;; --repo) repo=$val;; --ref) ref=$val;; --email) email=$val;; --cloudflared-config) cf_config=$val;; --token-out) token_out=$val;; esac;;
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
if ((dry)); then printf 'target=%s protocol=%s init=%s port=%s proxy=%s domain=%s ref=%s daemon=%s\n' "$target" "$protocol" "$init" "$port" "$proxy" "${domain:-dynamic}" "$ref" "$daemon"; exit 0; fi
[[ ! -e $token_out && ! -L $token_out ]] || die 'token output already exists'
command -v python3 >/dev/null || die 'python3 required on host PC'
stage=$(mktemp -d); trap 'rm -rf -- "$stage"' EXIT
mkdir "$stage/addon"; tar -C "$HERE" --exclude=.git --exclude=.venv --exclude='__pycache__' --exclude='.pytest_cache' --exclude='*.token' --exclude='*.pyc' -cf - . | tar -C "$stage/addon" -xf -
python3 "$HERE/deployment/token.py" --cleartext "$token_out" --records "$stage/tokens.json" --admin
# No plaintext token in archive, SSH commands, or logs.
tar -C "$stage" -czf "$stage/payload.tar.gz" addon tokens.json
args=("$port" "$proxy" "${domain:--}" "$init" "$repo" "$ref" "${email:--}" "${cf_config:--}" "$daemon")
if [[ $protocol == ssh ]]; then
 sshargs=(-p "$ssh_port" -o StrictHostKeyChecking=yes -o ConnectTimeout=15); [[ -z $identity ]] || sshargs+=(-i "$identity")
 remote='set -eu; umask 077; t=$(mktemp -d); trap '\''rm -rf -- "$t"'\'' EXIT; tar -xzf - -C "$t"; if [ "$(id -u)" = 0 ]; then bash "$t/addon/deployment/install.sh" "$t"';
 for a in "${args[@]}"; do remote+=" '$a'"; done
 remote+='; else sudo -n bash "$t/addon/deployment/install.sh" "$t"'; for a in "${args[@]}"; do remote+=" '$a'"; done; remote+='; fi'
 ssh "${sshargs[@]}" "$target" "$remote" < "$stage/payload.tar.gz" | tee "$stage/result"
else
 python3 "$HERE/deployment/telnet_transport.py" "$target" "$telnet_port" "$stage/payload.tar.gz" "${args[@]}" | tee "$stage/result"
fi
url=$(sed -n 's/^MCP_CANDIDATE_URL=//p' "$stage/result" | tail -1 | tr -d '\r'); [[ $url =~ ^https://[a-zA-Z0-9.-]+/mcp$ ]] || die 'remote install did not report a valid URL'
python3 "$HERE/deployment/probe.py" "$url" "$token_out" || die 'remote service installed but public MCP probe failed; inspect VPS service logs'
printf '\nMCP_SERVER_URL=%s\nTOKEN_FILE=%s\n' "$url" "$token_out"
