#!/usr/bin/env bash
# Remote fresh installer; invoked only by deploy.sh on the selected VPS.
set -Eeuo pipefail
umask 077
[[ $(id -u) = 0 && $# = 10 ]] || { echo 'root and 10 arguments required' >&2; exit 2; }
stage=$1 port=$2 proxy=$3 domain=$4 init=$5 repo=$6 ref=$7 email=$8 cf_config=$9 daemon=${10}
base=/opt/yieldcraft-mcp; etc=/etc/yieldcraft-mcp; state=/var/lib/yieldcraft-mcp; logs=/var/log/yieldcraft-mcp; user=yieldcraft-mcp
fail(){ echo "install: $*" >&2; exit 2; }
[[ $port =~ ^[1-9][0-9]{0,4}$ && $port -le 65535 && $ref =~ ^[a-f0-9]{40}$ && $repo =~ ^https://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]+\.git$ && $repo != *..* ]] || fail 'invalid deployment arguments'
[[ $domain == - || $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || fail 'invalid domain'
[[ $init == systemd || $init == sysvinit ]] || fail 'invalid service manager'; [[ $daemon == 0 || $daemon == 1 ]] || fail 'invalid daemon option'
case $proxy in cloudflared|nginx|apache2|caddy) ;; *) fail 'unknown proxy';; esac
[[ $proxy == cloudflared || $domain != - ]] || fail 'domain required'
if [[ $proxy == nginx || $proxy == apache2 ]]; then [[ $email =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || fail 'Certbot email required'; fi
if [[ $proxy == cloudflared && $domain != - ]]; then [[ $cf_config =~ ^/[A-Za-z0-9_./-]+$ && $cf_config != *..* && -f $cf_config ]] || fail 'preprovisioned tunnel config required'; fi
[[ $(uname -m) == x86_64 ]] || fail 'supported target is Linux x86-64'
. /etc/os-release; [[ $ID == debian || $ID == ubuntu ]] || fail 'Debian/Ubuntu only'
[[ ! -e $base && ! -e $etc && ! -e $state && ! -e $logs ]] || fail 'existing installation; refuse overwrite (see README)'
[[ ! -e /etc/systemd/system/yieldcraft-mcp.service && ! -e /etc/systemd/system/yieldcraft-tunnel.service && ! -e /etc/init.d/yieldcraft-mcp && ! -e /etc/init.d/yieldcraft-tunnel ]] || fail 'existing service definitions'
if [[ $init == systemd ]]; then [[ -d /run/systemd/system ]] || fail 'systemd not active'; else command -v start-stop-daemon >/dev/null || fail 'SysV start-stop-daemon missing'; fi
if [[ $proxy == cloudflared ]]; then command -v cloudflared >/dev/null || fail 'install cloudflared from the official trusted package repository on the VPS first'; fi
export DEBIAN_FRONTEND=noninteractive
apt-get update >&2; apt-get install -y --no-install-recommends git build-essential cmake pkg-config perl python3 python3-venv python3-pip libcurl4-openssl-dev libssl-dev zlib1g-dev ca-certificates curl make iproute2 >&2
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ss -Hln sport = ":$port" | grep -q .; then fail 'selected port already in use'; fi
if ! id "$user" >/dev/null 2>&1; then useradd --system --no-create-home --home-dir "$state" --shell /usr/sbin/nologin "$user"; else fail 'service account already exists'; fi
install -d -m 0755 "$base"; install -d -m 0700 -o "$user" -g "$user" "$state" "$logs"; install -d -m 0750 -o root -g "$user" "$etc"
# Failure leaves diagnostic files; no existing deployment overwritten. Explicit cleanup documented.
trap 'echo "Installation failed at line $LINENO; inspect $logs and run documented fresh-install cleanup." >&2' ERR
install -d -m 0755 -o "$user" -g "$user" "$base/finpred" "$base/addon" "$base/venv"
cp -a "$stage/addon/." "$base/addon/"; chown -R "$user:$user" "$base/addon"
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" init -q
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" remote add origin "$repo"
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" fetch --depth=1 origin "$ref" >&2
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" checkout --detach FETCH_HEAD >&2
[[ $(runuser -u "$user" -- git -C "$base/finpred" rev-parse HEAD) == "$ref" ]] || fail 'commit pin mismatch'
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" submodule update --init third_party/mulib >&2
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred/third_party/mulib" submodule update --init on1x/third_party/libstone >&2
# Native source builds run without root and with private scratch paths.
runuser -u "$user" -- env HOME="$state" bash -c 'set -e; cd "$1"; make mulib; make; make dragnet; bin/yieldcraft-demand build; bin/yieldcraft-inventory build; bin/finpred selftest' _ "$base/finpred" >&2
runuser -u "$user" -- env HOME="$state" python3 -m venv "$base/venv"
runuser -u "$user" -- env HOME="$state" "$base/venv/bin/pip" install --disable-pip-version-check "$base/addon" >&2
# Runtime account must not modify executable code or operator config.
chown -R root:root "$base"; chmod -R a+rX,go-w "$base"
install -m 0600 -o "$user" -g "$user" "$stage/tokens.json" "$etc/tokens.json"
install -d -m 0700 -o "$user" -g "$user" "$state/projects"
cat > "$etc/config.toml" <<CFG
finpred_root = "$base/finpred"
state_dir = "$state/projects"
token_file = "$etc/tokens.json"
bind = "127.0.0.1"
port = $port
enable_live = false
allowed_hosts = []
offer_hosts = []
allow_llm = false
daemon_config = "$base/finpred/plugins/dragnet/examples/Dragnet.json"
daemon_autostart = $( [[ $daemon == 1 ]] && echo true || echo false )
CFG
if [[ $domain != - ]]; then printf 'public_url = "https://%s/mcp"\n' "$domain" >> "$etc/config.toml"; fi
chown root:"$user" "$etc/config.toml"; chmod 0640 "$etc/config.toml"
cat > "$base/run-mcp" <<RUN
#!/bin/sh
umask 077
exec "$base/venv/bin/python" -m yieldcraft_mcp --config "$etc/config.toml"
RUN
chmod 0755 "$base/run-mcp"
install_service(){
 local name=$1 command=$2
 if [[ $init == systemd ]]; then
 cat > "/etc/systemd/system/$name.service" <<UNIT
[Unit]
Description=$name
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$user
Group=$user
WorkingDirectory=$state
Environment=HOME=$state
UMask=0077
ExecStart=$command
Restart=on-failure
RestartSec=5
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$state $logs
RestrictSUIDSGID=true
[Install]
WantedBy=multi-user.target
UNIT
 systemctl daemon-reload; systemctl enable --now "$name.service" >&2
 else
 sed -e "s|@NAME@|$name|g" -e "s|@COMMAND@|$command|g" "$base/addon/deployment/sysvinit.in" > "/etc/init.d/$name"
 chmod 0755 "/etc/init.d/$name"; update-rc.d "$name" defaults; service "$name" start >&2
 fi
}
install_service yieldcraft-mcp "$base/run-mcp"
for i in $(seq 1 30); do if curl -fsS --max-time 2 "http://127.0.0.1:$port/readyz" >/dev/null; then break; fi; [[ $i != 30 ]] || fail 'MCP readiness failed'; sleep 2; done
case $proxy in
 cloudflared)
  cf=$(command -v cloudflared); [[ $cf =~ ^/[A-Za-z0-9_./-]+$ ]] || fail 'unexpected cloudflared executable path'
  if [[ $domain == - ]]; then
   cat > "$base/run-tunnel" <<RUN
#!/bin/sh
umask 077
exec "$cf" tunnel --no-autoupdate --url "http://127.0.0.1:$port" --logfile "$logs/cloudflared.log"
RUN
  else
   runuser -u "$user" -- test -r "$cf_config" || fail 'named tunnel configuration must be readable by service user; provision scoped credentials outside /root'
   cat > "$base/run-tunnel" <<RUN
#!/bin/sh
umask 077
exec "$cf" tunnel --no-autoupdate --config "$cf_config" --logfile "$logs/cloudflared.log" run
RUN
  fi
  chmod 0755 "$base/run-tunnel"; install_service yieldcraft-tunnel "$base/run-tunnel"
  if [[ $domain == - ]]; then
   url=''; for i in $(seq 1 60); do url=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$logs/cloudflared.log" 2>/dev/null | tail -1 || true); [[ -z $url ]] || break; sleep 2; done
   [[ -n $url ]] || fail 'Quick Tunnel did not publish an endpoint'; url+=/mcp
  else url="https://$domain/mcp"; fi;;
 nginx)
  apt-get install -y nginx certbot python3-certbot-nginx >&2
  [[ ! -e /etc/nginx/sites-available/yieldcraft-mcp && ! -e /etc/nginx/sites-enabled/yieldcraft-mcp ]] || fail 'nginx site already exists'
  cat > /etc/nginx/sites-available/yieldcraft-mcp <<NGINX
server {
 listen 80;
 server_name $domain;
 client_max_body_size 32m;
 location / {
  proxy_pass http://127.0.0.1:$port;
  proxy_http_version 1.1;
  proxy_set_header Host \$host;
  proxy_set_header Authorization \$http_authorization;
  proxy_set_header X-Forwarded-Proto \$scheme;
  proxy_buffering off;
  proxy_read_timeout 1000s;
 }
}
NGINX
  chmod 0644 /etc/nginx/sites-available/yieldcraft-mcp; ln -s /etc/nginx/sites-available/yieldcraft-mcp /etc/nginx/sites-enabled/yieldcraft-mcp
  nginx -t >&2; service nginx reload >&2; certbot --nginx --non-interactive --agree-tos --redirect --email "$email" -d "$domain" >&2; url="https://$domain/mcp";;
 apache2)
  apt-get install -y apache2 certbot python3-certbot-apache >&2
  [[ ! -e /etc/apache2/sites-available/yieldcraft-mcp.conf ]] || fail 'Apache site exists'
  a2enmod proxy proxy_http ssl headers >&2
  cat > /etc/apache2/sites-available/yieldcraft-mcp.conf <<APACHE
<VirtualHost *:80>
 ServerName $domain
 ProxyPreserveHost On
 ProxyRequests Off
 ProxyTimeout 1000
 LimitRequestBody 33554432
 ProxyPass / http://127.0.0.1:$port/ retry=0
 ProxyPassReverse / http://127.0.0.1:$port/
</VirtualHost>
APACHE
  chmod 0644 /etc/apache2/sites-available/yieldcraft-mcp.conf; a2ensite yieldcraft-mcp >&2; apache2ctl configtest >&2; service apache2 reload >&2
  certbot --apache --non-interactive --agree-tos --redirect --email "$email" -d "$domain" >&2; url="https://$domain/mcp";;
 caddy)
  apt-get install -y caddy >&2; [[ ! -e /etc/caddy/yieldcraft-mcp.caddy && ! -e /etc/caddy/Caddyfile.yieldcraft-backup ]] || fail 'Caddy site exists'
  cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.yieldcraft-backup
  cat > /etc/caddy/yieldcraft-mcp.caddy <<CADDY
$domain {
 reverse_proxy 127.0.0.1:$port {
  flush_interval -1
 }
}
CADDY
  chmod 0644 /etc/caddy/yieldcraft-mcp.caddy; printf '\nimport /etc/caddy/yieldcraft-mcp.caddy\n' >> /etc/caddy/Caddyfile
  if ! caddy validate --config /etc/caddy/Caddyfile >&2; then cp -a /etc/caddy/Caddyfile.yieldcraft-backup /etc/caddy/Caddyfile; fail 'Caddy validation failed'; fi
  service caddy reload >&2; url="https://$domain/mcp";;
esac
printf 'MCP_CANDIDATE_URL=%s\n' "$url"
