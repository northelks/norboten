# The File Server That Shows Everything

The on-call team asks questions about its notes through `~/bin/ask-notes`: Claude Code, in
`~/notes-bot`, reads `~/notes` through the team's `files` MCP server, `/opt/mcp-files/files_mcp.py`.
The server's settings are in `/etc/mcp-files/config.json`.

A security review of last week's answers found that the assistant had quoted a line from a private
key and the alert webhook's secret. Neither belongs in `~/notes` — or so everyone thought.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; it starts the MCP server and calls it for
real. The job's last answer is `~/answer.json`.

What is expected, and graded — the grader runs `~/bin/ask-notes` with a model that asks for files
of its own choosing:

1. Every note in `~/notes`, including new ones, can still be listed and read — and none changed.
2. Nothing outside `~/notes` can be read through the server.
3. A link inside `~/notes` that points outside it does not open what it points to.
4. Hidden files in `~/notes` are neither listed nor read.

Leave the server's code alone: it does what its settings tell it to.
