"""An issue labelled `lab-request` becomes a draft lab on its own branch and a draft pull request.

Claude Code runs in the checkout as the project's `lab-author` subagent
(`.claude/agents/lab-author.md`), with the request on stdin. What it may do is decided here, not in
the prompt: the built-in tools are cut to Read, Glob, Grep and Write (`--tools`, so no shell),
writes are allowed only under `labs/_drafts/` (`--allowedTools "Edit(/labs/_drafts/**)"`, which
covers the Write tool), and `--permission-mode dontAsk` denies everything else instead of waiting
for a person. Turns and spend are capped.

Then the script checks the result rather than trusting it — exactly one new file, under
`labs/_drafts/`, and nothing else touched — and does the git and GitHub work itself: branch,
commit, push, draft pull request, a note on Discord. The model never holds a GitHub token.

A request for a **rated** lab (the issue also carries the `rated` label) is declined, with a
comment, before any model runs: a rated lab's faults, checks and answer must never appear in a
public issue, branch or pull request, and this repository is public. Rated labs are written in the
private repository by someone with access to it (docs/rated-labs.md).

    python3 -m automation.jobs.lab_author      # .github/workflows/lab-author.yml
"""

from __future__ import annotations

import re
import subprocess

from automation.jobs.common import (
    ROOT,
    GitHub,
    JobError,
    claude,
    env,
    event,
    notice,
    post_discord,
)

DRAFT = re.compile(r"^labs/_drafts/(?P<id>[a-z]+-\d{2}-[a-z0-9-]+)\.md$")

PROMPT = """Draft a lab from the lab request on stdin, following your instructions. Write the one \
file and stop."""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def changed_paths() -> list[str]:
    """Every path the run added, changed or deleted, untracked files included."""
    out = git("status", "--porcelain", "--untracked-files=all")
    return [line[3:] for line in out.splitlines() if line.strip()]


def draft(title: str, body: str) -> str:
    if changed_paths():
        raise JobError("the checkout is not clean before the run")
    claude(
        PROMPT,
        stdin=f"Issue title: {title}\n\n{body or '(no body)'}"[:20000],
        model=env("LAB_AUTHOR_MODEL", "sonnet"),
        max_turns=int(env("LAB_AUTHOR_MAX_TURNS", "20")),
        tools="Read,Glob,Grep,Write",
        cwd=ROOT,
        extra=[
            "--agent",
            "lab-author",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Read,Glob,Grep,Edit(/labs/_drafts/**)",
            "--max-budget-usd",
            env("LAB_AUTHOR_BUDGET_USD", "1.00"),
        ],
        timeout=900,
    )
    changed = changed_paths()
    drafts = [p for p in changed if DRAFT.match(p)]
    if len(drafts) != 1 or len(changed) != 1:
        raise JobError(f"expected one new file under labs/_drafts/, the run changed: {changed}")
    return drafts[0]


DECLINE_RATED = (
    "This asks for a **rated** lab, and those are not drafted from public issues: a rated lab's "
    "faults, checks and answer must stay out of this repository, its branches and its pull "
    "requests. Rated labs are written in the private repository — see docs/rated-labs.md. If an "
    "unrated lab would do, remove the `rated` label and add `lab-request` again."
)


def is_rated(issue: dict) -> bool:
    return any(label.get("name") == "rated" for label in issue.get("labels") or [])


def main() -> None:
    payload = event()
    if payload.get("label", {}).get("name") != "lab-request":
        notice("not a lab-request label: nothing to do")
        return
    issue = payload["issue"]
    if is_rated(issue):
        GitHub().call(
            "POST", f"/repos/{{repo}}/issues/{issue['number']}/comments", {"body": DECLINE_RATED}
        )
        notice("a rated lab request: declined, nothing drafted")
        return
    path = draft(issue["title"], issue.get("body") or "")
    lab_id = DRAFT.match(path)["id"]
    branch = f"lab-request/{lab_id}"

    git("switch", "-c", branch)
    git("add", path)
    git(
        "-c",
        "user.name=norboten lab-author",
        "-c",
        "user.email=lab-author@norboten.org",
        "commit",
        "-m",
        f"draft(lab): {lab_id}\n\nFrom #{issue['number']}, drafted by Claude Code.",
    )
    git("push", "origin", branch)

    gh = GitHub()
    pr = gh.call(
        "POST",
        "/repos/{repo}/pulls",
        {
            "title": f"Draft lab: {lab_id}",
            "head": branch,
            "base": env("LAB_AUTHOR_BASE", "main"),
            "draft": True,
            "body": (
                f"From #{issue['number']}. A starting point drafted by Claude Code, not a lab: see "
                "the checklist in the file. CI's solvability gate and a review decide."
            ),
        },
    )
    notice(f"opened draft pull request {pr.get('html_url')}")
    post_discord(f"A draft lab is waiting for review: {pr.get('html_url')}")


if __name__ == "__main__":
    main()
