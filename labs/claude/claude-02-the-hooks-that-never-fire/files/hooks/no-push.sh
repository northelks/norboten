#!/bin/sh
# PreToolUse (Bash): agents open pull requests; they do not push.
command=$(jq -r '.tool_input.command // ""')
if printf '%s\n' "$command" | grep -Eq '(^|[^[:alnum:]_])git([[:space:]].*)?[[:space:]]push([[:space:]]|$)'; then
    echo "Blocked: agents do not push. Commit locally and leave the push to a person."
    exit 1
fi
exit 0
