# The Server That Talks Too Much

`~/bin/health-check` asks Claude Code, in `~/ops`, how loaded this machine is. It gets the numbers
from the `metrics` MCP server, which `~/ops/.mcp.json` starts with `/usr/local/bin/metrics-mcp`. The
server's settings are in `/etc/metrics-mcp/config.json`.

It worked until someone turned on debug logging to chase a slow answer, and tidied the start-up
script so the version shows. Since then the job says it has no way to see the machine's load. The
server itself runs fine when you start it by hand — it even prints its log for you. The job's JSON
result is `~/health.json`.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; it starts the MCP server for real.

What is expected, and graded:

1. The job connects to the server and `get_load` answers it.
2. Everything the server's command writes to stdout is a protocol message.
3. The server's debug log of each call is still written somewhere.
