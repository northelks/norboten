# The Token for Someone Else

The weekly fleet report, `~/bin/inventory-report`, has Claude Code, in `~/inventory-report`, ask
the `inventory` MCP server at `http://127.0.0.1:8931/mcp` for the host list. The server wants a
bearer token signed by this machine's identity provider, `lab-idp`; the job reads its token from
`~/.config/inventory/env`. The server's settings are in `/etc/inventory-mcp/config.json`, and
`sudo inventory-mcp restart` makes it read them again.

The report works. An audit found out why: the job's token is a copy of the billing sync's, and the
inventory server takes it — along with any other token the provider ever signed, expired or not.
One leaked token opens every service that trusts the provider.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine; it connects to the server and calls it for
real. The job's JSON result is `~/inventory-report.json`.

What is expected, and graded — the grader mints tokens of its own with `lab-idp`:

1. A token issued for another service is refused.
2. A token past its expiry is refused.
3. The job runs on a token issued for the inventory server, and gets the host list.
