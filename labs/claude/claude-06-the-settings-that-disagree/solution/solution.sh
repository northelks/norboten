#!/bin/sh
# Reference solution: the policy where Claude Code reads managed settings on Linux, readable by the
# users it governs; the personal override out of git and ignored; the import spelled as the file is.
set -eu
R=/home/learner/platform
mkdir -p /etc/claude-code
mv /etc/claude/managed-settings.json /etc/claude-code/managed-settings.json
rmdir /etc/claude 2>/dev/null || true
chown root:root /etc/claude-code/managed-settings.json
chmod 644 /etc/claude-code/managed-settings.json

cd "$R"
runuser -u learner -- git rm -q --cached .claude/settings.local.json
rm .claude/settings.local.json
printf '.claude/settings.local.json\nCLAUDE.local.md\n' >> .gitignore
sed -i 's|^@docs/conventions.md$|@docs/CONVENTIONS.md|' CLAUDE.md
chown learner:learner .gitignore CLAUDE.md
runuser -u learner -- git add -A
runuser -u learner -- git commit -qm "Personal settings out of git; import the conventions by their real name"
