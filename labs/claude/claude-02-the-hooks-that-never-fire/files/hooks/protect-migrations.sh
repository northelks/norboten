#!/bin/sh
# PreToolUse (Edit|Write): a migration that exists has run against production. Add a new one.
file=$(jq -r '.tool_input.file_path // ""')
case "$file" in
    "$CLAUDE_PROJECT_DIR"/migrations/*)
        if [ -e "$file" ]; then
            echo "Blocked: $file has already been applied; write a new migration instead." >&2
            exit 2
        fi
        ;;
esac
exit 0
