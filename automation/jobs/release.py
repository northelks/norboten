"""A release: notes drafted by Claude from the commits, then the announcements. Two subcommands.

    python3 -m automation.jobs.release notes v0.2.0 notes.md   # before `gh release create`
    python3 -m automation.jobs.release announce v0.2.0         # after the release exists

`notes` gives Claude the commit subjects and bodies since the previous tag on stdin, with no
tools, and asks for a short grouped summary. The complete commit list is appended by this script,
so the notes stay true even where the summary is thin. Without a token, or if the run fails, the
notes are the commit list alone and the job goes on: a release is not held back by its prose.

`announce` needs no model: the labs a release adds are the `lab.yaml` files that appear between
the two tags. Discord gets the release, Telegram one message per new lab.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from automation.jobs.common import (
    ROOT,
    ClaudeError,
    claude,
    env,
    notice,
    post_discord,
    post_telegram,
)

PROMPT = """On stdin are the commits of a Norboten release (a project where people learn Linux by \
fixing broken machines), oldest first. Write release notes in Markdown: a one-sentence summary, \
then short bullet lists under whichever of these headings apply — New labs, Theory and journals, \
TUI and CLI, Server and site, Fixes. Only what the commits say; no version numbers, dates or \
counts they do not contain. At most 25 bullets. No preamble."""


ASK = "Write the release notes for the commits on stdin."


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def previous_tag(tag: str) -> str | None:
    try:
        return git("describe", "--tags", "--abbrev=0", "--match", "v*", f"{tag}^")
    except subprocess.CalledProcessError:
        return None  # the first release


def commits(tag: str) -> str:
    since = previous_tag(tag)
    span = f"{since}..{tag}" if since else tag
    return git("log", "--reverse", "--no-merges", "--format=- %h %s%n%b", span)


def notes(tag: str, out: Path) -> None:
    log = commits(tag)
    summary = ""
    if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        notice("no Claude token: release notes without a summary")
    else:
        try:
            summary = claude(ASK, system=PROMPT, stdin=log[:60000], max_turns=1)["result"].strip()
            summary += "\n\n_The summary above was drafted by Claude Code from the commits below._"
        except ClaudeError as e:
            notice(f"release notes without a summary: {e}")
    subjects = "\n".join(line for line in log.splitlines() if line.startswith("- "))
    since = previous_tag(tag)
    heading = f"## Commits since {since}" if since else "## Commits"
    out.write_text(f"{summary}\n\n{heading}\n\n{subjects}\n".lstrip())
    notice(f"wrote {out}")


def manifest_fields(text: str) -> dict:
    """The top-level scalars of a lab.yaml that an announcement names; no YAML library needed."""
    fields = {}
    for m in re.finditer(r"^(id|title|track|difficulty):[ \t]*(.+?)[ \t]*$", text, re.M):
        fields[m.group(1)] = m.group(2).strip("'\"")
    return fields


def added_labs(tag: str) -> list[dict]:
    since = previous_tag(tag)
    if since is None:
        return []  # the first release adds everything; announcing that is noise
    labs = []
    for line in git("diff", "--name-status", since, tag, "--", "labs").splitlines():
        status, _, path = line.partition("\t")
        parts = Path(path).parts
        if status != "A" or parts[-1] != "lab.yaml" or any(p.startswith("_") for p in parts):
            continue
        labs.append(manifest_fields(git("show", f"{tag}:{path}")))
    return labs


def announce(tag: str) -> None:
    repo = env("GITHUB_REPOSITORY")
    server = env("GITHUB_SERVER_URL", "https://github.com")
    site = env("NORBOTEN_SITE", "https://norboten.org").rstrip("/")
    labs = added_labs(tag)
    text = f"Norboten {tag} is out: {server}/{repo}/releases/tag/{tag}"
    if labs:
        text += "\nNew labs: " + ", ".join(lab["id"] for lab in labs)
    post_discord(text)
    for lab in labs:
        post_telegram(
            f"New lab: {lab['title']} ({lab['track']}, difficulty {lab['difficulty']})\n"
            f"{site}/labs/{lab['id']}/"
        )
    notice(f"announced {tag} with {len(labs)} new lab(s)")


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[0] == "notes":
        notes(argv[1], Path(argv[2]))
    elif len(argv) >= 2 and argv[0] == "announce":
        announce(argv[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
