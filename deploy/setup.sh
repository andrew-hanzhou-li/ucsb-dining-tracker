#!/bin/bash
# One-time setup for a fresh Ubuntu 24.04 VPS.
# Run it from the folder you copied up, as root:
#     bash deploy/setup.sh yourname.duckdns.org
# Safe to run again after you change the code: it updates files and restarts.
set -e

DOMAIN="$1"
if [ -z "$DOMAIN" ]; then
    echo "Usage: bash deploy/setup.sh yourname.duckdns.org"
    exit 1
fi
cd "$(dirname "$0")/.."      # the folder with main.py in it

echo "== Installing packages =="
apt-get update
apt-get install -y python3-venv caddy ufw

echo "== Clock: meal hours are Santa Barbara time, not UTC =="
timedatectl set-timezone America/Los_Angeles

echo "== Firewall: allow SSH and web traffic only =="
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw --force enable

echo "== App user and files =="
id dining >/dev/null 2>&1 || useradd --system --home /opt/dining --shell /usr/sbin/nologin dining
mkdir -p /opt/dining
cp main.py index.html requirements.txt /opt/dining/

echo "== Python libraries =="
[ -d /opt/dining/venv ] || python3 -m venv /opt/dining/venv
/opt/dining/venv/bin/pip install -r /opt/dining/requirements.txt

echo "== Database: /var/lib/dining, apart from the code =="
# Stop the app here, after the slow pip step, so it is down only for the
# database move and the restart below (nothing to stop the first time)
systemctl stop dining 2>/dev/null || true
mkdir -p /var/lib/dining
if [ -f /opt/dining/dining.db ]; then
    if [ -e /var/lib/dining/dining.db ]; then
        echo "Both /opt/dining/dining.db and /var/lib/dining/dining.db exist."
        echo "Keeping /var/lib/dining/dining.db; the old file is left where it is."
    else
        # Move SQLite's side files too, or the newest events could be lost
        for f in dining.db dining.db-journal dining.db-wal dining.db-shm; do
            if [ -e "/opt/dining/$f" ]; then
                mv "/opt/dining/$f" /var/lib/dining/
            fi
        done
        echo "Moved the database from /opt/dining to /var/lib/dining"
    fi
fi
chown -R dining:dining /var/lib/dining
chmod 750 /var/lib/dining
# Only now, with the database out: the code belongs to root and the app can
# only read it, so if the app is ever broken into it can't rewrite itself.
# (Older setups gave /opt/dining to the app user.)
chown -R root:root /opt/dining
chmod -R u=rwX,go=rX /opt/dining

echo "== Secret API key =="
if [ ! -f /etc/dining.env ]; then
    # umask: the file is never readable by other users, not even for a moment
    (umask 077 && echo "DINING_API_KEY=$(openssl rand -hex 24)" > /etc/dining.env)
    chmod 600 /etc/dining.env
fi

echo "== Start the app =="
cp deploy/dining.service /etc/systemd/system/dining.service
systemctl daemon-reload
systemctl enable dining
systemctl restart dining

echo "== HTTPS with Caddy =="
# Other sites can share this server, so never replace the whole file once
# it's in use: only add this app's block, and only if it isn't there yet.
CADDYFILE=/etc/caddy/Caddyfile
SITE_BLOCK="$DOMAIN {
    reverse_proxy 127.0.0.1:8000
}"
if grep -qF "$DOMAIN {" "$CADDYFILE"; then
    echo "$DOMAIN is already in the Caddyfile; leaving it as it is"
elif grep -qF "/usr/share/caddy" "$CADDYFILE"; then
    # Fresh install: this is Caddy's sample page, which would take over port 80
    echo "$SITE_BLOCK" > "$CADDYFILE"
else
    printf '\n%s\n' "$SITE_BLOCK" >> "$CADDYFILE"
fi
systemctl reload caddy || systemctl restart caddy

echo
echo "Done. Open https://$DOMAIN (the certificate can take a minute the first time)."
echo "Your devices' API key is in /etc/dining.env:"
cat /etc/dining.env
