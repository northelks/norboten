#!/usr/bin/env python3
"""docs — the team handbook as an MCP server, over stdio: one tool, search.

    docs_mcp.py --edition N     serve edition N of the handbook, /srv/handbook/edition-N.json

It needs DOCS_API_KEY in its environment, equal to the handbook service's key in
/etc/docs-mcp/key: without it every search is refused. Logs go to stderr.
"""

import argparse
import json
import os
import sys


def log(message):
    print(f"docs: {message}", file=sys.stderr, flush=True)


def reply(message_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": message_id}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def search(edition, query):
    with open("/etc/docs-mcp/key") as f:
        if os.environ.get("DOCS_API_KEY", "") != f.read().strip():
            log("refused: DOCS_API_KEY is missing or wrong")
            return {"content": [{"type": "text", "text": "403: bad DOCS_API_KEY"}], "isError": True}
    with open(f"/srv/handbook/edition-{edition}.json") as f:
        pages = json.load(f)
    words = [w for w in query.lower().split() if w]
    hits = [p for p in pages if any(w in (p["title"] + " " + p["text"]).lower() for w in words)]
    lines = [f"[handbook edition {edition}] {p['title']}: {p['text']}" for p in hits[:3]]
    return {"content": [{"type": "text", "text": "\n".join(lines) or "no matches"}]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", type=int, default=3)
    edition = parser.parse_args().edition
    log(f"serving edition {edition}")
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        message_id, method = message.get("id"), message.get("method")
        params = message.get("params") or {}
        if method == "initialize":
            reply(
                message_id,
                {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "docs", "version": f"edition-{edition}"},
                },
            )
        elif method == "tools/list":
            schema = {"type": "object", "properties": {"query": {"type": "string"}}}
            reply(
                message_id,
                {
                    "tools": [
                        {
                            "name": "search",
                            "description": "Search the team handbook",
                            "inputSchema": schema,
                        }
                    ]
                },
            )
        elif method == "tools/call" and params.get("name") == "search":
            reply(
                message_id, search(edition, str((params.get("arguments") or {}).get("query", "")))
            )
        elif message_id is not None:
            reply(message_id, error={"code": -32601, "message": f"unknown method {method}"})


if __name__ == "__main__":
    main()
