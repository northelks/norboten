---
title: A headless agent gets the permissions you write down, and nothing asks twice
topics: [claude-code, ai-agents]
minutes: 35
---

A nightly job asks Claude Code to fix typos. It "kept stopping to ask for permission", so someone
added `--dangerously-skip-permissions`, and for weeks nothing bad happened. Then the model decided
that a directory of unpublished drafts was clutter, deleted it, and opened the file holding the
publishing token while it was looking around. Nothing in Claude Code malfunctioned: it did what the
job told it it was allowed to do.

The fix is not "take the flag out". Take the flag out and a user setting still skips every check;
switch to a strict mode and put the allow rule in the project's settings file and a headless run
ignores it; forbid `rm` and the model has `/bin/rm`, `find -delete`, `git rm` and the Write tool.
There are really four questions: **what mode decides a call no rule mentions**, **which tools the
session has at all**, **where an allow rule is honoured**, and **what a tool result carries to the
model** — plus, first, getting the drafts back.

## What you should be able to do after this

- Restore files an agent deleted from a git working tree, index and working tree both.
- Say what each permission mode does with a call no rule mentions, and why `dontAsk` is the mode for
  unattended jobs.
- Explain the difference between removing a tool (`--tools`) and refusing a call (a deny rule), and
  what the model sees in each case.
- Know every place a permission mode and an allow rule can come from, and which of them a `claude -p`
  run honours in a repository nobody has trusted.
- Predict which ways of reading a secret a `Read` deny rule stops, and which it does not.
- Find what a past run sent to the model on disk, and keep a job from writing it there.

## The mechanism

### Every tool call passes one decision

When the model asks for a tool call, Claude Code decides before running anything. Rules are
evaluated **deny first, then ask, then allow**, across every settings level, and a deny anywhere
cannot be allowed anywhere else — not even by `--allowedTools` on the command line. A call that
matches no rule is decided by the **permission mode**:

| mode | a call no rule mentions |
|---|---|
| `default` (Manual) | reads in the working directory run; anything else prompts |
| `acceptEdits` | file edits and simple filesystem commands (`mkdir`, `touch`, `mv`, `cp`) run; the rest prompts |
| `plan` | nothing that changes anything runs |
| `dontAsk` | anything that would prompt is **denied** |
| `bypassPermissions` | everything runs, except ask and deny rules and a few protected paths |

In `-p` there is nobody to answer a prompt, so a prompt is a denial there too; `dontAsk` makes that
explicit and tells the model so. The denied call comes back to the model as a tool error, and the
run's JSON result lists it in `permission_denials` — the single most useful field when a job "does
nothing".

`--dangerously-skip-permissions` is `bypassPermissions` on the command line. The documentation
reserves it for isolated containers and VMs, and that is the right reading: it is for a machine you
are happy for the model to wreck.

### Settings come from five places

A permission mode (`permissions.defaultMode`) and rules can be set in any of these, highest
precedence first:

1. managed settings (`/etc/claude-code/managed-settings.json` on Linux);
2. the command line (`--permission-mode`, `--allowedTools`, `--settings`);
3. `.claude/settings.local.json` in the project;
4. `.claude/settings.json` in the project, usually committed;
5. `~/.claude/settings.json`, the user's.

Scalar keys such as `defaultMode` are taken from the highest level that sets them; lists such as
`permissions.allow` and `permissions.deny` **merge** across levels. So removing a flag from a
script does not remove a `defaultMode` two levels down, which is exactly what happens in this lab.

### An untrusted project cannot grant itself permissions

Interactive Claude Code asks whether you trust a folder the first time you open it. A headless run
cannot ask, and a repository can ship any `.claude/settings.json` it likes — including one that
allows `Bash`. Claude Code 2.1.270 resolves this by **ignoring allow rules from the shared project
settings file** when `claude -p` runs in a workspace that has not been trusted, and saying so on
stderr:

```
Ignoring 1 permissions.allow entry from .claude/settings.json: this workspace has not been trusted.
```

Deny rules from the same file still apply: a repository may restrict itself, not unlock itself.
The same allow rule works from `--allowedTools`, `--settings <file>`, the user settings or
`.claude/settings.local.json`. In a CI job, where nobody will ever accept the trust dialog, put what
the job needs on its command line, next to the prompt it applies to. (Hooks, `CLAUDE.md`, subagents
and `.mcp.json` servers do load in an untrusted `-p` run; allow rules are the exception.)

### Removing a tool is not the same as refusing a call

`--tools "Read,Edit"` limits the built-in tools the session has. A tool outside the list is not
offered to the model, and a call to it fails before any permission check:

```
Error: No such tool available: Bash. Bash is disabled for this session, in subagents as well as here.
```

A deny rule leaves the tool in place and refuses particular calls. Rules for Bash match the command
text, and they are **not a security boundary**: `Bash(rm *)` does not match `/bin/rm -rf drafts`,
`find drafts -delete`, `python3 -c "shutil.rmtree('drafts')"` or `git rm -r drafts`. In `dontAsk`
those still fail — not because of the rule but because nothing allows them. The robust shape for a
job is therefore: a strict mode, the fewest tools that do the task, and narrow allow rules for the
calls the task makes.

### What a tool returns goes to the model

A tool result is part of the next request. If the Read tool opens `.env`, the token is in the
conversation, in Anthropic's request logs for that run, and in the session transcript Claude Code
writes to `~/.claude/projects/<project>/<session>.jsonl` unless the run passes
`--no-session-persistence`.

A `Read` deny rule for `.env` covers more than the Read tool, and less than it seems:

| the model runs | with `deny: ["Read(./.env)"]` in `dontAsk` |
|---|---|
| Read `/home/learner/handbook/.env` | refused |
| Grep for `TOKEN` in the whole directory | the file is skipped: "No matches found" |
| Grep in `.env` itself | refused |
| Bash `cat .env`, `head -1 .env`, `tail .env`, `sort .env`, `cat /abs/path/.env` | refused |
| Bash `grep -r TOKEN .` | **prints the token** |
| Bash `cat .e*` | **prints the token** |

Read-only commands run without asking, and the rule catches one only when the command text names
the denied path. The lesson is the same as for deleting: if the job does not need a shell, do not
give it one. And a token that must exist should not live in the directory an agent works in.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, the scripted model). Start with what changed.
Nobody has committed since the run, so git knows exactly what it destroyed:

```console
$ cd ~/handbook && git log --oneline && git status --short
8648d84 Handbook as of August
 M docs/getting-started.md
 D drafts/2026-q4-roadmap.md
 D drafts/incident-2026-08-30.md
 D drafts/pricing-v2.md
```

The deletions are in the working tree only. `git restore` takes the files from `HEAD`; with
`--staged --worktree` it also resets the index, in case anything staged the deletion (the grader
tries `git rm`):

```console
$ git restore --source=HEAD --staged --worktree -- drafts docs
$ ls drafts
2026-q4-roadmap.md  incident-2026-08-30.md  pricing-v2.md
```

The job's log is its JSON result. `permission_denials` is empty — nothing was refused, because
nothing was checked:

```console
$ jq '{result, num_turns, permission_denials}' ~/tidy-handbook.log
{
  "result": "Tidied the handbook: fixed a typo in docs/getting-started.md and removed drafts/.",
  "num_turns": 5,
  "permission_denials": []
}
```

The obvious fix is to delete the flag. The run behaves exactly as before — five turns, no denials,
the drafts gone again — because `~/.claude/settings.json` sets the same mode a second time:

```console
$ sed -i '/dangerously-skip-permissions/d' ~/bin/tidy-handbook && ~/bin/tidy-handbook
$ tail -n1 ~/tidy-handbook.log | jq -c '{num_turns, permission_denials}'
{"num_turns":5,"permission_denials":[]}
$ cat ~/.claude/settings.json
{
  "permissions": {
    "defaultMode": "bypassPermissions"
  }
}
```

Next attempt: restore again, empty the user settings, run the job with `--permission-mode dontAsk`,
and write the policy where the team will review it — the project's `.claude/settings.json`,
allowing edits in `docs/` and denying `.env`. The drafts survive, and so do the typos:

```console
$ ~/bin/tidy-handbook
$ head -n -1 ~/tidy-handbook.log
Ignoring 1 permissions.allow entry from .claude/settings.json: this workspace has not been trusted. …
$ tail -n1 ~/tidy-handbook.log | jq -c '[.permission_denials[] | {tool_name, tool_input}]'
[{"tool_name":"Edit","tool_input":{"file_path":"/home/learner/handbook/docs/getting-started.md",…}},
 {"tool_name":"Bash","tool_input":{"command":"rm -rf drafts","description":"Remove clutter"}},
 {"tool_name":"Read","tool_input":{"file_path":"/home/learner/handbook/.env"}}]
```

All three calls were refused: the `rm` and the `.env` read as intended, and the edit because its allow
rule was ignored. The stderr line says why. The allow belongs on the job's command line; the deny
rules can stay in the project file, where they are honoured and reviewed. The job becomes:

```sh
cd "$HOME/handbook" || exit 1
claude -p "Fix the typos in docs/." \
    --permission-mode dontAsk \
    --tools "Read,Edit,Glob,Grep" \
    --allowedTools "Edit(./docs/**)" \
    --max-turns 10 \
    --output-format json > "$HOME/tidy-handbook.log" 2>&1
```

with `.claude/settings.json` denying `Read(./.env)`, `Read(./.env.*)` and `Edit(./drafts/**)`, and
`~/.claude/settings.json` reduced to `{}`. The model replays last night's plan once more:

```console
$ ~/bin/tidy-handbook
$ tail -n1 ~/tidy-handbook.log | jq -c '{num_turns, denials: [.permission_denials[] | .tool_name]}'
{"num_turns":5,"denials":["Read"]}
$ git status --short
 M docs/getting-started.md
?? .claude/
```

The typo is fixed, the `rm` failed as "No such tool available: Bash" (it is not a denial — Bash is
not in the session), and the read of `.env` was refused. The grader then tries harder than last
night's model did:

```
PASS 02_the_job_fixes_typos_and_deletes_nothing: The job fixed a typo in docs/ and refused all 7
     attempts to delete or overwrite.
PASS 03_the_token_never_reaches_the_model: None of the ways the model tried to read the token got it.
     Read /home/learner/handbook/.env: File is in a directory that is denied by your permission settings.
     Bash cat .env: Error: No such tool available: Bash. …
     Grep TOKEN: No matches found
```

One thing the grader cannot undo: the transcript of last night's run is still on disk with the
token in it, and so is the run where only the flag was removed.

```console
$ grep -l hbk_live ~/.claude/projects/*/*.jsonl | wc -l
2
```

In real life the token is now compromised — it was sent to a model provider — and has to be rotated
at the service that issued it. Delete those transcripts, and give the job `--no-session-persistence`
if nobody reads its sessions.

## Common wrong turns

**Removing the flag and calling it done.** A `defaultMode` in any settings file still applies; the
job's behaviour did not change at all. Look at `permission_denials` after every change: an empty
list on a run that tried to delete something means nothing is being checked.

**Putting the allow rules in the project's `.claude/settings.json` for a CI job.** Nobody ever
trusts a CI checkout, so `claude -p` ignores them and the job quietly does nothing. The warning is on
stderr — which the job redirects into its log, so read it.

**Answering with `acceptEdits`.** Edits run without asking — including the Write tool emptying a
draft and rewriting `README.md`. It is a mode for a person watching, not for a job.

**Denying `Bash(rm *)` and keeping Bash.** The model has `/bin/rm`, `find -delete`, `python3`,
`git rm` and a dozen more. Bash rules match text, not intent.

**Denying `Read(./.env)` and keeping Bash.** `grep -r TOKEN .` and `cat .e*` still print it.

**Exporting the token into the job's environment so the model "doesn't need the file".** Anything
the job's process can see, `env` shows the model the moment Bash is available.

**Restoring with `git checkout -- drafts` after something staged the deletion.** `checkout --` takes
files from the index; if `git rm` already removed them from the index, there is nothing there.
`git restore --source=HEAD --staged --worktree` restores both from the commit.

**Deleting the job.** The typo fixes were the point. The goal is a job that can do its one task and
nothing else.

## Cheat sheet

```bash
# what a run did and what was refused
jq '{result, num_turns, is_error, permission_denials}' run.json
claude -p "…" --output-format json 2>run.err >run.json   # keep stderr: trust and config warnings

# the modes, strict to loose
claude -p "…" --permission-mode dontAsk        # unattended: anything not allowed is refused
claude -p "…" --permission-mode acceptEdits    # edits run without asking — not for jobs
claude -p "…" --dangerously-skip-permissions   # = bypassPermissions: disposable machines only

# fewest tools, narrowest allow, caps
claude -p "…" --tools "Read,Edit,Glob,Grep" \
    --allowedTools "Edit(./docs/**)" --max-turns 10 --no-session-persistence

# where modes and rules come from (highest first)
cat /etc/claude-code/managed-settings.json        # managed
#   command line flags / --settings file
cat .claude/settings.local.json                   # local project (honoured untrusted)
cat .claude/settings.json                         # shared project: allow ignored by untrusted -p
cat ~/.claude/settings.json                       # user
grep -rn 'bypassPermissions\|dangerously' ~/.claude .claude ~/bin

# a deny rule for a secret — and why it is not enough with Bash
{ "permissions": { "deny": ["Read(./.env)", "Read(./.env.*)"] } }
#   stops: Read, Grep on the file, cat/head/tail .env   does not stop: grep -r ., cat .e*

# get deleted files back from the last commit
git status --short
git restore --source=HEAD --staged --worktree -- drafts

# what past runs sent the model
ls ~/.claude/projects/*/                 # one .jsonl transcript per session
grep -l 'SECRET_PATTERN' ~/.claude/projects/*/*.jsonl
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — What the model may do
- *Claude Code in a job* (topic journal `claude-code`) — Guards, helpers and outside data
- *Claude Code in a job* (topic journal `claude-code`) — What a session loads

Documentation:

- https://git-scm.com/docs/git-restore
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/settings

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A job runs `claude -p` with `--permission-mode dontAsk` and no allow rules. The model calls Edit on
   a file in the working directory. What happens, and where do you see it?

   > The edit is refused, because in dontAsk anything that would prompt is denied. The model gets a
   > tool error and carries on; the JSON result lists the call in `permission_denials`.

2. Someone removes `--dangerously-skip-permissions` from a job and the model still deletes files
   without a single denial. Name the likeliest cause.

   > A `permissions.defaultMode` of `bypassPermissions` in a settings file — here the user's
   > `~/.claude/settings.json`. Scalar settings come from the highest level that sets them, and the
   > command line no longer sets one.

3. Why are allow rules in a committed `.claude/settings.json` ignored by `claude -p` in a fresh CI
   checkout, while its deny rules still apply?

   > The workspace has not been trusted, and a repository must not be able to grant itself
   > permissions; restricting itself is harmless. Claude Code 2.1.270 ignores project allow entries
   > there and warns on stderr. Put the allow on the command line (`--allowedTools`) or in
   > `--settings`.

4. What is the difference, as the model experiences it, between `--tools "Read,Edit"` and a deny rule
   `Bash`?

   > With `--tools`, Bash is not in the session: it is not offered, and a call fails as "No such tool
   > available". With a deny rule the tool is offered and each call is refused as a permission denial.
   > Both stop the call; removing the tool also keeps it out of the model's plan.

5. A job keeps Bash and denies `Bash(rm *)`. Give three commands that still delete a directory.

   > `/bin/rm -rf drafts`, `find drafts -delete`, `git rm -r drafts` (or `python3 -c
   > "import shutil; shutil.rmtree('drafts')"`). Bash rules match command text; they are not a
   > security boundary. In dontAsk mode with no allow for them they are refused anyway.

6. With `deny: ["Read(./.env)"]` and Bash available, which of `cat .env`, `grep -r TOKEN .` and the
   Read tool on `.env` show the model the token?

   > Only `grep -r TOKEN .`. Read is refused, and `cat .env` names the denied path so it is refused;
   > a read-only command that does not name it runs without asking.

7. Once a model has read a secret, where else does it exist besides the provider's side of the
   request, and what should happen to it?

   > In the session transcript under `~/.claude/projects/<project>/<session>.jsonl` (unless the run
   > used `--no-session-persistence`) and in any log of the job's output. The secret is compromised:
   > rotate it where it was issued, then delete the transcripts.

8. The drafts were removed with `git rm -r drafts` and not committed. Why does
   `git checkout -- drafts` not bring them back, and what does?

   > `checkout -- <path>` copies from the index, and `git rm` already removed them from it.
   > `git restore --source=HEAD --staged --worktree -- drafts` restores the index and the working
   > tree from the last commit.
