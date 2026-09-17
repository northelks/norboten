#!/bin/sh
# Reference solution: the matcher in the tools' own case, tidy.sh reading the hook's JSON, no-push
# exiting 2 with its reason on stderr, protect-migrations executable; then put the applied migration
# back with a new commit, pushed by a person.
set -eu
R=/home/learner/billing
H="$R/.claude/hooks"
sed -i 's/"matcher": "edit|write"/"matcher": "Edit|Write"/' "$R/.claude/settings.json"

cat > "$H/tidy.sh" <<'HOOK'
#!/bin/sh
# PostToolUse (Edit|Write): re-indent any Python file the agent touched with four spaces.
file=$(jq -r '.tool_input.file_path // ""')
case "$file" in
    *.py) [ -f "$file" ] && expand -i -t 4 "$file" > "$file.tidy" && cat "$file.tidy" > "$file" && rm -f "$file.tidy" ;;
esac
exit 0
HOOK

sed -i 's/^    echo "Blocked: agents do not push\(.*\)"$/    echo "Blocked: agents do not push\1" >\&2/; s/^    exit 1$/    exit 2/' "$H/no-push.sh"
chmod 755 "$H/tidy.sh" "$H/no-push.sh" "$H/protect-migrations.sh"
chown -R learner:learner "$R/.claude"

cd "$R"
M=migrations/0002_add_due_date.sql
applied=$(runuser -u learner -- git log --reverse --format=%h -- "$M" | head -n 1)
runuser -u learner -- git restore --source="$applied" --staged --worktree -- "$M"
runuser -u learner -- git commit -qm "Restore migration 0002 as applied in production"
runuser -u learner -- git push -q origin main
