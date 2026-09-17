#!/usr/bin/env python3
"""reports — builds the weekly report as a remote MCP server: Streamable HTTP.

POST /mcp. initialize and tools/list answer with JSON. tools/call build_report takes a while, so it
answers with a server-sent event stream: a progress notification as each step finishes, then the
result. Settings, read at start (`sudo reports-mcp restart`), in /etc/reports-mcp/config.json:

  bind, port    where it listens
  step_seconds  how long each of the three steps takes
"""

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = "/etc/reports-mcp/config.json"
STEPS = ("collecting", "summarising", "formatting")

logging.basicConfig(
    filename="/var/log/reports-mcp.log", level=logging.INFO, format="%(asctime)s %(message)s"
)
log = logging.getLogger("reports")


class Handler(BaseHTTPRequestHandler):
    server_version = "reports-mcp/2.0"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _json(self, status, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._json(405, {"error": "use POST"})

    do_DELETE = do_GET

    def _event(self, message):
        self.wfile.write(f"event: message\ndata: {json.dumps(message)}\n\n".encode())
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "not JSON"})
            return
        method, message_id = message.get("method", ""), message.get("id")
        params = message.get("params") or {}
        if message_id is None:
            self._json(202)
            return
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "reports", "version": "2.0.0"},
            }
            self._json(200, {"jsonrpc": "2.0", "id": message_id, "result": result})
        elif method == "tools/list":
            tool = {
                "name": "build_report",
                "description": "Build the weekly operations report (takes a while)",
                "inputSchema": {"type": "object", "properties": {}},
            }
            self._json(200, {"jsonrpc": "2.0", "id": message_id, "result": {"tools": [tool]}})
        elif method == "tools/call" and params.get("name") == "build_report":
            self._build(message_id, params)
        else:
            error = {"code": -32601, "message": f"unknown method {method}"}
            self._json(200, {"jsonrpc": "2.0", "id": message_id, "error": error})

    def _build(self, message_id, params):
        token = (params.get("_meta") or {}).get("progressToken", f"report-{message_id}")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        started = time.monotonic()
        for i, step in enumerate(STEPS, 1):
            progress = {
                "progressToken": token,
                "progress": i - 1,
                "total": len(STEPS),
                "message": step,
            }
            self._event({"jsonrpc": "2.0", "method": "notifications/progress", "params": progress})
            time.sleep(self.server.step_seconds)
        report = f"Weekly report {self.server.report_id}: 3 incidents, 2 changes, 0 open."
        self._event(
            {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {"content": [{"type": "text", "text": report}]},
            }
        )
        log.info("report built in %.1fs", time.monotonic() - started)


def main():
    with open(CONFIG) as f:
        conf = json.load(f)
    server = ThreadingHTTPServer(
        (conf.get("bind", "127.0.0.1"), int(conf.get("port", 8931))), Handler
    )
    server.step_seconds = float(conf.get("step_seconds", 3))
    with open("/var/lib/reports/id") as f:
        server.report_id = f.read().strip()
    log.info("listening on %s:%s", conf.get("bind"), conf.get("port"))
    server.serve_forever()


if __name__ == "__main__":
    main()
