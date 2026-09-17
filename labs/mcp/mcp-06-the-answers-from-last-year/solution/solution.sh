#!/bin/sh
# Reference solution: remove the local-scope docs server left from testing the archive, and let the
# project's .mcp.json take the key from the job's environment instead of holding it.
set -eu
R=/home/learner/handbook-bot
runuser -u learner -- sh -c "cd $R && HOME=/home/learner /opt/claude/claude mcp remove docs -s local" >/dev/null
cat > "$R/.mcp.json" <<'JSON'
{
  "mcpServers": {
    "docs": {
      "type": "stdio",
      "command": "python3",
      "args": ["/opt/docs-mcp/docs_mcp.py", "--edition", "3"],
      "env": {"DOCS_API_KEY": "${DOCS_API_KEY}"}
    }
  }
}
JSON
chown learner:learner "$R/.mcp.json"
cd "$R"
runuser -u learner -- git add .mcp.json
runuser -u learner -- git commit -qm "docs: take the key from the environment"
