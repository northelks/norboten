---
title: A hook is a policy only if it fires, reads its input and exits 2
topics: [claude-code, bash]
minutes: 35
---

Hooks are the part of Claude Code that turns a team's rules into code that runs every time: format
what the agent writes, refuse a push, keep it out of files that must not change. They are also the
part that fails most quietly. A hook that never fires looks exactly like a hook that found nothing
to do. A hook that detects the forbidden command and exits with the wrong status prints a
convincing "Blocked:" message and lets the command run. A hook that is not executable produces a
non-blocking error that nobody reads.

The billing repository in this lab has three hooks, and each fails in a different one of those
ways. None of them is fixed by reading the settings file harder: each needs the hook to be **run
and observed** — with a trace, by hand with the JSON it will receive, or through the agent — and
the permission denials of a run to be read afterwards.

## What you should be able to do after this

- Write a hook matcher that matches the tools you mean, and explain why `edit|write` matches none.
- Read a command hook's input from stdin with `jq`, and name the fields a tool hook receives.
- Say what exit status 0, 2 and anything else mean for a `PreToolUse` hook, where the reason must be
  printed, and the JSON alternative.
- Find a hook that cannot run, and test one by hand before trusting it.
- See a hook's refusals in a headless run's `permission_denials`.
- Undo a file an agent changed in a pushed commit without rewriting shared history.

## The mechanism

### Where hooks live and when they run

Hooks are configured under `"hooks"` in any settings file — user, project, local, managed — and
entries from every level are **merged**, not overridden. The shape is event → matcher groups →
handlers:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/no-push.sh" }] }
    ]
  }
}
```

For tool calls the two events that matter are `PreToolUse`, which runs after Claude Code has the
model's tool call and before anything happens, and can refuse it; and `PostToolUse`, which runs
after the tool succeeded and can only react — the file is already written. There are many more
(`SessionStart`, `UserPromptSubmit`, `Stop`, `SubagentStop`, …); `/hooks` in an interactive session
lists what loaded.

A headless `claude -p` run loads the project's hooks without a trust dialog — which is what makes
them useful as guard rails for CI jobs, and why a repository's `.claude/` must be reviewed like
code.

### Matchers are tool names, exactly

For tool events the matcher is compared with the tool name:

- `*`, `""` or no matcher: every tool;
- only letters, digits, `_`, `-`, `,`, `|` and spaces: a list of **exact names** — `Edit|Write`;
- anything else: an unanchored JavaScript regular expression — `Edit.*` also matches `NotebookEdit`,
  `mcp__github__.*` matches every tool of one MCP server.

Tool names are case-sensitive: `Bash`, `Edit`, `Write`, `Read`. A matcher `bash` or `edit|write` is
valid, loads without a warning, and matches nothing. Claude Code 2.1.270 does not flag it.

### Input arrives as JSON on stdin

A command hook is started with **no arguments**. Claude Code writes one JSON object to its stdin and
sets `$CLAUDE_PROJECT_DIR`. For a Write call the object carries, among others:

```json
{"hook_event_name": "PostToolUse", "tool_name": "Write",
 "tool_input": {"file_path": "/home/learner/billing/app/overdue.py", "content": "…"},
 "session_id": "…", "cwd": "/home/learner/billing", "transcript_path": "…"}
```

File paths in `tool_input` are absolute. For Bash, `tool_input.command` is the command string. A
script written as `file="$1"` gets an empty string every time — and a `case` on an empty string
simply matches nothing, so the hook "succeeds".

### Exit status decides whether a PreToolUse hook blocks

| the hook | what happens to the tool call | what the model sees |
|---|---|---|
| exits 0 | proceeds (stdout parsed as JSON if it is a JSON object) | nothing |
| exits **2** | **refused** | stderr, as the hook's error |
| exits 2 with its message on stdout | refused | "No stderr output" |
| exits 1 (or any other status) | **proceeds** — a non-blocking error | the tool's normal result |
| cannot be executed (mode 0644 → status 126) | proceeds | the tool's normal result |
| exits 0 with `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "…"}}` | refused | the reason |

Every row was run against Claude Code 2.1.270 in the lab image. The trap is the fourth row: exit 1
is what every shell script uses for "something is wrong", and for a hook it means "carry on". A
blocking hook must exit 2, or answer with JSON; a refused call is then listed in the run's
`permission_denials` just like a call a deny rule refused.

A `PostToolUse` hook cannot undo anything. Exit 2 there feeds stderr back to the model as feedback,
which is useful ("the formatter failed on line 3") but not a guard.

### Claude Code's own edits

Two details matter when you test a formatting hook. The Write and Edit tools already remove trailing
whitespace from the lines they write, so a hook that strips it has nothing to prove itself on. They
do keep tabs. That is why this lab's tidy hook re-indents tabs (`expand -i -t 4`), and why a check
that a formatter ran must use a change the tool itself would not make.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, the scripted model). The agent's commit is on
`origin`, and the diff of the applied migration is small enough to have passed review:

```console
$ git log --oneline origin/main
70a4239 Tidy up: overdue report, migration comment
3c4ac24 Invoices with due dates (0002 applied)
$ git show HEAD -- migrations | tail -3
 ALTER TABLE invoices
-    ADD COLUMN due date NOT NULL DEFAULT CURRENT_DATE;  -- when payment is due
+    ADD COLUMN due date NOT NULL DEFAULT CURRENT_DATE;  -- when the payment is due
$ tail -n1 ~/nightly-cleanup.log | jq -c '{num_turns, permission_denials}'
{"num_turns":6,"permission_denials":[]}
```

Six turns and no denials: nothing refused the edit or the push. The hooks, as configured, and the
scripts they name:

```console
$ jq -c '.hooks | to_entries[] | {event: .key, matchers: [.value[].matcher]}' .claude/settings.json
{"event":"PostToolUse","matchers":["edit|write"]}
{"event":"PreToolUse","matchers":["Bash","Edit|Write"]}
$ ls -l .claude/hooks
-rwxr-xr-x 1 learner learner 343 Sep 14 19:21 no-push.sh
-rw-r--r-- 1 learner learner 384 Sep 14 19:21 protect-migrations.sh
-rwxr-xr-x 1 learner learner 177 Sep 14 19:21 tidy.sh
```

Start with the tidy hook and make it leave a trace: a `cat > /tmp/tidy-input.json` line at its top.
Run the job; no trace appears, so the hook never runs. Look at `origin` after that run, though:

```console
$ git log --oneline -3 origin/main
44cb4f8 Tidy up: overdue report, migration comment
70a4239 Tidy up: overdue report, migration comment
3c4ac24 Invoices with due dates (0002 applied)
$ git show --stat --format='%h %s' origin/main | tail -1
 .claude/hooks/tidy.sh | 1 +
```

The replayed plan ends in `git add -A`, commit and push, so **the trace line you were debugging with
was committed and pushed by the agent**. Debugging a job that can push, with the job itself, publishes
your experiments. (In the replay above this was undone with `git reset --hard HEAD~1` and a force
push, which is acceptable only because nobody else has fetched it yet.) Fix the push guard before
running the job again.

The guard, run by hand with the input Claude Code would give it:

```console
$ printf '%s' '{"tool_input":{"command":"git push origin main"}}' | .claude/hooks/no-push.sh; echo "exit $?"
Blocked: agents do not push. Commit locally and leave the push to a person.
exit 1
$ printf '%s' "{\"tool_input\":{\"file_path\":\"$PWD/migrations/0001_create_invoices.sql\"}}" \
    | CLAUDE_PROJECT_DIR=$PWD .claude/hooks/protect-migrations.sh; echo "exit $?"
bash: line 1: .claude/hooks/protect-migrations.sh: Permission denied
exit 126
```

`no-push.sh` detects the push perfectly and exits 1, which lets it through; its message goes to
stdout, where Claude Code does not look. `protect-migrations.sh` is correct and cannot run. With the
matcher changed to `Edit|Write`, the trace shows what `tidy.sh` receives — and that the path is not an
argument:

```console
$ jq -c '{hook_event_name, tool_name, tool_input: (.tool_input | keys)}' /tmp/tidy-input.json
{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":["content","file_path"]}
```

Three fixes, then: `tidy.sh` reads `file=$(jq -r '.tool_input.file_path // ""')`; `no-push.sh`
prints to stderr and exits 2; `protect-migrations.sh` gets its execute bit. The job again:

```console
$ ~/bin/nightly-cleanup
$ tail -n1 ~/nightly-cleanup.log | jq -c '[.permission_denials[] | {tool_name, input: (.tool_input.command // .tool_input.file_path)}]'
[{"tool_name":"Bash","input":"git push origin main"}]
$ grep -P -c '\t' app/overdue.py
0
$ git log --oneline -2 origin/main
70a4239 Tidy up: overdue report, migration comment
3c4ac24 Invoices with due dates (0002 applied)
```

The push is refused and listed; the file is re-indented; the agent's local commit (which now
contains the hook fixes) stayed local. The edit of the migration does not appear as a denial only
because the plan's `old_string` no longer exists in the file; the grader tries fresh edits.

What remains is the migration on `origin`. `git revert` of the agent's commit conflicts — the commit
also added `overdue.py`, which later commits changed — and reverting it would throw away the report
nobody objected to. The precise undo is the one file, taken from the commit that added it:

```console
$ git revert --no-edit 70a4239
CONFLICT (modify/delete): app/overdue.py deleted in parent of 70a4239 … and modified in HEAD.
$ git revert --abort
$ applied=$(git log --reverse --format=%h -- migrations/0002_add_due_date.sql | head -1)
$ git restore --source="$applied" --staged --worktree -- migrations/0002_add_due_date.sql
$ git commit -qm "Restore migration 0002 as applied in production" && git push -q origin main
```

A new commit on a shared branch, pushed by a person. The grader:

```
PASS 01_written_code_gets_tidied: What the agent wrote and edited came out indented with spaces.
PASS 02_agents_cannot_push: git status ran; all 3 ways of pushing were stopped before reaching origin.
     $ git push origin HEAD:refs/heads/norboten-probe-1
     PreToolUse:Bash hook error: [$CLAUDE_PROJECT_DIR/.claude/hooks/no-push.sh]: Blocked: agents do not push. …
PASS 03_applied_migrations_are_protected: Edits to existing migrations were blocked; a new migration was written.
PASS 04_the_applied_migration_is_restored: migrations/0002_add_due_date.sql matches what production ran, locally and on origin.
```

## Common wrong turns

**Reading the settings and concluding the hooks are fine.** `edit|write` looks right, the scripts
look right. Every one of the three faults is invisible until a hook is run and observed.

**Debugging through a job that can push.** Each run commits and pushes whatever is in the working
tree — your trace lines included. Test hooks by hand first, and fix the push guard before anything
else.

**Changing the push guard to exit 2 for every Bash call.** Nothing pushes, and nothing else works
either: `git status` is refused. A guard must refuse the forbidden thing and nothing more.

**Blocking every write under `migrations/`.** Applied migrations are safe, and the agent can no
longer write the new migration that is the correct way to change a schema.

**Leaving the reason on stdout with exit 2.** The call is blocked, but the model is told "No stderr
output" and has no idea why, so it tries again another way.

**Making the scripts executable with `chmod 777`.** Executable is `755`. A hook anyone on the
machine can rewrite is a hook anyone can disable — or use to run code in every agent session.

**Relying on a relative path in the hook command.** `.claude/hooks/no-push.sh` works while the
session's working directory is the project root. `$CLAUDE_PROJECT_DIR/.claude/hooks/…` works from
anywhere.

**`git push --force` to make the migration commit disappear.** It works on `origin` and breaks every
clone that already fetched it. On a shared branch, fix forward.

## Cheat sheet

```bash
# what hooks are configured, per event and matcher
jq -c '.hooks | to_entries[] | {event: .key, matchers: [.value[].matcher]}' .claude/settings.json
ls -l .claude/hooks                      # executable?

# see what a hook receives: a first line that saves its stdin
cat > /tmp/hook-input.json

# test a hook by hand, exactly as Claude Code runs it
printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}' \
  | CLAUDE_PROJECT_DIR=$PWD "$PWD/.claude/hooks/no-push.sh"; echo "exit $?"

# reading input inside a hook
cmd=$(jq -r '.tool_input.command // ""')
file=$(jq -r '.tool_input.file_path // ""')

# blocking a PreToolUse call: either
echo "Blocked: reason for the model" >&2; exit 2
# or
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"reason"}}'; exit 0

# after a headless run: what the hooks (and rules) refused
jq -c '.permission_denials[] | {tool_name, tool_input}' run.json

# matchers: exact names are case-sensitive
"matcher": "Edit|Write"        # yes
"matcher": "edit|write"        # matches nothing
"matcher": "mcp__github__.*"   # regex: every tool of one MCP server

# undo one file from a pushed commit, forward
git log --oneline -- path/to/file
git restore --source=<good-commit> --staged --worktree -- path/to/file
git commit -m "Restore …" && git push
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — Guards, helpers and outside data

Documentation:

- https://code.claude.com/docs/en/hooks
- https://git-scm.com/docs/git-revert

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A `PreToolUse` hook has `"matcher": "bash"`. What does it match, and how would you notice?

   > Nothing: a matcher of plain letters is a list of exact tool names and names are case-sensitive,
   > so only `Bash` matches the Bash tool. Nothing warns; a first line in the script that writes its
   > stdin to a file shows it never runs.

2. What does a command hook receive, and where? Give the jq expression for the path of a file the
   Write tool wrote.

   > No arguments; one JSON object on stdin with `hook_event_name`, `tool_name`, `tool_input` and
   > session fields, and `$CLAUDE_PROJECT_DIR` in the environment. `jq -r .tool_input.file_path`.

3. A guard prints "Blocked" and exits 1. What happens to the tool call, and what are the two correct
   ways to block?

   > The call proceeds: any status other than 0 and 2 is a non-blocking error. Exit 2 with the reason
   > on stderr, or exit 0 printing JSON with `hookSpecificOutput.permissionDecision` set to `deny`
   > and a `permissionDecisionReason`.

4. A hook script has mode `0644`. What does Claude Code do with the call it was meant to guard?

   > The shell cannot execute it (status 126), which is a non-blocking error, so the call goes ahead.
   > Make it executable, or run it through `sh` in the command.

5. Why can a `PostToolUse` hook not serve as a guard against editing a file?

   > It runs after the tool has succeeded: the edit is already on disk. Exit 2 there only sends
   > stderr to the model as feedback. Guards belong in `PreToolUse`.

6. Your formatting hook strips trailing whitespace, and a test Write with trailing spaces comes out
   clean even while the hook is broken. Why is that test worthless?

   > Claude Code's Write and Edit tools already remove trailing whitespace from what they write, so
   > the file is clean whether or not the hook ran. Test with a change the tool does not make itself
   > (here, tab indentation), or with a trace of the hook's input.

7. While debugging, you run the nightly job to see whether your hook works. What happened to your
   debugging edits in this lab, and what should the order of work have been?

   > The agent's plan ends in `git add -A`, commit and push, so the edits were committed and pushed
   > to `origin`. Test hooks by hand with sample JSON first, and fix the push guard before running the
   > job again.

8. An agent's pushed commit changed an applied migration and also added a file you want to keep. How
   do you restore the migration on the shared branch?

   > Take that one file from the commit that last had it right — `git restore --source=<commit>
   > --staged --worktree -- <file>` — commit, and push. Reverting the whole commit also removes the
   > wanted file (and here conflicts); force-pushing rewrites history other clones already have.
