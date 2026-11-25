#!/usr/bin/env bash
# Remote fresh installer; invoked only by deploy.sh on the selected VPS.
set +x
set -Eeuo pipefail
umask 077
# Report only reserved stage exit codes to deploy.sh, not a raw transcript.
phase=42
trap 'if (($?)); then exit "$phase"; fi' EXIT
[[ $(id -u) = 0 && $# = 11 ]] || { echo 'root and 11 arguments required' >&2; exit 2; }
stage=$1 port=$2 proxy=$3 domain=$4 init=$5 repo=$6 ref=$7 email=$8 cf_config=$9 daemon=${10} auth=${11}
base=/opt/yieldcraft-mcp; etc=/etc/yieldcraft-mcp; state=/var/lib/yieldcraft-mcp; logs=/var/log/yieldcraft-mcp; user=yieldcraft-mcp
fail(){ echo "install: $*" >&2; exit 2; }
[[ $port =~ ^[1-9][0-9]{0,4}$ && $port -le 65535 && $ref =~ ^[a-f0-9]{40}$ && $repo =~ ^https://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]+\.git$ && $repo != *..* ]] || fail 'invalid deployment arguments'
[[ $domain == - || $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || fail 'invalid domain'
[[ $init == systemd || $init == sysvinit ]] || fail 'invalid service manager'; [[ $daemon == 0 || $daemon == 1 ]] || fail 'invalid daemon option'
[[ $auth == 0 || $auth == 1 ]] || fail 'invalid authentication option'
if ((auth)); then
 [[ -f $stage/tokens.json && ! -L $stage/tokens.json ]] || fail 'missing token records'
else
 [[ $daemon == 0 && ! -e $stage/tokens.json && ! -L $stage/tokens.json ]] || fail 'public demo cannot use daemon or token records'
fi
case $proxy in cloudflared|nginx|apache2|caddy) ;; *) fail 'unknown proxy';; esac
[[ $proxy == cloudflared || $domain != - ]] || fail 'domain required'
if [[ $proxy == nginx || $proxy == apache2 ]]; then [[ $email =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || fail 'Certbot email required'; fi
if [[ $proxy == cloudflared && $domain != - ]]; then [[ $cf_config =~ ^/[A-Za-z0-9_./-]+$ && $cf_config != *..* && -f $cf_config ]] || fail 'preprovisioned tunnel config required'; fi
[[ $(uname -m) == x86_64 ]] || fail 'supported target is Linux x86-64'
. /etc/os-release; [[ $ID == debian || $ID == ubuntu ]] || fail 'Debian/Ubuntu only'
phase=43
[[ ! -e $base && ! -e $etc && ! -e $state && ! -e $logs ]] || fail 'existing installation; refuse overwrite (see README)'
[[ ! -e /etc/systemd/system/yieldcraft-mcp.service && ! -e /etc/systemd/system/yieldcraft-tunnel.service && ! -e /etc/init.d/yieldcraft-mcp && ! -e /etc/init.d/yieldcraft-tunnel ]] || fail 'existing service definitions'
phase=42
if [[ $init == systemd ]]; then [[ -d /run/systemd/system ]] || fail 'systemd not active'; else command -v start-stop-daemon >/dev/null || fail 'SysV start-stop-daemon missing'; fi
phase=44
if [[ $proxy == cloudflared ]]; then command -v cloudflared >/dev/null || fail 'install cloudflared from the official trusted package repository on the VPS first'; fi
phase=45
export DEBIAN_FRONTEND=noninteractive
packages=(git build-essential cmake pkg-config perl python3 python3-venv python3-pip libcurl4-openssl-dev libssl-dev zlib1g-dev ca-certificates curl make iproute2)
if [[ $proxy == cloudflared && $domain != - ]]; then packages+=(python3-yaml); fi
apt-get update >&2; apt-get install -y --no-install-recommends "${packages[@]}" >&2
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
phase=42
if ss -Hln sport = ":$port" | grep -q .; then fail 'selected port already in use'; fi
phase=46
! id "$user" >/dev/null 2>&1 || fail 'service account already exists'
# A named tunnel operator may pre-create its group to grant read access
# without exposing credentials before the installer creates the user.
user_group=(--user-group)
if group=$(getent group "$user"); then
 [[ $proxy == cloudflared && $domain != - ]] || fail 'existing service group'
 IFS=: read -r group_name _ group_id group_members <<< "$group"
 [[ $group_name == "$user" && $group_id =~ ^[1-9][0-9]*$ && -z $group_members ]] || fail 'service group must be dedicated and empty'
 accounts=$(getent passwd) || fail 'could not check the service group'
 if awk -F: -v gid="$group_id" '$4 == gid { found=1 } END { exit !found }' <<< "$accounts"; then
  fail 'service group already used by another account'
 fi
 user_group=(--gid "$user")
fi
useradd --system "${user_group[@]}" --no-create-home --home-dir "$state" --shell /usr/sbin/nologin "$user"
install -d -m 0755 "$base"; install -d -m 0700 -o "$user" -g "$user" "$state" "$logs"; install -d -m 0750 -o root -g "$user" "$etc"
# Failure leaves diagnostic files; no existing deployment overwritten.
trap 'echo "Installation failed at line $LINENO; inspect $logs and see the README before retrying." >&2' ERR
install -d -m 0755 -o "$user" -g "$user" "$base/finpred" "$base/addon" "$base/venv"
cp -a "$stage/addon/." "$base/addon/"; chown -R "$user:$user" "$base/addon"
phase=47
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" init -q
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" remote add origin "$repo"
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" fetch --depth=1 origin "$ref" >&2
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" checkout --detach FETCH_HEAD >&2
[[ $(runuser -u "$user" -- git -C "$base/finpred" rev-parse HEAD) == "$ref" ]] || fail 'commit pin mismatch'
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred" submodule update --init third_party/mulib >&2
runuser -u "$user" -- env HOME="$state" git -C "$base/finpred/third_party/mulib" submodule update --init on1x/third_party/libstone >&2
phase=48
# Native source builds run without root and with private scratch paths.
runuser -u "$user" -- env HOME="$state" bash -c 'set -e; cd "$1"; make mulib; make; make dragnet; bin/yieldcraft-demand build; bin/yieldcraft-inventory build; bin/finpred selftest' _ "$base/finpred" >&2
phase=49
runuser -u "$user" -- env HOME="$state" python3 -m venv "$base/venv"
runuser -u "$user" -- env HOME="$state" "$base/venv/bin/pip" install --disable-pip-version-check "$base/addon" >&2
phase=50
# Runtime account must not modify executable code or operator config.
chown -R root:"$user" "$base"; chmod -R u+rwX,g+rX,go-w,o-rwx "$base"
if ((auth)); then
 state_dir="$state/projects"
 install -m 0600 -o "$user" -g "$user" "$stage/tokens.json" "$etc/tokens.json"
else
 state_dir="$state/public-demo"
fi
install -d -m 0700 -o "$user" -g "$user" "$state_dir"
cat > "$etc/config.toml" <<CFG
finpred_root = "$base/finpred"
state_dir = "$state_dir"
bind = "127.0.0.1"
port = $port
enable_live = false
allowed_hosts = []
offer_hosts = []
allow_llm = false
CFG
if ((auth)); then
 cat >> "$etc/config.toml" <<CFG
auth_required = true
token_file = "$etc/tokens.json"
daemon_config = "$base/finpred/plugins/dragnet/examples/Dragnet.json"
daemon_autostart = $( [[ $daemon == 1 ]] && echo true || echo false )
CFG
else
 printf 'auth_required = false\n' >> "$etc/config.toml"
fi
if [[ $domain != - ]]; then printf 'public_url = "https://%s/mcp"\n' "$domain" >> "$etc/config.toml"; fi
chown root:"$user" "$etc/config.toml"; chmod 0640 "$etc/config.toml"
cat > "$base/run-mcp" <<RUN
#!/bin/sh
umask 077
exec "$base/venv/bin/python" -m yieldcraft_mcp --config "$etc/config.toml"
RUN
chown root:"$user" "$base/run-mcp"; chmod 0750 "$base/run-mcp"
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
if [[ $proxy == cloudflared && $domain != - ]]; then
 phase=51
 (cd "$state"; runuser -u "$user" -- env HOME="$state" /usr/bin/python3 "$base/addon/deployment/tunnel_config.py" "$cf_config") ||
   fail 'provision private named tunnel config and credentials readable only by root and the service account'
fi
phase=50
install_service yieldcraft-mcp "$base/run-mcp"
for i in $(seq 1 30); do if curl -q --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:$port/readyz" >/dev/null; then break; fi; [[ $i != 30 ]] || fail 'MCP readiness failed'; sleep 2; done
phase=51
case $proxy in
 cloudflared)
  cf=$(command -v cloudflared); [[ $cf =~ ^/[A-Za-z0-9_./-]+$ ]] || fail 'unexpected cloudflared executable path'
  if [[ $domain == - ]]; then
   cat > "$base/run-tunnel" <<RUN
#!/bin/sh
umask 077
exec "$cf" tunnel --no-autoupdate --url "http://127.0.0.1:$port" --loglevel info --transport-loglevel info --logfile "$logs/cloudflared.log"
RUN
  else
   cat > "$base/run-tunnel" <<RUN
#!/bin/sh
umask 077
exec "$cf" tunnel --no-autoupdate --config "$cf_config" --loglevel info --transport-loglevel info --logfile "$logs/cloudflared.log" run
RUN
  fi
   chown root:"$user" "$base/run-tunnel"; chmod 0750 "$base/run-tunnel"; install_service yieldcraft-tunnel "$base/run-tunnel"
   if [[ $domain == - ]]; then
    phase=52
    url=''; for i in $(seq 1 60); do url=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$logs/cloudflared.log" 2>/dev/null | tail -1 || true); [[ -z $url ]] || break; sleep 2; done
   [[ -n $url ]] || fail 'Quick Tunnel did not publish an endpoint'; url+=/mcp
  else url="https://$domain/mcp"; fi;;
 nginx)
   apt-get install -y nginx certbot python3-certbot-nginx >&2
   site=/etc/nginx/sites-available/yieldcraft-mcp
   enabled=/etc/nginx/sites-enabled/yieldcraft-mcp
   [[ ! -e $site && ! -L $site && ! -e $enabled && ! -L $enabled ]] || fail 'nginx site already exists'
   # Certificate provisioning must not publish a cleartext MCP backend.
   cat > "$site" <<NGINX
 server {
  listen 80;
  server_name $domain;
  access_log off;
  location / { return 404; }
 }
NGINX
   chmod 0644 "$site"; ln -s "$site" "$enabled"
   nginx -t >&2; service nginx reload >&2
   certbot certonly --nginx --non-interactive --agree-tos --email "$email" -d "$domain" --cert-name "$domain" --deploy-hook 'service nginx reload' >&2
   cat > "$site" <<NGINX
 server {
  listen 80;
  server_name $domain;
  access_log off;
  location / { return 308 https://$domain\$request_uri; }
 }
 server {
  listen 443 ssl;
  server_name $domain;
  ssl_protocols TLSv1.2 TLSv1.3;
  ssl_certificate /etc/letsencrypt/live/$domain/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;
  access_log off;
  error_log /var/log/nginx/yieldcraft-mcp-error.log warn;
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
   nginx -t >&2; service nginx reload >&2; url="https://$domain/mcp";;
 apache2)
   apt-get install -y apache2 certbot python3-certbot-apache >&2
   site=/etc/apache2/sites-available/yieldcraft-mcp.conf
   enabled=/etc/apache2/sites-enabled/yieldcraft-mcp.conf
   [[ ! -e $site && ! -L $site && ! -e $enabled && ! -L $enabled ]] || fail 'Apache site exists'
   a2enmod proxy proxy_http ssl headers >&2
   cat > "$site" <<APACHE
 <VirtualHost *:80>
  ServerName $domain
  CustomLog /dev/null common
 </VirtualHost>
APACHE
   chmod 0644 "$site"; a2ensite yieldcraft-mcp >&2; apache2ctl configtest >&2; service apache2 reload >&2
   certbot certonly --apache --non-interactive --agree-tos --email "$email" -d "$domain" --cert-name "$domain" --deploy-hook 'service apache2 reload' >&2
   cat > "$site" <<APACHE
 <VirtualHost *:80>
  ServerName $domain
  CustomLog /dev/null common
  RedirectMatch 308 "^/(?!\\.well-known/acme-challenge/)(.*)\$" "https://$domain/\$1"
 </VirtualHost>
 <VirtualHost *:443>
  ServerName $domain
  SSLEngine On
  SSLProtocol -all +TLSv1.2 +TLSv1.3
  SSLCertificateFile /etc/letsencrypt/live/$domain/fullchain.pem
  SSLCertificateKeyFile /etc/letsencrypt/live/$domain/privkey.pem
  CustomLog /dev/null common
  LogLevel warn
  ProxyPreserveHost On
 ProxyRequests Off
 ProxyTimeout 1000
 LimitRequestBody 33554432
 ProxyPass / http://127.0.0.1:$port/ retry=0
 ProxyPassReverse / http://127.0.0.1:$port/
</VirtualHost>
APACHE
   apache2ctl configtest >&2; service apache2 reload >&2; url="https://$domain/mcp";;
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
