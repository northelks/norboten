# The Reviewer Nobody Calls

Before a branch of `~/payments` is merged, `~/bin/review-diff` pipes its diff to Claude Code and
asks the team's **security-reviewer** subagent to review it. The subagent's instructions were
written carefully and agreed by the whole team. Its reviews never arrive: the job's result says
the main agent "reviewed it itself", and nobody can tell whether the reviewer has ever run.

The team's rules for the reviewer are short. It reads; it never edits files or runs commands. It
runs on Haiku — a review a day on a larger model was never in the budget.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine that asks for the security-reviewer on every
run; Claude Code decides for real whether that agent exists, which tools it gets and which model
it asks for. The job's JSON result is `~/review.json`.

What is expected, and graded — the grader runs `~/bin/review-diff` itself:

1. When the model asks for the security-reviewer, the review runs in that subagent.
2. The subagent is offered tools to read the code and nothing else.
3. The subagent runs on Haiku.
