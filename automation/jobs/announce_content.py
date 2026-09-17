"""What arrived on main: new labs, journals and question banks, posted to Discord.

    python3 -m automation.jobs.announce_content <before-sha> <after-sha>

A release already announces itself (`automation.jobs.release announce`); this is the other half —
content lands on main continuously, and a reader of the channel should hear about a lab the day it
merges rather than at the next tag. It reads the push's own diff, so it never announces the same
thing twice, and it says nothing at all when a push carries no new content.

Rated content is never announced from here: `rated/` is a private submodule, and a public channel
is exactly where its existence must not be described (docs/rated-labs.md).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from automation.jobs.common import ROOT, env, notice, post_discord

#: What counts as new content, and how a path turns into a line in the message.
KINDS = (
    ("labs", "lab"),
    ("journals", "journal"),
    ("quizzes", "question bank"),
)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def title_of(text: str) -> str:
    """The title a lab.yaml, a journal's front matter or a bank declares."""
    match = re.search(r"^title:[ \t]*(.+?)[ \t]*$", text, re.M)
    return match.group(1).strip("'\"") if match else ""


def added(before: str, after: str) -> list[dict]:
    """Every lab, journal and bank added by this push, in the order git reports them."""
    out = []
    for line in git("diff", "--name-status", before, after).splitlines():
        status, _, path = line.partition("\t")
        parts = Path(path).parts
        if status != "A" or not parts or any(p.startswith("_") for p in parts):
            continue
        top = parts[0]
        kind = next((label for prefix, label in KINDS if top == prefix), "")
        if not kind:
            continue
        if kind == "lab" and parts[-1] != "lab.yaml":
            continue
        note = kind == "journal" and len(parts) == 3 and parts[1] == "notes"
        if kind == "journal" and ((len(parts) != 2 and not note) or not path.endswith(".md")):
            continue
        if kind == "question bank" and (len(parts) != 2 or not path.endswith(".yaml")):
            continue
        slug = parts[-2] if kind == "lab" else Path(parts[-1]).stem
        out.append({"kind": kind, "slug": slug, "title": title_of(git("show", f"{after}:{path}"))})
    return out


def message(items: list[dict], site: str) -> str:
    lines = []
    for item in items:
        where = {
            "lab": f"{site}/labs/{item['slug']}/",
            "journal": f"{site}/journals/{item['slug']}/",
            "question bank": f"{site}/labs/#theory",
        }[item["kind"]]
        name = item["title"] or item["slug"]
        lines.append(f"- {item['kind']}: **{name}** — {where}")
    return "New on Norboten:\n" + "\n".join(lines)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    site = env("NORBOTEN_SITE", "https://norboten.org").rstrip("/")
    items = added(argv[0], argv[1])
    if not items:
        notice("no new labs, journals or banks in this push")
        return
    post_discord(message(items, site))
    notice(f"announced {len(items)} new item(s)")


if __name__ == "__main__":
    main(sys.argv[1:])
