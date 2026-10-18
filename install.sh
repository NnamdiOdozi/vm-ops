#!/usr/bin/env bash
# Install or update vm-ops on this VM. Idempotent: rerun after every `git pull`.
# The clone is made as your login user (root has no GitHub key); see README "Install".
#   cd /opt/vm-ops && git pull && sudo bash install.sh
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
ETC_DIR=/etc/vm-ops
STATE_DIR=/var/lib/vm-ops
UNITS=(vm-disk-alert.service vm-disk-alert.timer)

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
python3 -c 'import tomllib' || { echo "Needs Python 3.11+ (tomllib)."; exit 1; }

install -d -m 755 "$ETC_DIR"
install -d -m 700 "$STATE_DIR"
# Copy settings on first install only, so edits made on this machine survive updates.
[ -f "$ETC_DIR/config.toml" ] || install -m 644 "$INSTALL_DIR/config.toml" "$ETC_DIR/config.toml"
# A setting added to the repo later is missing here until copied across: show the difference.
if ! diff -u "$ETC_DIR/config.toml" "$INSTALL_DIR/config.toml"; then
    echo "WARNING: $ETC_DIR/config.toml differs from the repo (above). Add any new settings to it,"
    echo "or, if you never edited it: sudo cp $INSTALL_DIR/config.toml $ETC_DIR/config.toml"
fi

for unit in "${UNITS[@]}"; do
    sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$INSTALL_DIR/systemd/$unit" > "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [ ! -f "$ETC_DIR/smtp.env" ]; then
    echo "Next: create $ETC_DIR/smtp.env with SMTP_USER and SMTP_PASSWORD (see README), then rerun."
    echo "The timer is NOT enabled yet, because without credentials every alert would fail."
    exit 0
fi
chmod 600 "$ETC_DIR/smtp.env"
systemctl enable --now vm-disk-alert.timer
echo "Installed. Check: systemctl list-timers vm-disk-alert.timer; journalctl -u vm-disk-alert -n 20"
