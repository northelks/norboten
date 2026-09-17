#!/bin/sh
set -eu
cat > /usr/local/bin/export-orders <<'SCRIPT'
#!/bin/bash
# export-orders — the day's order files as one compressed CSV for the warehouse
set -euo pipefail

SRC=${EXPORT_SRC:-/srv/orders}
DEST=${EXPORT_DEST:-/srv/exports}
name=orders-$(date +%F).csv.gz

# a private work file, and a partial export under a name the importer does not match
work=$(mktemp)
part=$(mktemp "$DEST/.orders.XXXXXX")
cleanup() { rm -f -- "$work" "$part"; }
# bash runs the EXIT trap on success, on failure and when a signal such as SIGTERM kills it
trap cleanup EXIT

echo "id,sku,qty" > "$work"
for f in "$SRC"/*.csv; do
    tail -n +2 -- "$f" >> "$work"
done
gzip -c "$work" > "$part"
chmod 644 "$part"
mv -f -- "$part" "$DEST/$name"   # the only step the importer can see, and it is atomic
echo "exported to $DEST/$name"
SCRIPT
chmod 755 /usr/local/bin/export-orders
rm -f /tmp/export.tmp
