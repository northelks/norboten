#!/bin/sh
# Reference solution: restore the drafts from git; run the job in dontAsk mode with only the tools
# it needs and edits allowed in docs/ alone; deny the token file; drop the user-level bypass.
set -eu
L=learner
H=/home/learner
cd "$H/handbook"
runuser -u "$L" -- git restore --source=HEAD --staged --worktree -- drafts

cat > "$H/bin/tidy-handbook" <<'JOB'
#!/bin/sh
# Nightly handbook tidy-up (crontab: 30 2 * * *). Fixes typos in docs/ and nothing else.
cd "$HOME/handbook" || exit 1
claude -p "Fix the typos in docs/." \
    --permission-mode dontAsk \
    --tools "Read,Edit,Glob,Grep" \
    --allowedTools "Edit(./docs/**)" \
    --max-turns 10 \
    --output-format json > "$HOME/tidy-handbook.log" 2>&1
JOB

mkdir -p "$H/handbook/.claude"
cat > "$H/handbook/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "deny": ["Read(./.env)", "Read(./.env.*)", "Edit(./drafts/**)"]
  }
}
JSON
printf '{}\n' > "$H/.claude/settings.json"
chown -R "$L:$L" "$H/bin" "$H/.claude" "$H/handbook/.claude"
