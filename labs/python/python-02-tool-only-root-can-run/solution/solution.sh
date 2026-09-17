#!/bin/sh
set -eu
VENV=/opt/netprobe/venv
mkdir -p /opt/netprobe
rm -rf /opt/netprobe/src
cp -r /root/src/netprobe /opt/netprobe/src
"$VENV/bin/pip" uninstall --yes --quiet netprobe
"$VENV/bin/pip" install --quiet --no-index --find-links /opt/wheels /opt/netprobe/src
chmod 755 "$VENV"
chmod -R a+rX /opt/netprobe
ln -sfn "$VENV/bin/netprobe" /usr/local/bin/netprobe
