#!/bin/sh
# PostToolUse: re-indent any Python file the agent touched with four spaces instead of tabs.
file="$1"
case "$file" in
    *.py) expand -i -t 4 "$file" > "$file.tidy" && cat "$file.tidy" > "$file" && rm -f "$file.tidy" ;;
esac
exit 0
