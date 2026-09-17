#!/bin/sh
# Reference solution: the server checks the audience and the expiry; the job gets a token minted
# for the inventory server instead of the billing API's.
set -eu
cat > /etc/inventory-mcp/config.json <<'JSON'
{
  "issuer": "https://idp.lab",
  "audience": "http://127.0.0.1:8931/mcp",
  "verify_exp": true,
  "bind": "127.0.0.1",
  "port": 8931
}
JSON
inventory-mcp restart
token=$(lab-idp mint --audience http://127.0.0.1:8931/mcp --subject inventory-report)
printf 'INVENTORY_TOKEN=%s\n' "$token" > /home/learner/.config/inventory/env
chown learner:learner /home/learner/.config/inventory/env
chmod 600 /home/learner/.config/inventory/env
