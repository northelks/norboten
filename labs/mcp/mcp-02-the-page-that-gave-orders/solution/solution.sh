#!/bin/sh
# Reference solution: the server fetches the docs site only, strips hidden text and labels what it
# returns; the job allows the one MCP tool and Write, and nothing else, instead of bypassing checks.
set -eu
cat > /etc/mcp-web/config.json <<'JSON'
{
  "allowed_hosts": ["docs.example"],
  "strip_hidden": true,
  "label_untrusted": true
}
JSON
sed -i 's|    --permission-mode bypassPermissions \\|    --permission-mode dontAsk --allowedTools "mcp__web__fetch_page,Write" \\|' \
    /home/learner/bin/release-notes
