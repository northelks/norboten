#!/usr/bin/env python3
"""tickets — the support queue as an MCP server, over stdio.

One tool, list_tickets. Authorised by TICKETS_TOKEN, which must equal the queue's API token.
Logs go to stderr; stdout carries JSON-RPC and nothing else.
"""

import json
import os
import sys

QUEUE = "/var/lib/tickets/queue.json"
TOKEN = "/etc/tickets/token"


def log(message):
    print(f"tickets: {message}", file=sys.stderr, flush=True)


def reply(message_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": message_id}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def list_tickets():
    with open(TOKEN) as f:
        expected = f.read().strip()
    if os.environ.get("TICKETS_TOKEN", "") != expected:
        shown = os.environ.get("TICKETS_TOKEN", "")[:14]
        log(f"refused a call: TICKETS_TOKEN is {shown!r}")
        return {
            "content": [{"type": "text", "text": "401 unauthorized: bad TICKETS_TOKEN"}],
            "isError": True,
        }
    with open(QUEUE) as f:
        tickets = [t for t in json.load(f) if t["status"] == "open"]
    lines = [f"{t['id']} [{t['priority']}] {t['title']}" for t in tickets]
    return {"content": [{"type": "text", "text": "\n".join(lines) or "no open tickets"}]}


def main():
    log("starting")
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        message_id, method = message.get("id"), message.get("method")
        if method == "initialize":
            version = message.get("params", {}).get("protocolVersion", "2025-06-18")
            reply(
                message_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "tickets", "version": "1.4.0"},
                },
            )
        elif method == "tools/list":
            reply(
                message_id,
                {
                    "tools": [
                        {
                            "name": "list_tickets",
                            "description": "List the open tickets in the support queue",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                },
            )
        elif method == "tools/call":
            name = message.get("params", {}).get("name")
            if name == "list_tickets":
                reply(message_id, list_tickets())
            else:
                reply(message_id, error={"code": -32602, "message": f"unknown tool {name}"})
        elif message_id is not None:
            reply(message_id, error={"code": -32601, "message": f"unknown method {method}"})


if __name__ == "__main__":
    main()
