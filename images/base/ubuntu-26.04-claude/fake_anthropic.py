"""A stand-in for the Anthropic Messages API that answers from a script: Claude Code runs for free.

Point Claude Code at it with `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` and any
`ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`). Every model turn Claude Code asks for is the
next step of the script:

    [{"text": "I will look first.", "tool": "Read", "input": {"file_path": "README.md"}},
     {"tool": "StructuredOutput", "input": {"label": "bug"}},
     {"text": "Done."}]

A step with `tool` ends its turn with that tool call, and Claude Code carries it out — for real,
under its real permission rules and hooks — before asking for the next turn. The last step repeats
if Claude Code asks for more. A run with `--tools ""` sends no tools, and still takes a step.

    python3 fake_anthropic.py --port 18555 --script steps.json [--log requests.jsonl]

Control endpoints, for a rehearsal that drives several runs through one server:
`POST /_script` replaces the script (a JSON list) and resets it, `GET /_requests` returns what was
asked so far, `POST /_reset` clears both. Standard library only: it also runs inside lab images.
"""

from __future__ import annotations

import argparse
import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Script:
    def __init__(self, steps: list[dict] | None = None) -> None:
        self.lock = threading.Lock()
        self.load(steps or [{"text": "ok"}])

    def load(self, steps: list[dict]) -> None:
        with self.lock:
            self.steps, self.position, self.requests = list(steps) or [{"text": "ok"}], 0, []

    def next_step(self) -> dict:
        with self.lock:
            step = self.steps[min(self.position, len(self.steps) - 1)]
            self.position += 1
            return step


_ids = itertools.count(1)


def message(step: dict, model: str) -> dict:
    content = []
    if step.get("text"):
        content.append({"type": "text", "text": step["text"]})
    if step.get("tool"):
        content.append(
            {
                "type": "tool_use",
                "id": f"toolu_fake_{next(_ids):06d}",
                "name": step["tool"],
                "input": step.get("input", {}),
            }
        )
    if not content:
        content.append({"type": "text", "text": ""})
    return {
        "id": f"msg_fake_{next(_ids):06d}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "tool_use" if step.get("tool") else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(step.get("input_tokens", 100)),
            "output_tokens": int(step.get("output_tokens", 20)),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }


def make_handler(script: Script, log: Path | None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send_json(self, payload, status: int = 200) -> None:
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/_requests":
                with script.lock:
                    return self._send_json(script.requests)
            self._send_json({"type": "error", "error": {"type": "not_found_error"}}, 404)

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if self.path == "/_script":
                script.load(body)
                return self._send_json({"steps": len(script.steps)})
            if self.path == "/_reset":
                script.load([])
                return self._send_json({"reset": True})
            if "count_tokens" in self.path:
                return self._send_json({"input_tokens": 100})
            if not self.path.startswith("/v1/messages"):
                return self._send_json({"type": "error", "error": {"type": "not_found_error"}}, 404)

            tools = [t.get("name") for t in body.get("tools", [])]
            step = script.next_step()
            record = {
                "model": body.get("model"),
                "tools": tools,
                "system": body.get("system"),
                "messages": body.get("messages", []),
                "answered": step,
                "auth": "bearer" if self.headers.get("authorization") else "api-key",
                "bytes": length,
            }
            with script.lock:
                script.requests.append(record)
            if log:
                with log.open("a") as f:
                    f.write(json.dumps(record) + "\n")

            reply = message(step, body.get("model", "claude-fake"))
            if not body.get("stream"):
                return self._send_json(reply)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            self._stream(reply)

        def _stream(self, reply: dict) -> None:
            def event(kind: str, data: dict) -> None:
                self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())

            start = {**reply, "content": [], "stop_reason": None}
            event("message_start", {"type": "message_start", "message": start})
            for i, block in enumerate(reply["content"]):
                if block["type"] == "text":
                    opening = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": block["text"]}
                else:
                    opening = {**block, "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
                event(
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": opening},
                )
                event(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": i, "delta": delta},
                )
                event("content_block_stop", {"type": "content_block_stop", "index": i})
            event(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": reply["stop_reason"], "stop_sequence": None},
                    "usage": {"output_tokens": reply["usage"]["output_tokens"]},
                },
            )
            event("message_stop", {"type": "message_stop"})

    return Handler


def serve(port: int, steps: list[dict] | None = None, log: Path | None = None):
    """Start in a thread; returns (server, script). Port 0 picks a free one."""
    script = Script(steps)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(script, log))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, script


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18555)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--script", type=Path)
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    steps = json.loads(args.script.read_text()) if args.script else None
    script = Script(steps)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(script, args.log))
    print(f"fake Anthropic API on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
