#!/bin/sh
# Prints one label for the issue in $GITHUB_EVENT_PATH. Run by .github/workflows/claude-triage.yml.
set -eu
out="${RUNNER_TEMP:-/tmp}/triage.json"
jq -r '"Title: \(.issue.title)\n\n\(.issue.body // "")"' "$GITHUB_EVENT_PATH" |
    claude -p "Label this GitHub issue as bug, question or lab-request. Look around the repository first if it helps." \
        --model opus \
        --dangerously-skip-permissions \
        --output-format json > "$out"
jq -r '.result' "$out"
