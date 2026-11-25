#!/usr/bin/env bash
# Root-side dispatcher for UUID-scoped operations. The host CLI uploads only
# static, allowlisted helpers, not shell tasks supplied by the operator.
set +x
set -Eeuo pipefail
umask 077
HERE=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$HERE/instance.sh"
[[ $(id -u) == 0 && $# -ge 3 ]] || exit 60
stage=$1 action=$2 instance_id=$3; shift 3
instance_paths "$instance_id" || exit 60
case $action in install|uninstall|configure|patch) ;; *) exit 60;; esac
open_registry || exit 60
# The lock covers port/domain reservation and shared proxy edits. Do not pass
# its descriptor to service processes (including forked SysV daemons).
if [[ ${1:-} != --locked ]]; then
 exec flock -x --close "$registry/.lock" bash "$0" "$stage" "$action" "$instance_id" --locked "$@"
fi
shift
if [[ $action == install ]]; then
 [[ $# == 10 ]] || exit 60
 p=$1 i=$2 r=$3 d=$4 e=$5 c=$6; shift 6
 exec bash "$HERE/install.sh" install "$instance_id" "$p" "$i" "$r" "$d" "$e" "$c" "$stage" "$@"
fi

record="$registry/$instance_id.instance"
transition="$registry/$instance_id.transition.instance"
load_record "$record" || exit 60
expected_port=${1:-}; shift
[[ $expected_port == 0 || $expected_port == "$port" ]] || exit 60

trusted_file(){
 [[ -f $1 && ! -L $1 && $(stat -c '%u' -- "$1") == 0 ]] || return 1
 local mode
 mode=$(stat -c '%a' -- "$1") || return 1
 (( (8#$mode & 022) == 0 ))
}

remove_unit(){
 local service_name=$1 launcher=$2 path
 if [[ $init == systemd ]]; then
  path="/etc/systemd/system/$service_name.service"
  [[ -e $path || -L $path ]] || return 0
  trusted_file "$path" && grep -Fxq -- "ExecStart=$launcher" "$path" &&
   systemctl disable --now "$service_name.service" && rm -- "$path" && systemctl daemon-reload
 else
  path="/etc/init.d/$service_name"
  [[ -e $path || -L $path ]] || return 0
  trusted_file "$path" && grep -Fxq -- "CMD=$launcher" "$path" &&
   service "$service_name" stop && update-rc.d -f "$service_name" remove && rm -- "$path"
 fi
}

restart_backend(){
 if [[ $init == systemd ]]; then systemctl restart "$backend.service"; else service "$backend" restart; fi
}

reload_proxy(){
 local kind=$1 rc
 case $kind in
  nginx|caddy) command -v "$kind" >/dev/null || return 0;;
  apache2) command -v apache2ctl >/dev/null || return 0;;
 esac
 if service "$kind" status >/dev/null 2>&1; then
  case $kind in
   nginx) nginx -t || return 1;;
   apache2) apache2ctl configtest || return 1;;
   caddy) caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile || return 1;;
  esac
  service "$kind" reload
 else
  rc=$?
  # LSB 3/4: stopped/unknown. Do not mask other status failures.
  [[ $rc == 3 || $rc == 4 ]]
 fi
}

remove_proxy(){
 local kind=$1 force=${2:-0} site='' enabled='' snapshot='' link_target=''
 case $kind in
  cloudflared) remove_unit "$tunnel" "$base/run-tunnel"; return;;
  nginx) site=/etc/nginx/sites-available/$backend; enabled=/etc/nginx/sites-enabled/$backend;;
  apache2) site=/etc/apache2/sites-available/$backend.conf; enabled=/etc/apache2/sites-enabled/$backend.conf;;
  caddy) site=/etc/caddy/yieldcraft.d/$backend.caddy;;
  *) return 1;;
 esac
 if (( ! force )) && [[ ! -e $site && ! -L $site && ( -z $enabled || ( ! -e $enabled && ! -L $enabled ) ) ]]; then
  return 0
 fi
 if [[ -e $site || -L $site ]]; then
  trusted_file "$site" && grep -Fxq -- "# Yieldcraft instance $instance_id" "$site" || return 1
 fi
 if [[ -n $enabled && ( -e $enabled || -L $enabled ) ]]; then
  [[ -L $enabled && $(realpath -m -- "$enabled") == "$site" ]] || return 1
  link_target=$(readlink -- "$enabled") || return 1
 fi
 if [[ -e $site ]]; then
  snapshot=$(mktemp "$(dirname -- "$site")/.$backend.XXXXXXXX") || return 1
  if ! mv -T -- "$site" "$snapshot"; then rm -f -- "$snapshot"; return 1; fi
 fi
 if { [[ -z $link_target ]] || rm -- "$enabled"; } && reload_proxy "$kind"; then
  if [[ -n $snapshot ]]; then rm -- "$snapshot" || return 1; fi
  return 0
 fi
 # Restore the files before reporting a shared-proxy reload failure.
 if [[ -n $snapshot ]]; then mv -T -- "$snapshot" "$site" || return 1; fi
 if [[ -n $link_target && ! -L $enabled ]]; then ln -s -- "$link_target" "$enabled" || return 1; fi
 reload_proxy "$kind" || :
 return 1
}

wait_backend(){
 local i
 for ((i=0; i<25; i++)); do
  if /usr/bin/python3 -I "$HERE/probe.py" --local-ready "$port"; then return 0; fi
  sleep 1
 done
 return 1
}

start_proxy(){
 # Use a subprocess so errexit in the proxy installer is not suppressed by
 # the caller checking its status.
 bash "$HERE/install.sh" proxy "$instance_id" "$port" "$init" "$@" >/dev/null
}

case $action in
 uninstall)
  [[ $# == 0 ]] || exit 60
  # In case an earlier proxy change failed mid-flight, remove any managed
  # snippets bearing this ID, not just the one named in the registry.
  remove_proxy "$proxy" 1 || exit 61
  for kind in cloudflared nginx apache2 caddy; do
   [[ $kind == "$proxy" ]] || remove_proxy "$kind" || exit 61
  done
  remove_unit "$backend" "$base/run-mcp" || exit 61
  if [[ -e $base || -L $base ]]; then
   [[ -d $base && ! -L $base && $(stat -c '%u' -- "$base") == 0 ]] || exit 61
   if mountpoint -q -- "$base"; then exit 61; fi
   rm -rf --one-file-system -- "$base" || exit 61
  fi
  rm -f -- "$transition" || exit 61
  mv -T -- "$record" "$registry/$instance_id.retired" || exit 61
  ;;
 patch)
  [[ $# == 2 && $status == active && ! -e $transition && ! -L $transition ]] || exit 60
  exec /usr/bin/python3 -I -B "$HERE/patch.py" "$port" "$1" "$2" "$user"
  ;;
 configure)
  [[ $# == 5 && $status == active && ! -e $transition && ! -L $transition ]] || exit 60
  new_daemon=$1 new_proxy=$2 new_domain=$3 new_email=$4 new_cf=$5
  [[ $new_daemon == = || $new_daemon == 1 || $new_daemon == 0 ]] || exit 60
  if [[ $new_proxy == = ]]; then
   new_proxy=$proxy new_domain=$domain new_email=$email new_cf=$cf_config
  else
   valid_proxy "$new_proxy" "$new_domain" "$new_email" "$new_cf" &&
    available_route "$port" "$new_domain" "$record" || exit 60
  fi
  proxy_change=0
  if [[ $new_proxy != "$proxy" || $new_domain != "$domain" || $new_email != "$email" || $new_cf != "$cf_config" ]]; then
   proxy_change=1
  fi
  if ((proxy_change)); then
   if [[ $new_proxy == cloudflared ]]; then command -v cloudflared >/dev/null || exit 62; fi
   target_domain=$new_domain
  else
   target_domain='='
  fi
  config="$etc/config.toml"
  trusted_file "$config" || exit 62
  candidate=$(mktemp "$etc/.configure.XXXXXXXX") || exit 62
  trap 'rm -f -- "$candidate"' EXIT
  /usr/bin/python3 -I "$HERE/reconfigure.py" "$config" "$candidate" "$port" "$base/finpred" "$new_daemon" "$target_domain" ||
   exit 62
  if cmp -s -- "$config" "$candidate" && (( ! proxy_change )); then exit 0; fi
  chown root:"$user" "$candidate" && chmod 0640 "$candidate" || exit 62
  runuser -u "$user" -- "$base/venv/bin/python" -I -c \
   'import sys; from pathlib import Path; from yieldcraft_mcp.config import load; load(Path(sys.argv[1]))' "$candidate" ||
   exit 62
  backup=$(mktemp "$etc/config.pre-configure.XXXXXXXX.toml") || exit 62
  cat -- "$config" > "$backup" || exit 62
  if ((proxy_change)); then
   save_record "$transition" pending "$port" "$init" "$new_proxy" "$new_domain" "$new_email" "$new_cf" || exit 62
  fi

  rollback(){
   trap '' HUP INT TERM
   local failed=0
   if ((proxy_change && new_started)); then remove_proxy "$new_proxy" 1 || failed=1; fi
   if ((backend_changed)); then
    if install -m 0640 -o root -g "$user" -- "$backup" "$candidate" &&
     mv -T -- "$candidate" "$config" && restart_backend && wait_backend; then :; else failed=1; fi
   fi
   if ((proxy_change && old_removed)); then
    start_proxy "$proxy" "$domain" "$email" "$cf_config" || failed=1
   fi
   if ((failed)); then exit 64; fi
   rm -f -- "$transition" || exit 64
   exit 63
  }
  old_removed=0 backend_changed=0 new_started=0
  trap rollback HUP INT TERM
  if ((proxy_change)); then
   if ! remove_proxy "$proxy" 1; then exit 64; fi
   old_removed=1
  fi
  if ! cmp -s -- "$config" "$candidate"; then
   backend_changed=1
   mv -T -- "$candidate" "$config" && restart_backend && wait_backend || rollback
  fi
  if ((proxy_change)); then
   new_started=1
   start_proxy "$new_proxy" "$new_domain" "$new_email" "$new_cf" || rollback
   save_record "$record" active "$port" "$init" "$new_proxy" "$new_domain" "$new_email" "$new_cf" || rollback
   rm -f -- "$transition" || exit 64
  fi
  trap - HUP INT TERM
  ;;
esac
