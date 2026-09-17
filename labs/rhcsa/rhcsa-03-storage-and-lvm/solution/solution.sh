#!/bin/sh
set -eu
uuid=$(blkid -s UUID -o value /dev/vg0/applv)
sed -i "s|^/dev/vdb1 |UUID=$uuid |" /etc/fstab
systemctl daemon-reload
vgextend vg0 /dev/vdc
lvextend -r -l +100%FREE vg0/applv
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap defaults 0 0' >> /etc/fstab
swapon -a
systemctl restart app-spooler
