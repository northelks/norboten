#!/bin/sh
set -eu
cat > /usr/local/bin/prune-releases <<'SCRIPT'
#!/bin/bash
# prune-releases — keep the newest $KEEP releases (by the timestamp in their names), delete the rest
set -euo pipefail

RELEASES_DIR=${RELEASES_DIR:-/srv/app/releases}
KEEP=${KEEP:-5}

cd -- "$RELEASES_DIR"

releases=()
for entry in [0-9]*; do
    # release directories only: not current, not files, not a glob that matched nothing
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
        releases+=("$entry")
    fi
done

# glob results are sorted by name, and the names start with a timestamp: newest last
count=${#releases[@]}
if (( count > KEEP )); then
    for old in "${releases[@]:0:count-KEEP}"; do
        rm -rf -- "./$old"
    done
fi
SCRIPT
chmod 755 /usr/local/bin/prune-releases
mkdir -p /etc/systemd/system/prune-releases.service.d
cat > /etc/systemd/system/prune-releases.service.d/path.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/usr/local/bin/prune-releases
UNIT
systemctl daemon-reload
systemctl enable --now prune-releases.timer
