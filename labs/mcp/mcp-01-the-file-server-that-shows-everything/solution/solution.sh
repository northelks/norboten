#!/bin/sh
# Reference solution: share the notes folder only, read-only; check links where they lead; hide
# dotfiles.
set -eu
cat > /etc/mcp-files/config.json <<'JSON'
{
  "roots": ["/home/learner/notes"],
  "follow_symlinks": false,
  "show_hidden": false,
  "read_only": true
}
JSON
