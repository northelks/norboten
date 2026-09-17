#!/bin/sh
# Reference solution: the agent file where Claude Code looks for project subagents, with the
# `description` key it requires, a read-only tool list and Haiku.
set -eu
R=/home/learner/payments/.claude
mkdir -p "$R/agents"
sed -e 's/^desc: /description: /' \
    -e 's/^model: opus$/model: haiku\ntools: Read, Grep, Glob/' \
    "$R/agent/security-reviewer.md" > "$R/agents/security-reviewer.md"
rm -r "$R/agent"
chown -R learner:learner "$R"
