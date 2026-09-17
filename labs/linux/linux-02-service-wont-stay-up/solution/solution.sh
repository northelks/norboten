#!/bin/sh
set -eu
# 1. the service user must be able to read its config
chown root:notes /etc/notes/notes.ini
chmod 0640 /etc/notes/notes.ini
# 2. free the port from the retired unit
systemctl disable --now notes-legacy
# 3. allow the real data directory, keep the profile enforcing
sed -i 's#/var/lib/notes/#/srv/notes/#' /etc/apparmor.d/usr.local.bin.notes-app
apparmor_parser -r /etc/apparmor.d/usr.local.bin.notes-app
# 4. restart on failure, start at boot
mkdir -p /etc/systemd/system/notes.service.d
printf '[Service]\nRestart=on-failure\n' > /etc/systemd/system/notes.service.d/restart.conf
systemctl daemon-reload
systemctl enable --now notes
