#!/usr/bin/env bash
# Run from a host PC. No remote command is executed in --dry-run.
set +x
set -Eeuo pipefail
umask 077
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
usage(){ cat <<'HELP'
Usage: deploy.sh [USER@]HOST [-p|--port 8788] [-r|--reverse-proxy cloudflared|nginx|apache2|caddy]
  [-d|--domain foo.com] [--ssh|--telnet] [--systemd|--sysvinit]
  [--ssh-port 22] [--identity FILE] [--telnet-port 23]
  [--repo https://github.com/Chubek/finpred.git] [--ref FULL_COMMIT_SHA]
  [--email ADDRESS] [--cloudflared-config /remote/path.yml]
  [--no-auth|--auth] [--token-out FILE] [--no-daemon] [--dry-run]
       deploy.sh [USER@]HOST --patch --no-auth [-p|--port 8788] [-d|--domain foo.com] [--dry-run]
       deploy.sh [USER@]HOST --show-endpoint [-p|--port 8788] [-d|--domain foo.com] [--dry-run]
Deploy a fresh Debian/Ubuntu Linux x86-64 service. SSH is the default.
--patch --no-auth switches an existing SSH deployment to the limited public
demo on the same backend port and proxy. It does not reinstall software.
--show-endpoint prints the existing HTTPS /mcp URL over SSH without changing
the installation or probing the public service. An optional domain must match.
Telnet is supported only through a separately secured loopback management tunnel.
Nginx/Apache2 require a domain pointing at the VPS and --email for Certbot.
Cloudflared without a domain uses a temporary Quick Tunnel (JSON HTTP, not SSE).
For a named tunnel, provision DNS and credentials on the VPS and pass its config.
Its private files can use mode 0640 with a dedicated, empty yieldcraft-mcp group.
Default: --no-auth serves a public synthetic demo without stored runs or live access.
Use --auth for the full service. It generates a local bearer credential and uploads only its hash.
Fresh installs refuse to overwrite an existing deployment or token file.
HELP
}
die(){ echo "deploy: $*" >&2; exit 2; }
[[ $# -gt 0 ]] || { usage; exit 2; }; [[ $1 != -h && $1 != --help ]] || { usage; exit 0; }
target=$1; shift
port=8788 proxy=cloudflared domain='' protocol=ssh init=systemd ssh_port=22 telnet_port=23 identity='' email='' cf_config='' repo=https://github.com/Chubek/finpred.git ref=957e9671a14460200318e6285728c2f9904efa8c dry=0 daemon=1 auth=0 token_out_set=0 token_out="$PWD/yieldcraft-mcp.token"
patch=0 show_endpoint=0 auth_choice='' patch_init=auto install_option='' telnet_set=0
# Prefer the checked-out parent repository if this addon is inside it.
if top=$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null) && [[ -f "$top/bin/finpred" ]]; then ref=$(git -C "$top" rev-parse HEAD); fi
while (($#)); do
 case "$1" in
  -p|--port|-r|--reverse-proxy|-d|--domain|--ssh-port|--telnet-port|--identity|--repo|--ref|--email|--cloudflared-config|--token-out)
   [[ $# -ge 2 && -n $2 ]] || die "$1 requires a value"; key=$1; val=$2; shift 2
   case "$key" in -r|--reverse-proxy|--telnet-port|--repo|--ref|--email|--cloudflared-config|--token-out) install_option=$key;; esac
   case "$key" in -p|--port) port=$val;; -r|--reverse-proxy) proxy=$val;; -d|--domain) domain=$val;; --ssh-port) ssh_port=$val;; --telnet-port) telnet_port=$val;; --identity) identity=$val;; --repo) repo=$val;; --ref) ref=$val;; --email) email=$val;; --cloudflared-config) cf_config=$val;; --token-out) token_out=$val; token_out_set=1;; esac;;
  --auth) auth=1; auth_choice=auth; shift;; --no-auth) auth=0; auth_choice=no-auth; shift;;
  --patch) patch=1; shift;; --show-endpoint) show_endpoint=1; shift;;
  --telnet) protocol=telnet; telnet_set=1; shift;;
  --ssh) protocol=ssh; shift;; --systemd|--sysvinit) init=${1#--}; patch_init=$init; shift;; --no-daemon) daemon=0; shift;; --dry-run) dry=1; shift;; -h|--help) usage; exit 0;; *) die "unknown argument: $1";; esac
done
[[ $target =~ ^([a-zA-Z_][a-zA-Z0-9_-]{0,31}@)?[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}$ ]] || die 'expected [USER@]HOST (IPv4/DNS)'
for v in "$port" "$ssh_port" "$telnet_port"; do [[ $v =~ ^[1-9][0-9]{0,4}$ && $v -le 65535 ]] || die 'invalid port'; done
if [[ -n $domain ]]; then [[ ${#domain} -le 253 && $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || die 'invalid DNS domain'; fi
if ((show_endpoint)); then
 (( ! patch )) || die '--show-endpoint cannot be combined with --patch'
 (( ! telnet_set )) || die '--show-endpoint requires SSH'
 [[ -z $install_option ]] || die "$install_option is not supported with --show-endpoint"
 [[ -z $auth_choice && $patch_init == auto && $daemon == 1 ]] ||
  die '--show-endpoint does not accept authentication, daemon or service-manager options'
elif ((patch)); then
 [[ $auth_choice == no-auth ]] || die '--patch requires explicit --no-auth'
 [[ $protocol == ssh ]] || die '--patch requires SSH'
 [[ -z $install_option ]] || die "$install_option is a fresh-install option; --patch preserves the existing installation"
else
 [[ $proxy != clouadflared ]] || proxy=cloudflared
 case $proxy in cloudflared|nginx|apache2|caddy) ;; *) die 'unknown reverse proxy';; esac
 [[ $ref =~ ^[0-9a-f]{40}$ ]] || die 'use an immutable full Git commit SHA'
 [[ $repo =~ ^https://[a-zA-Z0-9.-]+/[a-zA-Z0-9_./-]+\.git$ && $repo != *..* ]] || die 'expected HTTPS Git URL ending in .git'
 if [[ $proxy != cloudflared ]]; then [[ -n $domain ]] || die 'domain required'; fi
 if [[ $proxy == nginx || $proxy == apache2 ]]; then [[ $email =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || die 'valid --email required for Certbot'; fi
 if [[ $proxy == cloudflared && -n $domain ]]; then [[ $cf_config =~ ^/[a-zA-Z0-9_./-]+$ && $cf_config != *..* ]] || die 'named tunnel needs --cloudflared-config remote path'; else [[ -z $cf_config ]] || die 'cloudflared config is for a named tunnel only'; fi
 if [[ $protocol == telnet ]]; then
  [[ $target == *@* && ( ${target#*@} == 127.0.0.1 || ${target#*@} == localhost ) ]] || die 'Telnet requires USER@HOST on a separately secured loopback tunnel; use SSH for public VPS'
 fi
fi
if (( ! show_endpoint )); then
 if ((auth)); then
  [[ $token_out != *[[:cntrl:]]* ]] || die 'token output path must not contain control characters'
 else
  (( ! token_out_set )) || die '--token-out requires --auth'
  daemon=0
 fi
fi
if ((dry)); then
 if ((show_endpoint)); then
  printf 'target=%s protocol=ssh action=show-endpoint port=%s domain=%s\n' "$target" "$port" "${domain:-existing}"
 elif ((patch)); then
  printf 'target=%s protocol=ssh action=patch init=%s port=%s domain=%s daemon=0 auth=0\n' "$target" "$patch_init" "$port" "${domain:-existing}"
 else
  printf 'target=%s protocol=%s init=%s port=%s proxy=%s domain=%s ref=%s daemon=%s auth=%s\n' "$target" "$protocol" "$init" "$port" "$proxy" "${domain:-dynamic}" "$ref" "$daemon" "$auth"
 fi
 exit 0
fi
if [[ $protocol == ssh ]]; then
 command -v ssh >/dev/null || die 'OpenSSH client required on host PC'
 sshargs=(-T -p "$ssh_port" -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o ForwardAgent=no -o ClearAllForwardings=yes); [[ -z $identity ]] || sshargs+=(-i "$identity")
fi
ssh_candidate(){
 local remote_cmd=$1 input=$2 expected_domain=$3 statuses
 # Never print or save the remote transcript. A remote failure takes priority
 # when the candidate is also missing or invalid.
 ssh "${sshargs[@]}" "$target" "$remote_cmd" < "$input" 2>/dev/null |
  PYTHONIOENCODING=utf-8:replace python3 "$HERE/deployment/probe.py" --candidate "$expected_domain" 2>/dev/null
 statuses=("${PIPESTATUS[@]}")
 if ((statuses[0])); then return "${statuses[0]}"; fi
 if ((statuses[1])); then return 53; fi
}
if ((show_endpoint)); then
 command -v python3 >/dev/null || die 'python3 required on host PC'
 helper=$HERE/deployment/show_endpoint.py
 [[ -d $HERE/deployment && ! -L $HERE/deployment && -f $helper && ! -L $helper ]] ||
  die 'missing or non-regular deployment source: deployment/show_endpoint.py'
 # Stream the read-only helper into a Python process running as the service
 # user, which can read both the installed config and its private log.
 remote='set +x; set -eu; u=yieldcraft-mcp; id -u "$u" >/dev/null || exit 54; if [ "$(id -un)" = "$u" ]; then set --; elif [ "$(id -u)" = 0 ]; then set -- /usr/sbin/runuser -u "$u" --; else set -- sudo -n -u "$u" --; fi; exec "$@" /usr/bin/python3 -I -B -'
 remote+=" '$port'"
 url=$(ssh_candidate "$remote" "$helper" "${domain:-existing}") || {
  case $? in
   255) die 'SSH transport failed; check the host, SSH port, known host key and login credentials' ;;
   53) die 'remote command did not report exactly one valid MCP candidate URL matching any requested domain' ;;
   54) die 'no matching Yieldcraft installation; check the installed config and requested backend port on the VPS' ;;
   55) die 'could not determine the existing public URL; check the configured domain or Quick Tunnel logs on the VPS' ;;
   *) die 'could not run the read-only VPS lookup; check Python 3.11+ and, for a non-root SSH user, passwordless sudo -n -u yieldcraft-mcp' ;;
  esac
 }
 printf '%s\n' "$url"
 exit 0
fi
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
if ((patch)); then
 payload_files=(deployment/patch.py deployment/probe.py deployment/show_endpoint.py)
 source_dirs=(deployment)
 program='/usr/bin/python3 -I "$t/addon/deployment/patch.py"'
 args=("$port" "$patch_init" "${domain:--}")
 candidate_domain=${domain:-existing}
else
 payload_files=(
  pyproject.toml deployment/install.sh deployment/sysvinit.in deployment/tunnel_config.py
  highlighting/ottomat.js highlighting/ottomat.tmLanguage.json
  native/bridge.on1x native/build.py
  yieldcraft_mcp/{__init__,__main__,artifacts,auth,config,dragnet,engine,highlight,models,ottomat,processes,server}.py
  yieldcraft_mcp/ui/editor.html
 )
 source_dirs=(deployment highlighting native yieldcraft_mcp yieldcraft_mcp/ui)
 program='bash "$t/addon/deployment/install.sh" "$t"'
 args=("$port" "$proxy" "${domain:--}" "$init" "$repo" "$ref" "${email:--}" "${cf_config:--}" "$daemon" "$auth")
 candidate_domain=${domain:--}
fi
for dir in "${source_dirs[@]}"; do
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
if [[ $protocol == ssh ]]; then
 remote='set +x; set -eu; umask 077; t=$(mktemp -d) || exit 40; trap '\''rm -rf -- "$t"'\'' 0; trap '\''exit 40'\'' HUP INT TERM; tar --no-same-owner --no-same-permissions -xzf - -C "$t" || exit 40; if [ "$(id -u)" = 0 ]; then set --; else set -- sudo -n; fi; "$@" '"$program"
 for a in "${args[@]}"; do remote+=" '$a'"; done
 # Only the installer's reserved stage statuses pass through. OpenSSH uses 255.
 remote+=' || { rc=$?; case "$rc" in 4[2-9]|5[0-2]|5[4-9]) exit "$rc";; *) exit 41;; esac; }'
 url=$(ssh_candidate "$remote" "$stage/payload.tar.gz" "$candidate_domain") || {
  case $? in
   255) die 'SSH transport failed; check the host, SSH port, known host key and login credentials' ;;
   40) die 'SSH connected, but VPS staging or archive extraction failed; check tar and temporary disk space' ;;
   41) die 'could not run the VPS deployment command; check Bash or Python 3.11+ and, for a non-root SSH user, passwordless sudo -n' ;;
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
   54) die 'no matching Yieldcraft installation; check the configured backend port and service manager on the VPS' ;;
   55) die 'could not determine the existing public URL; check the configured domain or Quick Tunnel logs on the VPS' ;;
   56) die 'could not prepare the public demo patch; check addon support and permissions on the VPS (existing config unchanged)' ;;
   57) die 'public demo failed its VPS startup check; the previous config was restored and service restarted' ;;
   58) die 'public demo patch failed and rollback could not be verified; inspect the VPS config backups and service logs' ;;
   59) die 'another Yieldcraft patch is already in progress on the VPS' ;;
   *) die 'SSH command did not complete the deployment; check the SSH login and VPS shell locally' ;;
  esac
 }
else
 url=$(python3 "$HERE/deployment/telnet_transport.py" "$target" "$telnet_port" "$stage/payload.tar.gz" "${args[@]}") ||
  die 'Telnet transport or remote install failed; inspect the VPS locally'
fi
python3 "$HERE/deployment/probe.py" "$url" "${probe_args[@]}" || {
 if ((patch)); then die 'public demo patch applied on the VPS, but the public MCP probe failed; check the existing proxy and service logs'; fi
 die 'remote service installed but public MCP probe failed; inspect VPS service logs'
}
printf '\nMCP_SERVER_URL=%s\n' "$url"
if ((auth)); then printf 'TOKEN_FILE=%s\n' "$token_out"; fi
