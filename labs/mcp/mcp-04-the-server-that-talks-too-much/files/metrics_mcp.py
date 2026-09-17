#!/usr/bin/env python3
"""metrics — this machine's load and disk, as an MCP server over stdio.

On stdio, stdout is the protocol: every line the client reads there must be one JSON-RPC message.
Where this server's own log goes is decided by /etc/metrics-mcp/config.json:

  log_level  debug | info | off
  log_to     stdout | stderr | file   (file: /var/log/metrics-mcp.log)
"""

import json
import os
import shutil
import sys
import time

CONFIG = "/etc/metrics-mcp/config.json"
LOG_FILE = "/var/log/metrics-mcp.log"
LEVELS = {"debug": 10, "info": 20, "off": 100}


def config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CONF = config()


def log(level, message):
    if LEVELS.get(level, 20) < LEVELS.get(CONF.get("log_level", "info"), 20):
        return
    line = f"{time.strftime('%H:%M:%S')} {level.upper():5} metrics: {message}"
    where = CONF.get("log_to", "stderr")
    if where == "stdout":
        print(line, flush=True)
    elif where == "file":
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    else:
        print(line, file=sys.stderr, flush=True)


def reply(message_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": message_id}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def get_load():
    one, five, fifteen = os.getloadavg()
    disk = shutil.disk_usage("/")
    text = (
        f"load {one:.2f} {five:.2f} {fifteen:.2f}; "
        f"disk / {disk.used * 100 // disk.total}% used; cpus {os.cpu_count()}"
    )
    return {"content": [{"type": "text", "text": text}]}


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            log("info", f"ignored a line that is not JSON: {line.strip()[:80]}")
            continue
        message_id, method = message.get("id"), message.get("method")
        params = message.get("params") or {}
        if method == "initialize":
            reply(
                message_id,
                {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "metrics", "version": "3.1.0"},
                },
            )
        elif method == "tools/list":
            tool = {
                "name": "get_load",
                "description": "This machine's load averages, disk use and CPU count",
                "inputSchema": {"type": "object", "properties": {}},
            }
            reply(message_id, {"tools": [tool]})
        elif method == "tools/call" and params.get("name") == "get_load":
            reply(message_id, get_load())
            log("debug", "get_load called")
        elif message_id is not None:
            reply(message_id, error={"code": -32601, "message": f"unknown method {method}"})
        log("debug", f"handled {method} (id {message_id}), pid {os.getpid()}")


if __name__ == "__main__":
    main()
