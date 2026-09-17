#!/bin/sh
# Reference solution: the log goes to stderr, and the wrapper's banner with it.
set -eu
cat > /etc/metrics-mcp/config.json <<'JSON'
{"log_level": "debug", "log_to": "stderr"}
JSON
sed -i "s/^printf 'metrics-mcp 3.1 ready '$/printf 'metrics-mcp 3.1 ready\\\\n' >\&2/" /usr/local/bin/metrics-mcp
