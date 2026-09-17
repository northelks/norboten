#!/bin/sh
# Reference solution, run as root. A learner does task 1 from rd.break at the GRUB console
# (and must touch /.autorelabel there); the gate has root already, so it sets the password
# directly and restores the labels.
set -eu
echo 'root:Rhcsa-Lab5!' | chpasswd
restorecon /etc/shadow /etc/passwd /etc/group /etc/gshadow

uuid=$(blkid -s UUID -o value /dev/vdb)
sed -i "s|^UUID=[^ ]* /data |UUID=$uuid /data |" /etc/fstab
systemctl daemon-reload
mountpoint -q /data || mount /data

cat > /etc/yum.repos.d/lab-local.repo <<'REPO'
[lab-local]
name=Lab packages
baseurl=file:///opt/repos/local
enabled=1
gpgcheck=0
REPO
dnf -y -q install tree

cat > /usr/local/bin/sysreport <<'SCRIPT'
#!/bin/bash
report() {
    echo "hostname: $(hostname -s)"
    echo "kernel: $(uname -r)"
    echo "root_free: $(df --output=pcent / | tail -1 | tr -dc '0-9' | awk '{print 100-$1}')%"
}
case "${1:-}" in
    "") report ;;
    -o) [ -n "${2:-}" ] || { echo "sysreport: -o needs a file" >&2; exit 2; }
        report > "$2" ;;
    *)  echo "sysreport: unknown option: $1" >&2; exit 2 ;;
esac
SCRIPT
chmod 755 /usr/local/bin/sysreport
sed -i 's/^OnCalender=/OnCalendar=/' /etc/systemd/system/sysreport.timer
systemctl daemon-reload
systemctl enable --now sysreport.timer

groupadd -g 5000 auditors
useradd -u 5001 -G auditors maria
useradd -u 5002 -G auditors -s /sbin/nologin sam
chage -M 90 maria

sed -i -E 's/^(server|pool)[[:space:]]/# &/' /etc/chrony.conf
echo 'server 192.168.5.2 iburst' >> /etc/chrony.conf
systemctl enable chronyd
systemctl restart chronyd

rm -f /etc/systemd/journald.conf.d/99-retention.conf
mkdir -p /var/log/journal
systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl --flush

su - maria -c 'ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 &&
    cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'

mkdir -p /srv/audit
chgrp auditors /srv/audit
chmod 2770 /srv/audit

usermod -aG wheel "$NORBOTEN_LEARNER"
