#!/usr/bin/env python3
"""A scripted stand-in for an OpenAI-compatible chat endpoint, for the lab's grader and walkthrough.

POST /v1/chat/completions answers with the next step of the script: {"tool": name, "arguments": {}}
becomes a tool call, {"text": "..."} a plain answer; the last step repeats. POST /_script replaces
the script, GET /_requests lists what was asked, POST /_reset rewinds it. --script loads a first
script. Standard library only.
"""

import argparse
import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
state = {"steps": [{"text": "Thank you for your message."}], "position": 0, "requests": []}
ids = itertools.count(1)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/_requests":
            with lock:
                return self.send(state["requests"])
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        with lock:
            if self.path == "/_script":
                state.update(steps=body or [{"text": "ok"}], position=0, requests=[])
                return self.send({"steps": len(state["steps"])})
            if self.path == "/_reset":
                state.update(position=0, requests=[])
                return self.send({"reset": True})
            if not self.path.endswith("/chat/completions"):
                return self.send({"error": "not found"}, 404)
            step = state["steps"][min(state["position"], len(state["steps"]) - 1)]
            state["position"] += 1
            state["requests"].append(
                {
                    "tools": [t["function"]["name"] for t in body.get("tools", [])],
                    "messages": len(body.get("messages", [])),
                }
            )
        message = {"role": "assistant", "content": step.get("text", "")}
        if step.get("tool"):
            message["tool_calls"] = [
                {
                    "id": f"call_{next(ids)}",
                    "type": "function",
                    "function": {
                        "name": step["tool"],
                        "arguments": json.dumps(step.get("arguments", {})),
                    },
                }
            ]
        self.send(
            {
                "id": f"chatcmpl-{next(ids)}",
                "object": "chat.completion",
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if step.get("tool") else "stop",
                    }
                ],
            }
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11500)
    parser.add_argument("--script", help="a JSON file with the steps to start with")
    args = parser.parse_args()
    if args.script:
        try:
            with open(args.script) as f:
                state["steps"] = json.load(f) or state["steps"]
        except (OSError, ValueError):
            pass
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
