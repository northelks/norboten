#!/bin/sh
set -eu
cat > /usr/local/bin/deploy-site <<'SCRIPT'
#!/bin/bash
# deploy-site <release.tar.gz> — unpack a release and make it the live site
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: deploy-site <release.tar.gz>" >&2
    exit 2
fi
tarball=$1
SITE_ROOT=${SITE_ROOT:-/srv/www}
if [ ! -f "$tarball" ]; then
    echo "deploy-site: $tarball: no such file" >&2
    exit 1
fi

mkdir -p "$SITE_ROOT/releases"
release=$(mktemp -d "$SITE_ROOT/releases/$(date +%Y%m%d%H%M%S).XXXXXX")
if ! tar -xzf "$tarball" -C "$release"; then
    rm -rf -- "$release"
    echo "deploy-site: cannot unpack $tarball; the live release is unchanged" >&2
    exit 1
fi
chmod 755 "$release"

# a new link beside the old one, renamed over it: current is never missing
ln -sfn "$release" "$SITE_ROOT/.current.new"
mv -Tf "$SITE_ROOT/.current.new" "$SITE_ROOT/current"
echo "deployed ${release##*/}"
SCRIPT
chmod 755 /usr/local/bin/deploy-site
