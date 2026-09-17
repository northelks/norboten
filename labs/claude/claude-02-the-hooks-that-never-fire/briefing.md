# The Hooks That Never Fire

The billing team lets a nightly Claude Code job, `~/bin/nightly-cleanup`, tidy the code in
`~/billing`. Three hooks in the repository's `.claude/settings.json` are the guard rails everyone
agreed on: Python the agent writes is re-indented with spaces (the model likes tabs), the agent never pushes,
and migrations that have already run against production are never edited.

Last night the agent edited an applied migration, committed it and pushed it to `origin` — and the
Python file it wrote is indented with tabs. Nobody changed the hooks. The job's JSON result
is in `~/nightly-cleanup.log`.

This lab runs in a container, as `learner` with `sudo`. `claude` here is the real Claude Code
2.1.270, talking to a scripted model on this machine: every run replays last night's plan, and
Claude Code carries out the tool calls — and runs the hooks — for real. `origin` is a bare
repository at `/srv/git/billing.git`.

What is expected, and graded — the grader runs `~/bin/nightly-cleanup` itself, against models that
try other things:

1. A Python file the agent writes or edits comes out indented with spaces, not tabs.
2. The agent cannot push, however it spells the command — and can still run `git status`.
3. The agent cannot edit or overwrite a migration that already exists — and can still add a new one.
4. The applied migration is back to what production ran, in your working tree and on `origin`.

Keep the hooks: the job's own permissions are not the problem to solve here.
