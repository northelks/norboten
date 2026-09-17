#!/bin/sh
# Reference solution: .mcp.json runs python3 and passes the job's TICKETS_TOKEN through; the local
# settings file leaves git and is ignored; the job allows the tool by its real name.
set -eu
R=/home/learner/support-digest
cat > "$R/.mcp.json" <<'JSON'
{
  "mcpServers": {
    "tickets": {
      "type": "stdio",
      "command": "python3",
      "args": ["/opt/tickets/tickets_mcp.py"],
      "env": {"TICKETS_TOKEN": "${TICKETS_TOKEN}"}
    }
  }
}
JSON
rm -f "$R/.claude/settings.local.json"
printf '.claude/settings.local.json\n' >> "$R/.gitignore"
sed -i 's/mcp__ticket__list_tickets/mcp__tickets__list_tickets/' /home/learner/bin/support-digest
chown -R learner:learner "$R"
cd "$R"
runuser -u learner -- git add -A
runuser -u learner -- git commit -qm "Start the tickets server with python3; no token in the repository"
