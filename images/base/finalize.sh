#!/bin/sh
# Last step of a golden image build. Runs as root, detached from the SSH session that started it,
# then powers the machine off. Leaves nothing of the build behind: no build user, no logs, no
# host keys, no cloud-init state — the next boot is a brand-new instance.
set -u
build_user="$1"
sleep 2

pkill -KILL -u "$build_user" 2>/dev/null
sleep 1
userdel -r "$build_user" 2>/dev/null || deluser --remove-home "$build_user" 2>/dev/null
rm -f /etc/sudoers.d/90-cloud-init-users

dnf clean all >/dev/null 2>&1
apt-get clean >/dev/null 2>&1
rm -rf /var/cache/apk/*

cloud-init clean --logs --seed >/dev/null 2>&1
rm -f /etc/ssh/ssh_host_*
[ -f /etc/machine-id ] && : > /etc/machine-id
rm -f /var/lib/dbus/machine-id

rm -rf /var/log/journal/*
find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null
rm -f /root/.bash_history /root/.ash_history
rm -rf /tmp/* /var/tmp/* 2>/dev/null

fstrim -a >/dev/null 2>&1
sync
poweroff || poweroff -f
