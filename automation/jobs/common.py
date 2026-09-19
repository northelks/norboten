"""What every job needs: the event, GitHub's REST API, Discord and Telegram, and Claude Code.

Standard library only, so a job runs with the runner's own `python3` and no install step. Every
address comes from the environment, which is how `automation/rehearse.py` points a job at
stand-ins: `GITHUB_API_URL`, `TELEGRAM_API_URL`, `DISCORD_WEBHOOK`, `NORBOTEN_API` and, for the
model, `ANTHROPIC_BASE_URL` (read by Claude Code itself).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# the checkout a job works in; the rehearsal points it at a scratch repository
ROOT = Path(os.environ.get("NORBOTEN_REPO") or Path(__file__).resolve().parents[2])


class JobError(RuntimeError):
    """A step failed in a way the run should report as failed."""


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, "")
    if value:
        return value
    if default is None:
        raise JobError(f"{name} is not set")
    return default


def event() -> dict:
    """The webhook payload that triggered the run (`GITHUB_EVENT_PATH`)."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    return json.loads(Path(path).read_text()) if path else {}


def notice(message: str) -> None:
    """A line in the run log that GitHub also shows on the run's summary page."""
    print(f"::notice::{message}", flush=True)


def summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(markdown.rstrip() + "\n")


def http(method: str, url: str, body: Any = None, headers: dict | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raise JobError(f"{method} {url}: {e.code} {e.read()[:300]!r}") from None
    return json.loads(raw) if raw.strip() else None


class GitHub:
    """The few REST calls the jobs make, against `GITHUB_API_URL` with `GH_TOKEN`."""

    def __init__(self) -> None:
        self.base = env("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        self.repo = env("GITHUB_REPOSITORY")
        self.token = env("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))

    def call(self, method: str, path: str, body: Any = None, **query: Any) -> Any:
        url = f"{self.base}{path.replace('{repo}', self.repo)}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return http(method, url, body, headers)

    def open_issue_titled(self, title: str) -> dict | None:
        """An open issue whose title is exactly this one, if there is one."""
        q = f'repo:{self.repo} is:issue is:open in:title "{title}"'
        found = self.call("GET", "/search/issues", q=q).get("items", [])
        wanted = title.strip().lower()
        return next((i for i in found if i["title"].strip().lower() == wanted), None)

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self.call(
            "POST", "/repos/{repo}/issues", {"title": title, "body": body, "labels": labels}
        )

    def open_issues(self) -> list[dict]:
        """Every open issue of the repository (pull requests left out)."""
        issues, page = [], 1
        while True:
            batch = self.call("GET", "/repos/{repo}/issues", state="open", per_page=100, page=page)
            issues += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return issues
            page += 1

    def close_issue(self, number: int, comment: str) -> None:
        self.call("POST", f"/repos/{{repo}}/issues/{number}/comments", {"body": comment})
        self.call("PATCH", f"/repos/{{repo}}/issues/{number}", {"state": "closed"})


def post_discord(text: str) -> bool:
    """Tell the maintainer. Without `DISCORD_WEBHOOK` the message is only logged."""
    url = os.environ.get("DISCORD_WEBHOOK", "")
    if not url:
        notice(f"DISCORD_WEBHOOK is not set; not posted: {text[:120]}")
        return False
    http("POST", url, {"content": text[:2000]})
    return True


def post_telegram(text: str) -> bool:
    """Tell the channel. Without a bot token and a chat the message is only logged."""
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT", "")
    if not (token and chat):
        notice(f"TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT is not set; not posted: {text[:120]}")
        return False
    base = env("TELEGRAM_API_URL", "https://api.telegram.org").rstrip("/")
    http("POST", f"{base}/bot{token}/sendMessage", {"chat_id": chat, "text": text})
    return True


class ClaudeError(JobError):
    pass


def claude(
    prompt: str,
    *,
    system: str | None = None,
    stdin: str = "",
    model: str = "haiku",
    max_turns: int = 1,
    tools: str | None = "",
    schema: dict | None = None,
    cwd: Path | None = None,
    extra: list[str] | None = None,
    timeout: int = 300,
) -> dict:
    """One headless Claude Code run; the parsed `--output-format json` result.

    The defaults are the cheap, safe shape: the small model, one turn, **no tools** (`--tools ""`)
    — the model reads what it is given on stdin and answers, and cannot act on anything. A job that
    needs tools says which. A `system` prompt replaces Claude Code's own (`--system-prompt`), which
    is about 27 KB of instructions for using tools a no-tool job does not have. With no `cwd` the
    run happens in an empty directory, so no project `CLAUDE.md`, hooks or MCP servers load: the
    issue text a stranger wrote never meets a shell.

    A no-tool run also has extended thinking turned off (`MAX_THINKING_TOKENS=0`): measured on real
    triage runs, Haiku spent 200–1,000 output tokens thinking about a one-field label, and without
    it chose the same labels in half the time for about a quarter less. `--effort low` did not
    reduce it.

    Authentication is Claude Code's own: `CLAUDE_CODE_OAUTH_TOKEN` in CI (a subscription token
    from `claude setup-token`). That is why this never passes `--bare`, which ignores the token.
    """
    cmd = [
        env("CLAUDE_BIN", "claude"),
        "-p",
        prompt,
        "--model",
        model,
        "--max-turns",
        str(max_turns),
        "--output-format",
        "json",
        "--no-session-persistence",
    ]
    if system is not None:
        cmd += ["--system-prompt", system]
    if tools is not None:
        cmd += ["--tools", tools]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema)]
    cmd += extra or []
    run_env = dict(os.environ)
    if tools == "":
        run_env.setdefault("MAX_THINKING_TOKENS", "0")
    with tempfile.TemporaryDirectory(prefix="norboten-job-") as empty:
        done = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            cwd=cwd or empty,
            env=run_env,
            timeout=timeout,
        )
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(
            f"claude exited {done.returncode} without a JSON result: "
            f"{(done.stderr or done.stdout)[-500:]}"
        ) from None
    cost = result.get("total_cost_usd")
    usage = result.get("usage") or {}
    # most of an agentic run's input is cached; `input_tokens` alone counts only the uncached rest
    tokens_in = sum(
        usage.get(k, 0)
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    notice(
        f"claude {model}: {result.get('num_turns')} turns, "
        f"{tokens_in} in ({usage.get('cache_read_input_tokens', 0)} cached) / "
        f"{usage.get('output_tokens', 0)} out tokens, ~${cost} at list price "
        f"({result.get('subtype')})"
    )
    summary(
        f"| claude | {model} | {result.get('num_turns')} turns | "
        f"{tokens_in}/{usage.get('output_tokens', 0)} tokens | ~${cost} |"
    )
    if result.get("is_error") or done.returncode != 0:
        detail = result.get("errors") or result.get("result") or result.get("subtype")
        raise ClaudeError(f"claude run failed: {detail}")
    return result
