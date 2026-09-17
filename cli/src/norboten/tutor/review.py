"""The post-mortem reviewer: the only agent allowed to see the reference solution, and only
after the attempt is over (passed or surrendered). It explains what the machine was signalling
and where the learner's diagnostic path went wrong — not what to type.

It runs on the learner's machine, like the tutor, on the same model. The commands it reads come
from two places (`commands.py`): recordings of the attempt, which are exact and timed, and the
shell history on the machine, which covers every shell but has no times and can be edited."""

from __future__ import annotations

from pydantic import BaseModel, Field

from norboten.questions import providers
from norboten.tutor.agent import CheckState, _fact_summary

SYSTEM = """You are reviewing a finished attempt at a Linux troubleshooting lab. The attempt is
over: the learner has either passed or given up, so you may discuss the fix.

Write for someone who wants to be better next time:
- What the machine was telling them, and where that evidence was.
- The first point at which their path went wrong — a command they ran that could not have shown
  the problem, or the evidence they never looked at.
- What a faster path would have been, as a sequence of observations, not a script to paste.
- One habit to take to the next lab.

Be specific about this attempt. No praise, no filler, no headings. At most 250 words."""


class PostMortemRequest(BaseModel):
    lab_id: str
    objectives: list[str] = Field(default_factory=list)
    checks: list[CheckState] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)  # already labelled with their source
    facts: dict = Field(default_factory=dict)
    hint_levels: dict[str, int] = Field(default_factory=dict)
    surrendered: bool = False
    minutes: int = 0


class PostMortem(BaseModel):
    what_the_machine_was_saying: str
    where_the_path_went_wrong: str
    a_faster_path: str
    habit_for_next_time: str


def review(
    req: PostMortemRequest,
    solution_text: str,
    *,
    model: str,
    config: providers.Config | None = None,
) -> PostMortem:
    checks = "\n".join(
        f"- {c.id}: {'passed' if c.passed else 'failed'} — {c.message}" for c in req.checks
    )
    commands = "\n".join(req.commands[-60:]) or "(no commands were recorded)"
    hints = ", ".join(f"{k}={v}" for k, v in req.hint_levels.items()) or "none"
    return providers.ask(
        config=config,
        model=model,
        system=SYSTEM,
        user=(
            f"Lab: {req.lab_id}\nOutcome: {'surrendered' if req.surrendered else 'passed'} after "
            f"{req.minutes} minutes. Hints taken: {hints}\n\n"
            f"Objectives:\n" + "\n".join(f"- {o}" for o in req.objectives) + "\n\n"
            f"Final check results:\n{checks}\n\n"
            "Commands the learner ran. [recorded +m:ss] lines are exact and timed from the start; "
            "[history] lines come from shell history, untimed and possibly incomplete:\n"
            f"{commands}\n\n"
            f"Final machine state:\n{_fact_summary(req.facts)}\n\n"
            f"Reference solution (for your understanding; quote from it only if it explains the "
            f"lesson):\n{solution_text}"
        ),
        schema=PostMortem,
        max_tokens=1500,
    )
