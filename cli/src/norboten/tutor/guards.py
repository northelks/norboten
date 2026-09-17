"""What may leave the tutor. Every blocked reply is recorded, with the rule that blocked it."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("norboten.guards")

# Lines in a reference solution that are too generic to count as a leak on their own.
_TRIVIAL = re.compile(r"^\s*(#|set -|fi$|done$|esac$|\}|\{|EOF|\w+\s*=\s*\$\(|exit\b)")
_PATH = re.compile(r"(?<![\w.:/])(/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)")
_COMMANDS = re.compile(
    r"\b(chmod|chown|chgrp|usermod|useradd|groupadd|semanage|setsebool|restorecon|firewall-cmd|"
    r"systemctl|nmcli|hostnamectl|lvextend|vgextend|pvcreate|mkswap|swapon|sed|chage|logrotate|"
    r"apparmor_parser|aa-enforce|dnf|apt|chpasswd)\b"
)
_ASKS_FOR_ANSWER = re.compile(
    r"\b(here is the fix|run this|the answer is|paste this|the solution is)\b", re.I
)


@dataclass
class Verdict:
    ok: bool
    rule: str = ""
    detail: str = ""
    matched: list[str] = field(default_factory=list)


def _solution_lines(solution_text: str) -> list[str]:
    lines = []
    for raw in solution_text.splitlines():
        line = raw.strip()
        if len(line) < 8 or _TRIVIAL.match(line):
            continue
        lines.append(line)
    return lines


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def solution_lines_in(text: str, solution_text: str) -> list[str]:
    """The lines of a reference solution that appear in `text`, whitespace and case aside."""
    flat = _normalise(text)
    return [line for line in _solution_lines(solution_text) if _normalise(line) in flat]


def check_reply(message: str, *, solution_text: str = "", hint_level: int = 1) -> Verdict:
    """Block a reply that hands over the fix, or that is too specific for the hint level."""
    flat = _normalise(message)

    if _ASKS_FOR_ANSWER.search(message):
        return Verdict(False, "announces_the_fix", "the reply offers the answer outright")

    for line in _solution_lines(solution_text):
        if _normalise(line) in flat:
            return Verdict(
                False, "solution_line", "a line of the reference solution appeared", [line]
            )

    solution_paths = set(_PATH.findall(solution_text))
    reply_paths = set(_PATH.findall(message))
    if hint_level < 3:
        leaked = sorted(reply_paths & solution_paths)
        if leaked:
            return Verdict(
                False, "path_too_early", f"named {leaked[0]} at hint level {hint_level}", leaked
            )
        if _COMMANDS.search(message) and re.search(r"\s-{1,2}\w", message):
            return Verdict(
                False, "command_too_early", "gave a command with options below hint level 3"
            )
    return Verdict(True)


def enforce(
    message: str, *, solution_text: str, hint_level: int, lab_id: str
) -> tuple[str, Verdict]:
    verdict = check_reply(message, solution_text=solution_text, hint_level=hint_level)
    if not verdict.ok:
        log.warning(
            "tutor reply blocked: lab=%s rule=%s detail=%s", lab_id, verdict.rule, verdict.detail
        )
        return (
            "I am not going to give you that. Tell me what you have already looked at, and I "
            "will tell you what you have not.",
            verdict,
        )
    return message, verdict
