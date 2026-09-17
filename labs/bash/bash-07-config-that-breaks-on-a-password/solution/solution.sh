#!/bin/sh
set -eu
cat > /usr/local/bin/render-config <<'SCRIPT'
#!/bin/bash
# render-config — fill the application's configuration template from its values
set -euo pipefail

TEMPLATE=${RENDER_TEMPLATE:-/etc/myapp/app.conf.tmpl}
VALUES=${RENDER_VALUES:-/etc/myapp/secrets.env}
OUT=${RENDER_OUT:-/etc/myapp/app.conf}

unset DB_HOST DB_PASSWORD
. "$VALUES"
: "${DB_HOST:?DB_HOST is not set in $VALUES}"
: "${DB_PASSWORD:?DB_PASSWORD is not set in $VALUES}"

text=$(<"$TEMPLATE")
# a quoted replacement is literal: no /, &, \ or $ in a value means anything here
text=${text//@DB_HOST@/"$DB_HOST"}
text=${text//@DB_PASSWORD@/"$DB_PASSWORD"}

umask 077   # the file with the password is private from the moment it exists
tmp=$(mktemp "$OUT.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
printf '%s\n' "$text" > "$tmp"
chmod 600 "$tmp"
mv -f -- "$tmp" "$OUT"
trap - EXIT
echo "rendered $OUT"
SCRIPT
chmod 755 /usr/local/bin/render-config
systemctl restart myapp.service
