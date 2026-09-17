"""One stand-in for everything else a job talks to: GitHub's REST API, Discord, Telegram, and the
Norboten API's public telemetry. It records every request and answers just enough.

    GITHUB_API_URL=http://127.0.0.1:<port>/github
    DISCORD_WEBHOOK=http://127.0.0.1:<port>/discord
    TELEGRAM_API_URL=http://127.0.0.1:<port>/telegram
    NORBOTEN_API=http://127.0.0.1:<port>/norboten

What it answers from is its state, set with `POST /_state` (merged): `issues` (open issues, for
search), `jobs` (the jobs of any Actions run), `stuck_points`. `GET /_requests` returns the
record, `POST /_reset` clears record and state.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.data: dict = {"issues": [], "jobs": [], "stuck_points": []}
        self.requests: list[dict] = []
        self.next_number = 100


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, payload, status: int = 200) -> None:
            raw = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self, method: str) -> None:
            url = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            length = int(self.headers.get("content-length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw.strip() else None
            path = url.path

            if path == "/_requests":
                with state.lock:
                    return self._send(state.requests)
            if path == "/_state" and method == "POST":
                with state.lock:
                    state.data.update(body or {})
                return self._send(state.data)
            if path == "/_reset":
                with state.lock:
                    state.reset()
                return self._send({"reset": True})

            with state.lock:
                state.requests.append(
                    {
                        "method": method,
                        "path": path,
                        "query": query,
                        "body": body,
                        "auth": self.headers.get("authorization", ""),
                    }
                )
                return self._route(method, path, query, body)

        def _route(self, method: str, path: str, query: dict, body) -> None:
            data = state.data
            if path.startswith("/discord"):
                return self._send(None, 204)
            if m := re.match(r"^/telegram/bot[^/]+/sendMessage$", path):
                return self._send({"ok": True, "result": {"message_id": len(state.requests)}})
            if path == "/norboten/telemetry/stuck-points":
                return self._send(data["stuck_points"])
            if path == "/github/search/issues":
                wanted = re.search(r'in:title "(.*)"', query.get("q", ""))
                title = (wanted.group(1) if wanted else "").lower()
                items = [i for i in data["issues"] if title in i["title"].lower()]
                return self._send({"total_count": len(items), "items": items})
            if m := re.match(r"^/github/repos/[^/]+/[^/]+/(.*)$", path):
                rest = m.group(1)
                if rest == "issues" and method == "POST":
                    state.next_number += 1
                    issue = {**body, "number": state.next_number, "state": "open"}
                    issue["html_url"] = f"https://github.example/issues/{issue['number']}"
                    data["issues"].append(issue)
                    return self._send(issue, 201)
                if re.match(r"^issues/\d+/labels$", rest):
                    return self._send([{"name": n} for n in body.get("labels", [])])
                if re.match(r"^issues/\d+/comments$", rest):
                    return self._send({"id": len(state.requests), "body": body.get("body")}, 201)
                if re.match(r"^actions/runs/\d+/jobs$", rest):
                    return self._send({"total_count": len(data["jobs"]), "jobs": data["jobs"]})
                if rest == "pulls" and method == "POST":
                    state.next_number += 1
                    n = state.next_number
                    return self._send(
                        {**body, "number": n, "html_url": f"https://github.example/pull/{n}"}, 201
                    )
            return self._send({"message": "Not Found"}, 404)

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def do_PUT(self) -> None:
            self._handle("PUT")

    return Handler


def serve(port: int = 0):
    """Start in a thread; returns (server, state). Port 0 picks a free one."""
    state = State()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"sink on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(State())).serve_forever()
