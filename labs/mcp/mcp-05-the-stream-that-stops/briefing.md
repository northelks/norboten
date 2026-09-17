# The Stream That Stops

`~/bin/weekly-report` has Claude Code, in `~/ops-report`, ask the `reports` MCP server to build the
week's operations report. The server (`/opt/reports-mcp/reports_mcp.py`, settings in
`/etc/reports-mcp/config.json`, `sudo reports-mcp restart`) is published through nginx on
`http://127.0.0.1:8080/mcp`; nginx's site is `/etc/nginx/conf.d/reports.conf`, and
`sudo proxy-restart` tests and reloads it. Building a report takes a few seconds, and the server
reports progress as it goes.

Since the proxy went in front of it, the job says the reports tool failed. Asked directly on its
own port, the server builds the report every time. The job's JSON result is `~/weekly-report.json`.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; it calls the server through the proxy for
real.

What is expected, and graded:

1. The job gets the report, through the proxy.
2. Through the proxy, progress reaches the client as each step finishes, not all at the end.
3. The server can be reached only through the proxy — every client's traffic is logged there.
