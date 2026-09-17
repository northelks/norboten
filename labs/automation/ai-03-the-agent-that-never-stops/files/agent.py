#!/usr/bin/env python3
"""inbox-agent — answers the support inbox with a model and a few tools.

Every message file in $INBOX is one conversation: the model is asked to answer it and may call the
tools listed in $AGENT_TOOLS. A reply the model writes goes to $OUTBOX; the message moves to done/.
The model is any OpenAI-compatible chat endpoint ($MODEL_URL) — the local Ollama in production.

    AGENT_TOOLS   comma-separated: read_message, write_reply, run_shell
    MAX_STEPS     model calls allowed per message; 0 means no limit
"""

import json
import os
import pathlib
import subprocess
import sys
import urllib.request

MODEL_URL = os.environ.get("MODEL_URL", "http://127.0.0.1:11434/v1/chat/completions")
MODEL = os.environ.get("MODEL", "qwen2.5:0.5b")
TOOLS = [
    t.strip()
    for t in os.environ.get("AGENT_TOOLS", "read_message,write_reply").split(",")
    if t.strip()
]
MAX_STEPS = int(os.environ.get("MAX_STEPS", "0"))
STATE = pathlib.Path(os.environ.get("STATE_DIRECTORY", "/var/lib/inbox-agent"))
INBOX, OUTBOX, DONE = STATE / "inbox", STATE / "outbox", STATE / "done"

SPECS = {
    "read_message": {
        "description": "Read a message from the inbox",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
    "write_reply": {
        "description": "Write the reply to a message",
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["id", "text"],
        },
    },
    "run_shell": {
        "description": "Run a shell command on the server and return its output",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}


def log(text):
    print(text, flush=True)


def call_model(messages):
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": [
            {"type": "function", "function": {"name": t, **SPECS[t]}} for t in TOOLS if t in SPECS
        ],
    }
    request = urllib.request.Request(
        MODEL_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)["choices"][0]["message"]


def run_tool(name, args):
    if name not in TOOLS:
        return f"error: the tool {name} is not available"
    if name == "read_message":
        path = INBOX / pathlib.Path(args.get("id", "")).name
        return path.read_text() if path.is_file() else "error: no such message"
    if name == "write_reply":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        (OUTBOX / (pathlib.Path(args.get("id", "reply")).name + ".txt")).write_text(
            args.get("text", "")
        )
        return "reply saved"
    if name == "run_shell":
        done = subprocess.run(
            args.get("command", ""), shell=True, capture_output=True, text=True, timeout=30
        )
        return (done.stdout + done.stderr)[-2000:]
    return f"error: unknown tool {name}"


def answer(message):
    messages = [
        {"role": "system", "content": "You answer customer support messages politely and briefly."},
        {"role": "user", "content": f"Answer the message with id {message.name}."},
    ]
    steps = 0
    while True:
        if MAX_STEPS and steps >= MAX_STEPS:
            log(f"{message.name}: stopped after {steps} model calls (MAX_STEPS)")
            return
        steps += 1
        reply = call_model(messages)
        messages.append(reply)
        calls = reply.get("tool_calls") or []
        if not calls:
            log(f"{message.name}: finished after {steps} model calls")
            return
        for call in calls:
            name = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            result = run_tool(name, args)
            refused = " (refused: not an allowed tool)" if name not in TOOLS else ""
            log(f"{message.name}: tool {name} {json.dumps(args)}{refused}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                }
            )


def main():
    for directory in (INBOX, OUTBOX, DONE):
        directory.mkdir(parents=True, exist_ok=True)
    messages = sorted(p for p in INBOX.iterdir() if p.is_file())
    limit = MAX_STEPS or "none"
    log(f"{len(messages)} message(s) in the inbox; tools: {', '.join(TOOLS)}; max steps: {limit}")
    for message in messages:
        try:
            answer(message)
        except OSError as e:
            log(f"{message.name}: model unreachable: {e}")
            return 1
        message.rename(DONE / message.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
