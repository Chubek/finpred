# Shared by the host CLI and the root-side deployment commands. No side effects
# on source; only validated UUIDs may select an instance.
valid_instance_id(){
 [[ $1 =~ ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$ ]]
}

instance_prefix(){
 local compact=${1//-/} escaped='' encoded i
 valid_instance_id "$1" || return 1
 # A UUIDv4 provides 122 random bits. Base32 retains all bits while keeping the
 # account name below Debian's 32-character limit (and reserving no extra ID).
 for ((i=0; i<32; i+=2)); do escaped+="\\x${compact:i:2}"; done
 encoded=$(printf '%b' "$escaped" | base32 -w0) || return 1
 encoded=${encoded//=}
 printf 'yc-%s\n' "${encoded,,}"
}

instance_paths(){
 local prefix
 prefix=$(instance_prefix "$1") || return 1
 user=$prefix
 backend="$prefix-mcp" tunnel="$prefix-tunnel"
 base="/opt/$prefix" etc="/etc/$prefix" state="/var/lib/$prefix" logs="/var/log/$prefix"
}

valid_domain(){
 [[ ${#1} -le 253 && $1 =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]
}

valid_port(){
 [[ $1 =~ ^[1-9][0-9]{0,4}$ && $1 -le 65535 ]]
}

valid_proxy(){
 case $1 in cloudflared|nginx|apache2|caddy) ;; *) return 1;; esac
 if [[ $2 != - ]]; then valid_domain "$2" || return 1
 elif [[ $1 != cloudflared ]]; then return 1
 fi
 if [[ $1 == nginx || $1 == apache2 ]]; then
  [[ $3 =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || return 1
 else [[ $3 == - ]] || return 1
 fi
 if [[ $1 == cloudflared && $2 != - ]]; then
  [[ $4 =~ ^/[a-zA-Z0-9_./-]+$ && $4 != *..* ]] || return 1
 else [[ $4 == - ]] || return 1
 fi
}

registry=/etc/yieldcraft-instances

open_registry(){
 [[ ! -L $registry ]] || return 1
 if [[ ! -d $registry ]]; then mkdir -m 0700 -- "$registry" || [[ -d $registry && ! -L $registry ]] || return 1; fi
 [[ $(stat -c '%u:%a' -- "$registry") == 0:700 ]]
}

save_record(){
 local path=$1 tmp; shift
 tmp=$(mktemp "$registry/.record.XXXXXXXX") || return 1
 if ! printf '%s %s %s %s %s %s %s\n' "$@" > "$tmp" || ! mv -T -- "$tmp" "$path"; then
  rm -f -- "$tmp"
  return 1
 fi
}

load_record(){
 local path=$1 extra
 [[ -f $path && ! -L $path && $(stat -c '%u:%a' -- "$path") == 0:600 ]] || return 1
 IFS=' ' read -r status port init proxy domain email cf_config extra < "$path" || return 1
 [[ -z $extra && ( $status == pending || $status == active ) && ( $init == systemd || $init == sysvinit ) ]] &&
  valid_port "$port" && valid_proxy "$proxy" "$domain" "$email" "$cf_config"
}

available_route(){
 local wanted_port=$1 wanted_domain=$2 skip=$3 path
 # Isolate globals written by load_record; ignore retired records.
 for path in "$registry"/*.instance; do
  [[ -e $path || -L $path ]] || continue
  [[ $path != "$skip" ]] || continue
  (load_record "$path" &&
    [[ $port != "$wanted_port" && ( $wanted_domain == - || $domain != "$wanted_domain" ) ]]) || return 1
 done
}
