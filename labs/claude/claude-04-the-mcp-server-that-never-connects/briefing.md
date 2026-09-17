# The MCP Server That Never Connects

Every morning `~/bin/support-digest` asks Claude Code to summarise the open support tickets. The
tickets come from the team's own MCP server, `/opt/tickets/tickets_mcp.py`, which the repository
`~/support-digest` declares in its `.mcp.json`. The server itself works — the platform team tests
it daily — and it wants the queue's API token in `TICKETS_TOKEN`. The token lives in
`~/.config/support-digest/env`, which the job reads.

For a week the digest has said there are no tickets, or that it has no way to see them. Someone
tried to fix it last Friday and committed what they had. The job's JSON result is
`~/digest.json`.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine that asks for the ticket list on every run;
Claude Code starts (or fails to start) the MCP server and calls it for real.

What is expected, and graded — the grader runs `~/bin/support-digest` itself:

1. The tickets server starts for the job, and its tools are offered to the model.
2. The job may call the tool that lists tickets.
3. The tool answers with the real queue, not an authorisation error.
4. The token is not in any file the repository tracks.

Leave `/opt/tickets` alone: the server is not the problem.
