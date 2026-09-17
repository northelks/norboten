---
title: The Stream That Stops — a proxy in front of a remote MCP server
topics: [mcp, networking]
minutes: 30
---

A remote MCP server speaks Streamable HTTP: every message is a POST, and the answer is either one JSON
body or, for anything that takes a while, a stream of server-sent events — progress notifications as
the work goes, then the result. Put a reverse proxy in front of it and the proxy decides how that
stream travels. nginx's defaults are made for pages, not streams: it collects the upstream's answer in
buffers before passing it on, and it gives up on an upstream that stays silent for longer than its read
timeout. Either one alone ruins a long tool call. This lab had both, and a server that could be reached
around the proxy as well.

## What you should be able to do after this

- Describe how a Streamable HTTP server answers a long tool call, and what a client does meanwhile.
- Say what `proxy_buffering` and `proxy_read_timeout` do to an event stream, and measure it.
- Tell a proxy that cut a response apart from a server that failed.
- Keep a proxied server reachable through its proxy only, and check it from outside.
- Explain what a client-side tool timeout protects, and why it is no fix for a proxy.

## The mechanism

### A long answer is a stream

The reports server answers `build_report` with `Content-Type: text/event-stream`: one `data:` line per
event, a progress notification every three seconds, the result after nine. The first bytes leave at
once — the status line and the first event — so a client knows the call is alive long before it is done.
That is the point of streaming, and the thing a proxy can take away.

### Buffering

With `proxy_buffering on` (nginx's default), nginx reads the upstream response into memory and sends it
to the client in large pieces — for a response that is never large, only when it ends. The client sees
nothing for nine seconds and then everything at once: no progress, and no sign of life to tell a slow
call from a hung one. `proxy_buffering off` passes each piece on as it arrives. (An upstream can ask for
the same per response with an `X-Accel-Buffering: no` header; this server does not send one.)

### The read timeout

`proxy_read_timeout` is the longest nginx waits *between two reads* from the upstream, not for the whole
response. Here it was two seconds and the server writes every three, so nginx closes the connection
after the first gap — the error log says `upstream timed out … while reading upstream` — and the client
gets a response with a status line and no result. The value has to exceed the longest silence a tool
can have: the gap between progress events, or the whole call when a server sends none.

### What the client does about it

A Streamable HTTP client that loses a stream before its result can wait, or try to resume it. Claude
Code 2.1.270 waited, and the job hung until something killed it; the job now sets `MCP_TOOL_TIMEOUT`
(milliseconds) so a call that has gone quiet fails after twenty seconds. That bounds the damage; it is
not the fix. The fix is a proxy that passes the stream through.

### One way in

A proxy in front of a server is where access is logged, rate-limited and, eventually, encrypted. A
server that also listens on every address makes all of that optional: anyone who can reach the machine
can go around it. The server binds `127.0.0.1`, and only nginx — on the same machine — can reach it.

## A failure, walked through

Replayed on the lab's container (Ubuntu 26.04, nginx from Ubuntu's archive, Claude Code 2.1.270; the
site trimmed to its location block, the settings on one line). The proxy's site and the server's
settings:

```console
$ cat /etc/nginx/conf.d/reports.conf; cat /etc/reports-mcp/config.json
    location /mcp {
        proxy_pass http://127.0.0.1:8931;
        proxy_set_header Host $host;
        proxy_read_timeout 2s;
        proxy_buffering on;
    }
{"bind": "0.0.0.0", "port": 8931, "step_seconds": 3}
```

A small client that posts `tools/call build_report` and prints each line as it arrives, with the time.
Straight to the server:

```text
  0.0s  HTTP/1.0 200 OK
  0.0s  data: {"jsonrpc": "2.0", "method": "notifications/progress", ...
  3.0s  data: {"jsonrpc": "2.0", "method": "notifications/progress", ...
  6.0s  data: {"jsonrpc": "2.0", "method": "notifications/progress", ...
  9.0s  data: {"jsonrpc": "2.0", "id": 7, "result": {"content": [{"type": "text", "text": "Weekly report W42-6c00: 3 i
  9.0s  (connection closed)
```

Through nginx on `:8080`, one setting at a time, nginx restarted from scratch for each:

```text
== proxy_buffering on; proxy_read_timeout 2s
  2.0s  HTTP/1.1 200 OK
  2.0s  (connection closed)
== proxy_buffering on; proxy_read_timeout 300s
  9.0s  HTTP/1.1 200 OK
  9.0s  data: … progress   (×3, all at once)
  9.0s  data: … result
  9.0s  (connection closed)
== proxy_buffering off; proxy_read_timeout 2s
  0.0s  HTTP/1.1 200 OK
  0.0s  data: … progress
  2.0s  (connection closed)
== proxy_buffering off; proxy_read_timeout 300s
  0.0s  HTTP/1.1 200 OK
  0.0s  data: … progress
  3.0s  data: … progress
  6.0s  data: … progress
  9.0s  data: … result
  9.0s  (connection closed)
```

and nginx's error log for the first: `upstream timed out (110: Connection timed out) while reading
upstream`. The job, with the broken proxy and then the fixed one:

```text
21s  build_report: MCP server "reports" tool "build_report" timed out after 20s
10s  build_report: Weekly report W42-6c00: 3 incidents, 2 changes, 0 open.
```

The way around the proxy, before and after `"bind": "127.0.0.1"` and `sudo reports-mcp restart`:

```console
$ ss -Hltn "sport = :8931"; hostname -I
LISTEN 0      5      0.0.0.0:8931 0.0.0.0:*
172.17.0.6
$ curl -s -o /dev/null -w "%{http_code}\n" -X POST … http://172.17.0.6:8931/mcp
200
$ ss -Hltn "sport = :8931"
LISTEN 0      5      127.0.0.1:8931 0.0.0.0:*
$ curl -s -o /dev/null -w "%{http_code}\n" -X POST -d "{}" http://172.17.0.6:8931/mcp
000
```

## Common wrong turns

- **Pointing `.mcp.json` at `:8931`.** The report arrives; the proxy, its log and everything it will do
  are bypassed. The grader measures through `:8080`.
- **Raising the timeout and keeping the buffer.** The report arrives after nine seconds, in one lump, with
  no progress — the second measurement above.
- **Turning the buffer off and keeping two seconds.** One event, then the cut.
- **Raising `MCP_TOOL_TIMEOUT`.** The client waits longer for a stream the proxy has already closed.

## Cheat sheet

```text
nginx -t && nginx -s reload                         # here: sudo proxy-restart
proxy_buffering off;                                # pass the stream on as it arrives
proxy_read_timeout 300s;                            # longest silence between two reads
proxy_http_version 1.1; proxy_set_header Connection "";
sudo tail /var/log/nginx/error.log                  # "upstream timed out … while reading upstream"
ss -Hltn "sport = :8931"                            # who listens, on which address
curl -N -X POST -H 'Accept: application/json, text/event-stream' …    # -N: do not buffer either
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The Model Context Protocol* (topic journal `mcp`) — Transports

Manual pages: `man 8 ss`.

Documentation:

- https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- https://html.spec.whatwg.org/multipage/server-sent-events.html

The whole subject, end to end: the topic journals *The Model Context Protocol* (`mcp`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. How does a Streamable HTTP server answer a tool call that takes a while?

   > With a server-sent event stream: progress notifications as it goes, then the JSON-RPC result, all on
   > the response to that POST.

2. What does `proxy_buffering on` do to that stream in nginx?

   > nginx collects the response and sends it on in large pieces — for a short stream, only at the end — so
   > the client gets no progress until the call is over.

3. `proxy_read_timeout` is 60 seconds and a tool call takes five minutes. When is that a problem?

   > Only if the upstream is ever silent for more than 60 seconds; the timeout is between reads, so
   > progress events every few seconds keep the connection alive.

4. Why is setting a client tool timeout not a fix here?

   > It makes a lost stream fail sooner instead of hanging, but the proxy still cuts or holds back every
   > long call.

5. Why must the server listen on loopback when it sits behind a proxy on the same machine?

   > Otherwise clients can reach it directly and bypass the proxy's logging, limits and TLS.
