# The Answers From Last Year

`~/bin/ask-handbook` answers questions from the team handbook: Claude Code, in `~/handbook-bot`,
searches it through the `docs` MCP server that the repository's `.mcp.json` declares — edition 3,
the current one. The server needs the handbook service's key, which the job reads from
`~/.config/handbook/env`.

People keep getting last year's answers: credentials rotated yearly by whoever is on call, deploys
encouraged on Friday afternoons. The `.mcp.json` in the repository is right; everyone has checked.
While they were looking, someone also noticed the service key sitting in that same file, committed.
The job's JSON result is `~/handbook.json`.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; it starts the MCP server for real.

What is expected, and graded:

1. The job's answers come from edition 3 of the handbook.
2. The repository's `.mcp.json` is the only place a `docs` server is defined for this project.
3. The key is in no tracked file and not in the latest commit — and the server still gets it.
