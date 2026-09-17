#!/bin/sh
set -eu
systemctl unmask config-sync.service
rm -f /etc/systemd/system/inventory-api.service.d/override.conf
mkdir -p /etc/systemd/system/inventory-api.service.d
printf '[Unit]\nWants=config-sync.service\n' > /etc/systemd/system/inventory-api.service.d/deps.conf
systemctl daemon-reload
systemctl set-default multi-user.target
systemctl enable --now inventory-api
