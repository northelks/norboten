---
title: The Server That Talks Too Much — on stdio, stdout belongs to the protocol
topics: [mcp, logging-journald]
minutes: 20
---

A stdio MCP server has two output streams and they are not interchangeable. The client reads stdout as
the protocol — newline-delimited JSON-RPC, one message per line — and nothing else may appear there.
stderr is the server's own: the client may log it, show it, or drop it, but never parses it. Print a
greeting to stdout, or log to it, and the server may work perfectly by hand while the client cannot
understand a word. This lab's server did both.

## What you should be able to do after this

- Say what a stdio MCP client reads from stdout and from stderr.
- Find everything that writes to a server's stdout: the server, its logging, and whatever starts it.
- Explain why one stray line can break the handshake while another merely wastes the client's time.
- Move a server's diagnostics off stdout without losing them.
- Check a server's stdout line by line, without a client.

## The mechanism

### Framing: one message per line

The stdio transport frames messages by newline. The client reads a line, parses it as JSON, and expects
a JSON-RPC message: a response to something it sent, a request, or a notification. The specification
says a server must not write anything to stdout that is not a valid message. How a client treats a line
that breaks the rule is up to the client: Claude Code 2.1.270, as the walkthrough shows, skips a line
that is not JSON — but it cannot recover a message that shares its line with something else.

### Two polluters, two effects

The wrapper `/usr/local/bin/metrics-mcp` prints `metrics-mcp 3.1 ready ` — without a newline — before
it hands over to Python. The first thing the server writes is its answer to `initialize`, so the answer
becomes `metrics-mcp 3.1 ready {"jsonrpc": …}`: one line that is not JSON. The client never sees the
answer to its first request, waits, and gives up. That is fatal.

The debug log (`"log_to": "stdout"`) writes a line after every reply. Each is a line of its own, so a
tolerant client skips them and carries on: harmless to Claude Code today, a protocol violation all the
same, noise in every exchange, and fatal to a stricter client — or to this one if a log line is ever
written without its newline.

### Where diagnostics should go

stderr, or a file. Claude Code keeps a stdio server's stderr for its debug output; a file survives
restarts and can be rotated. The one wrong answer is `log_level: off`: the log was turned on to chase a
slow answer, and whoever turned it on still needs it.

### Wrappers are part of the server

Whatever `.mcp.json` names as the command is the server, as far as the client is concerned: a shell
wrapper, `npx`, `uvx`, a `docker run`. Anything any of them prints to stdout reaches the client. Package
managers that announce what they install are a classic source; a wrapper's `echo` is another.

## A failure, walked through

Replayed on the lab's container (Ubuntu 26.04, Claude Code 2.1.270; JSON files shown on one line).
The command the project runs, the wrapper, and the server's settings:

```console
$ cat ~/ops/.mcp.json; cat /usr/local/bin/metrics-mcp; cat /etc/metrics-mcp/config.json
{"mcpServers": {"metrics": {"type": "stdio", "command": "/usr/local/bin/metrics-mcp"}}}
#!/bin/sh
# Start the metrics MCP server. Kept as a wrapper so the version shows when it starts.
printf 'metrics-mcp 3.1 ready '
exec python3 /opt/metrics-mcp/metrics_mcp.py "$@"
{"log_level": "debug", "log_to": "stdout"}
```

The server by hand, stderr thrown away — so this is exactly what a client reads:

```console
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | /usr/local/bin/metrics-mcp 2>/dev/null
metrics-mcp 3.1 ready {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", ...}}
18:57:49 DEBUG metrics: handled initialize (id 1), pid 90
{"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "get_load", ...}]}}
18:57:49 DEBUG metrics: handled tools/list (id 2), pid 90
```

It works, to a person. The job, with a model that asks for `get_load`, sees:

```text
mcp tools offered: []
get_load: <tool_use_error>Error: No such tool available: mcp__metrics__get_load. The MCP server
'metrics' is still connecting. Call WaitForMcpServers to wait for it, then try again.</tool_use_error>
```

Send the banner to stderr (`printf 'metrics-mcp 3.1 ready\n' >&2`) and nothing else, and the job
connects — the debug lines are still on stdout, and Claude Code skips them:

```text
mcp tools offered: ['mcp__metrics__get_load']
get_load: load 2.46 2.38 2.28; disk / 55% used; cpus 8
```

```console
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | /usr/local/bin/metrics-mcp 2>/dev/null
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", ...}}
18:58:07 DEBUG metrics: handled initialize (id 1), pid 164
```

Then `"log_to": "stderr"`: stdout carries the protocol and nothing else, and the log is where it
belongs:

```console
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | /usr/local/bin/metrics-mcp 2>/tmp/err.txt
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", ...}}
$ cat /tmp/err.txt
metrics-mcp 3.1 ready
18:58:07 DEBUG metrics: handled initialize (id 1), pid 178
```

## Common wrong turns

- **Fixing the banner and stopping.** The job connects, which looks like done; stdout still carries a
  log line per message, and the next client, or the next missing newline, breaks again.
- **`log_level: off`.** Quiet stdout, and the diagnostics someone switched on deliberately are gone.
- **Testing the server with stderr and stdout mixed on the terminal.** Everything looks fine because a
  person skips the noise. Throw stderr away (`2>/dev/null`) to see what a client sees.
- **Blaming Claude Code's timeout.** Waiting longer for an answer that was mangled on the wire changes
  nothing.
- **Changing `.mcp.json` to run the Python file directly.** It drops the banner, and the log on stdout
  stays; and the wrapper was there for a reason someone will restore.

## Cheat sheet

```text
<command> 2>/dev/null < requests.jsonl          # stdout exactly as the client reads it
<command> 2>&1 >/dev/null < requests.jsonl      # only what went to stderr
python3 -c 'import json,sys; [json.loads(l) for l in sys.stdin]'   # fails on the first bad line
printf '...' >&2                                # a wrapper's messages, on stderr
claude --debug                                  # Claude Code's own view of MCP start-up
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The Model Context Protocol* (topic journal `mcp`) — Transports

Manual pages: `man 3 stdout`.

Documentation:

- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports

The whole subject, end to end: the topic journals *The Model Context Protocol* (`mcp`), *The log lines that were never written down* (`logging-journald`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. What may a stdio MCP server write to stdout?

   > Only JSON-RPC messages, one per line; everything else — logs, banners, progress — belongs on stderr
   > or in a file.

2. Why did the banner stop the connection while the log lines did not?

   > The banner had no newline, so it shared a line with the answer to `initialize` and that answer was
   > lost; each log line was a line of its own, which Claude Code skips.

3. After moving the banner to stderr the job works. Why is the lab not finished?

   > The log still writes to stdout, which breaks the protocol for stricter clients and on the next
   > missing newline; stdout must carry only protocol messages.

4. Why is turning logging off the wrong fix?

   > It removes the diagnostics someone needs, and hides the real problem instead of fixing where the
   > output goes.

5. How do you see exactly what a client receives from a stdio server?

   > Run its command with JSON-RPC requests on stdin and stderr redirected away; every remaining line
   > must parse as a JSON-RPC message.
