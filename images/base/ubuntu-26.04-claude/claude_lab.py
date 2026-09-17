"""Run the real Claude Code against a scripted model — for the claude track's checks and learners.

Nothing here reaches Anthropic. `fake_anthropic.py` answers every model turn from a script, and
Claude Code carries out the tool calls in it for real, under the permission rules, hooks,
subagents and MCP servers the machine is configured with. A check scripts the model to attempt
something (delete a directory, read a secret, call an MCP tool) and grades what Claude Code
actually did: the files left behind, the tool results it sent back, the tools it offered.

    import sys; sys.path.insert(0, "/usr/local/lib/norboten")
    import claude_lab

    run = claude_lab.run([{"tool": "Bash", "input": {"command": "rm -rf data"}}, {"text": "done"}],
                         cwd="/home/learner/project")
    run.result["permission_denials"], run.requests[0]["tools"]

Standard library only, like the runner that imports it.
"""

from __future__ import annotations

import json
import os
import pwd
import shlex
import subprocess
from dataclasses import dataclass, field

import fake_anthropic

CLAUDE = "/opt/claude/claude"
OFFLINE_KEY = "sk-norboten-offline"


def offline_env(base_url: str) -> dict[str, str]:
    """What makes Claude Code talk to the scripted model and nothing else."""
    return {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_API_KEY": OFFLINE_KEY,
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }


@dataclass
class Run:
    code: int
    out: str
    err: str
    result: dict = field(default_factory=dict)
    requests: list[dict] = field(default_factory=list)

    @property
    def denials(self) -> list[dict]:
        return self.result.get("permission_denials") or []

    def tools_offered(self, turn: int = 0) -> list[str]:
        return self.requests[turn]["tools"] if len(self.requests) > turn else []

    def sent_text(self) -> str:
        """Everything Claude Code sent the model: the system prompt, messages and tool results."""
        return "\n".join(json.dumps([r["system"], r["messages"]]) for r in self.requests)

    def tool_results(self) -> list[str]:
        """The text of every tool result Claude Code sent back, in order."""
        found: dict[str, str] = {}
        for r in self.requests:
            for message in r["messages"]:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    inner = block.get("content")
                    if isinstance(inner, list):
                        inner = "".join(b.get("text", "") for b in inner if isinstance(b, dict))
                    # each request repeats the history: one entry per tool call
                    found.setdefault(block.get("tool_use_id", str(len(found))), str(inner))
        return list(found.values())


def as_user(user: str, command: list[str], env: dict[str, str]) -> list[str]:
    """`command` as `user` with a login-like environment: their HOME, no root's variables."""
    home = pwd.getpwnam(user).pw_dir
    base = {"HOME": home, "USER": user, "LOGNAME": user, "PATH": "/usr/local/bin:/usr/bin:/bin"}
    pairs = [f"{k}={v}" for k, v in {**base, **env}.items()]
    return ["runuser", "-u", user, "--", "env", "-i", *pairs, *command]


def run(
    steps: list[dict],
    *,
    cwd: str,
    user: str = "learner",
    prompt: str = "Do the task.",
    args: list[str] | None = None,
    command: list[str] | str | None = None,
    env: dict[str, str] | None = None,
    stdin: str = "",
    timeout: float = 120,
) -> Run:
    """One Claude Code run against `steps`. `command` runs a script that calls `claude` itself."""
    server, script = fake_anthropic.serve(0, steps)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        if command is None:
            argv = [CLAUDE, "-p", prompt, "--output-format", "json", *(args or [])]
        elif isinstance(command, str):
            argv = ["/bin/sh", "-c", f"cd {shlex.quote(cwd)} && {command}"]
        else:
            argv = list(command)
        full_env = {**offline_env(base_url), **(env or {})}
        try:
            done = subprocess.run(
                as_user(user, argv, full_env),
                cwd=cwd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            code, out, err = done.returncode, done.stdout, done.stderr
        except subprocess.TimeoutExpired as e:
            code = 124
            out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else ""
            err = f"timed out after {timeout:.0f}s"
        with script.lock:
            requests = [r for r in script.requests if r.get("messages")]
        result = {}
        for line in reversed(out.strip().splitlines()):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict) and "session_id" in parsed:
                result = parsed
                break
        return Run(code, out, err, result, requests)
    finally:
        server.shutdown()
        server.server_close()


def ensure_home(user: str) -> str:
    home = pwd.getpwnam(user).pw_dir
    os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
    return home
