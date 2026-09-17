---
title: Claude Code in a job — what it loads, what it may do, and what it costs
topics: [claude-code, ai-services, ai-agents]
minutes: 45
covers: >-
  headless claude -p runs; the five settings levels and workspace trust; permission modes, allow and deny rules; hooks' matchers and exit statuses; subagents; turns, budgets and model choice
---

Claude Code is usually met as an interactive assistant in a terminal. This journal is about the other
way it runs: as a program started by a script, a cron job or a CI workflow, with nobody watching. In
that role it is a small operating environment of its own. It reads configuration from five levels,
loads instructions from `CLAUDE.md` files, starts MCP servers, runs hooks, can hand work to
subagents, and executes tool calls a model chooses — each of which is either allowed, refused or
never offered. A job is safe and cheap when every one of those is decided on purpose.

Everything below was run with Claude Code 2.1.270 in Norboten's claude lab image, where the model is a
local script and every other decision is Claude Code's own — before that image moved to Ubuntu 26.04
(`ubuntu-26.04-claude`), where the six claude labs built on the same behaviour pass again. The six labs of the claude
track each take one of these mechanisms apart; this journal puts them together into one job.

## What you should be able to do after this

- Start a headless run and read what it loaded: model, permission mode, tools, agents, MCP servers.
- Say which settings level a key comes from, and why permission rules behave differently from other keys.
- Shape a job's permissions: a strict mode, the fewest tools, narrow allow rules, and deny rules that
  still apply in an untrusted checkout.
- Use a hook as a guard, a subagent to keep work cheap and contained, and an MCP server for outside data.
- Bound a run's cost with a trigger, a turn cap, a model choice and structured output.
- Find the evidence afterwards: the JSON result, the init event, transcripts and subagent logs.

## The mechanism

### One run, from the outside

`claude -p "<prompt>"` runs one session and exits. Three outputs matter:

- `--output-format json` prints one result object: `result`, `num_turns`, `is_error` and `subtype`
  (`success`, `error_max_turns`, …), `permission_denials`, `total_cost_usd` and `modelUsage` per model.
- `--output-format stream-json --verbose` prints events as they happen; the first, `system/init`,
  records what the session loaded.
- The session transcript, `~/.claude/projects/<cwd with / as ->/<session>.jsonl`, with every tool
  result, and a `subagents/` directory beside it when work was delegated. `--no-session-persistence`
  writes none.

A run authenticates with, in order, a cloud provider, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY` (in
`-p`, always used when present), an `apiKeyHelper`, `CLAUDE_CODE_OAUTH_TOKEN` (a one-year subscription
token from `claude setup-token`), then a login. `--bare` skips every kind of auto-discovery and reads
only API keys, so a subscription-token job cannot use it — and therefore always loads the repository's
`.claude/`, which is part of what the job runs.

### What a session loads

| what | from | loaded by `-p` in an untrusted checkout? |
|---|---|---|
| settings | managed → command line → `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json` | yes, **except allow rules from `.claude/settings.json`** |
| memory | managed, `~/.claude/CLAUDE.md`, every `CLAUDE.md` from the cwd upward, `CLAUDE.local.md`, `@` imports | yes |
| hooks | the `hooks` key of every settings level (merged) | yes |
| subagents | `.claude/agents/`, `~/.claude/agents/`, `--agents`, managed, plugins | yes |
| MCP servers | `.mcp.json`, `claude mcp add` scopes, `--mcp-config` | yes, unless disabled |
| skills | `.claude/skills/`, `~/.claude/skills/`, built-in and plugin skills | yes |

Scalar settings (`model`, `permissions.defaultMode`) come from the highest level that sets them.
Lists (`permissions.allow`, `permissions.deny`, hooks) merge across levels. A deny anywhere wins over an
allow anywhere.

The trust exception is the one that surprises CI authors. A repository could ship a settings file that
allows everything, so a headless run in a workspace nobody has trusted **ignores allow rules from the
shared project file** and warns on stderr, while honouring its deny rules. Put a job's allow rules on
its command line.

### What the model may do

For each tool call the model asks for, Claude Code decides before running anything:

1. Is the tool in the session at all? `--tools` limits the built-in set; a deny rule naming a tool
   without a specifier (`WebFetch`) removes it. A missing tool fails as "No such tool available".
2. Deny rules, then ask rules, then allow rules, from every level.
3. A `PreToolUse` hook, which can refuse with exit status 2 (stderr is the reason) or JSON.
4. The permission mode, for anything no rule decided: `default` prompts, `acceptEdits` lets edits
   through, `dontAsk` refuses, `bypassPermissions` lets everything through. In `-p` a prompt cannot be
   answered, so `dontAsk` is the honest mode for a job.

Rules for Bash match command text and are not a security boundary: `Bash(rm *)` does not match
`find -delete` or `/bin/rm`. Read-only commands run without asking; a `Read` deny stops `cat .env` but
not `grep -r TOKEN .`. When a job needs no shell, the only reliable answer is not to offer one.

### Guards, helpers and outside data

**Hooks** are commands Claude Code runs on events, with the event as JSON on stdin. Matchers are exact,
case-sensitive tool names (`Edit|Write`) or regular expressions. A `PreToolUse` hook blocks only with
exit 2 or a JSON `deny`; exit 1 — and a script that cannot be executed — are non-blocking errors.

**Subagents** are Markdown files with `name`, `description`, and optionally `tools` and `model`. Their
work happens in their own context, which keeps the main conversation short; a narrow subagent on Haiku
is one of the documented cost levers. Without a `tools` line a subagent inherits every tool.

**MCP servers** bring outside tools, named `mcp__<server>__<tool>`. A server has to be enabled,
startable, allowed by that name, and given its credentials — `${VAR}` in `.mcp.json` expands from the
environment, and an unset variable is passed literally.

### What a run costs

Four things multiply:

- **how often it runs** — the trigger (`issues: types: [opened]`, not every issue activity);
- **how many turns** — no limit by default; `--max-turns` and `--max-budget-usd` set one;
- **what each turn costs** — the model, the system prompt and tool definitions sent every turn, the
  context that grows with each tool result, and thinking tokens;
- **how much output** — structured output (`--json-schema`) instead of prose.

Norboten's own jobs, measured on real runs (docs/claude-code-in-norboten.md): a triage label on Haiku
with no tools and thinking off costs $0.0028–0.0038; release notes for 40 commits dropped from 111 s and
$0.070 to 9 s and $0.021 when thinking was turned off for runs without tools; the Sonnet lab-author job
took 15 turns and $0.33, three quarters of its 163,802 input tokens read from cache. The cost figures are
Claude Code's list-price estimate; on a subscription token they count against the plan.

## A failure, walked through

The job: write release notes for a repository into `NOTES.md`. It must not push; a person does. Start
with an empty repository and ask the session what it loaded:

```console
$ claude -p hi --output-format stream-json --verbose 2>/dev/null | head -1 \
    | jq -c '{model, permissionMode, agents, tools: (.tools|length)}'
{"model":"claude-opus-5[1m]","permissionMode":"default","agents":["claude","Explore","general-purpose","Plan","statusline-setup"],"tools":21}
```

No model was named, so the account default — Opus — with 21 tools and the default mode. The project
adds what a team would commit: a `CLAUDE.md` with the rule, a Haiku subagent that only reads, a
`PreToolUse` hook that refuses pushes, and a deny rule for `.env`:

```markdown
# .claude/agents/summariser.md
---
name: summariser
description: Summarises commit messages into user-facing release-note bullets. Use for release notes.
tools: Read, Grep, Glob
model: haiku
---
You turn commit messages into one short, user-facing bullet each. You never edit files.
```

```sh
#!/bin/sh
# .claude/hooks/no-push.sh — PreToolUse, matcher Bash
if jq -r '.tool_input.command // ""' | grep -Eq 'git([[:space:]].*)?[[:space:]]push'; then
    echo "Blocked: a person pushes release notes." >&2
    exit 2
fi
```

```console
$ claude -p hi --output-format stream-json --verbose 2>/dev/null | head -1 | jq -c '{agents}'
{"agents":["claude","Explore","general-purpose","Plan","statusline-setup","summariser"]}
```

The scripted model plays the job the way a model plausibly would: read the log, ask the summariser,
write `NOTES.md`, then commit and push. First with no flags at all:

```console
$ claude -p "Write the release notes." --output-format json 2>/dev/null \
    | jq -c '{num_turns, denials: [.permission_denials[] | .tool_name], models: (.modelUsage|keys)}'
{"num_turns":5,"denials":["Write","Bash"],"models":["claude-haiku-4-5-20251001","claude-opus-5[1m]"]}
$ ls
CLAUDE.md  README.md
```

Nothing was harmed — and nothing was done. In `default` mode the Write would have needed a prompt, and a
headless run cannot answer one, so it was refused; the push was refused too. The subagent did
run on Haiku; the main agent ran on Opus. A job that silently produces nothing is the first failure mode.

Now the job's own command line: a strict mode, an explicit model, allow rules for exactly the calls the
task needs, a cap:

```console
$ claude -p "Write the release notes for the last five commits into NOTES.md." \
    --permission-mode dontAsk --model sonnet \
    --allowedTools "Bash(git *),Write(./NOTES.md),Edit(./NOTES.md),Agent" \
    --max-turns 12 --output-format json 2>/dev/null \
    | jq -c '{num_turns, denials: [.permission_denials[] | .tool_name], models: (.modelUsage|keys)}'
{"num_turns":5,"denials":["Bash"],"models":["claude-haiku-4-5-20251001","claude-sonnet-5"]}
```

`Bash(git *)` is broader than the task needs — it allows `git push` — and it is what a hurried job
author writes. The hook is what stopped it. The transcript shows each tool result in order:

```console
$ jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result")
         | .content | if type=="array" then .[0].text else . end' "$s" | cut -c1-90
a8008cb init
Async agent launched successfully. (This tool result is internal metadata — never quote or paste
File created successfully at: /home/learner/notes/NOTES.md (file state is current in your context
PreToolUse:Bash hook error: [$CLAUDE_PROJECT_DIR/.claude/hooks/no-push.sh]: Blocked: a person pushes
$ cat "${s%.jsonl}"/subagents/*.meta.json | jq -c '{agentType}'
{"agentType":"summariser"}
$ git log --oneline -1 origin/main
a8008cb init
```

The log was read, the summariser ran, the notes were written, and the whole compound command
`git add … && git commit … && git push` was refused before any part of it ran — so nothing was committed
either. Two layers did two jobs: the allow rules defined the task, the hook enforced the one rule that
must hold even when the rules are written loosely. With `Bash(git log *)` instead of `Bash(git *)` the
push is refused by the permission check itself, and the hook becomes the second line rather than the
only one.

What is left is cost and evidence. For CI the same command gains `--no-session-persistence` (or keeps
transcripts as an artifact on purpose), a trigger that runs it once per release, and a workflow
`timeout-minutes`. If the notes are consumed by a script rather than read by a person, `--json-schema`
turns them into fields.

## Common wrong turns

**Reading the result and not the denials.** A run that was refused everything still ends with
`is_error: false` and a cheerful `result`. `permission_denials` and the transcript's tool results say
what happened.

**`--dangerously-skip-permissions` because "it kept asking".** It was asking because the job had not said
what it needs. Say it with allow rules and `dontAsk`.

**Committing allow rules to `.claude/settings.json` for a CI job.** An untrusted checkout ignores them.
Deny rules and hooks there are fine; allows go on the command line.

**`Bash(rm *)` as a safety measure.** It matches text. If the job needs no shell, `--tools` without Bash.

**Hooks that exit 1.** Every shell script's "error" is a hook's "carry on". Exit 2, reason on stderr.

**A subagent with no `tools` line.** It inherits everything, including what the main session was given.

**Forgetting what is sent every turn.** `CLAUDE.md`, tool definitions and the default system prompt ride
along on each request. Short `CLAUDE.md`, few tools, and `--system-prompt` for jobs that need none of
Claude Code's own instructions.

**No turn cap.** A model that keeps calling tools keeps billing. In the lab image an endless scripted
model drove 1,186 turns in 25 seconds.

**`--bare` with a subscription token.** Not logged in.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| a headless job does things nobody allowed | `bypassPermissions`, or allow rules broader than the task | the job's flags; `permission_denials` in the JSON result |
| allow rules in the project are ignored in CI | the checkout is untrusted: project allow rules need trust | the run's stderr; `--allowedTools` on the command line |
| a hook never runs | the matcher does not name the tool exactly, or the script is not executable | `--debug`; `ls -l .claude/hooks`; the matcher's case |
| a PreToolUse hook sees the call and does not stop it | it exits 1 instead of 2, or writes its reason to stdout | the hook's exit status and stderr |
| a subagent is never used | its file is misnamed, its tools misspelled, or it is not where Claude Code looks | the session transcript; `.claude/agents/` |
| a job's bill keeps growing | no `--max-turns`, no `--max-budget-usd`, a large model for a small task | the result's `num_turns` and `total_cost_usd` |

## Cheat sheet

```bash
# what a session loaded
claude -p hi --output-format stream-json --verbose 2>/dev/null | head -1 \
  | jq '{model, permissionMode, apiKeySource, agents, mcp_servers, tools, claude_code_version}'

# a job-shaped run
claude -p "…" --permission-mode dontAsk --model sonnet \
  --tools "Read,Edit,Glob,Grep" --allowedTools "Edit(./docs/**)" \
  --max-turns 10 --max-budget-usd 1.00 --no-session-persistence --output-format json

# a classification: no tools, structured answer, no thinking
MAX_THINKING_TOKENS=0 claude -p "…" --model haiku --tools "" --max-turns 3 \
  --json-schema '{"type":"object","properties":{"label":{"type":"string"}},"required":["label"]}' \
  --output-format json | jq -r '.structured_output.label'

# afterwards
jq -c '{subtype, num_turns, is_error, permission_denials, total_cost_usd, models: (.modelUsage|keys)}' run.json
s=$(ls -t ~/.claude/projects/<project>/*.jsonl | head -1)
jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content' "$s"
ls "${s%.jsonl}"/subagents/

# levels, highest first: managed, command line, .claude/settings.local.json, .claude/settings.json, ~/.claude/settings.json
cat /etc/claude-code/managed-settings.json     # Linux; must be readable (0644)

# hooks: JSON on stdin; exit 2 blocks PreToolUse
jq -r '.tool_input.command // .tool_input.file_path // ""'
echo "reason" >&2; exit 2

# subagent: .claude/agents/<name>.md with name, description, tools, model
# MCP: .mcp.json; tools are mcp__<server>__<tool>; "${VAR}" from the environment
claude -p hi --output-format stream-json --verbose | head -1 | jq '.mcp_servers'
```

## Exercises

1. Run `claude -p` in a fresh directory with a deny rule and a scripted request for the denied tool;
   read `permission_denials`.
2. Write a PreToolUse hook that blocks `git push`, and test it with exit status 1 and with 2.
3. Put the same setting at three levels (user, shared project, local project) and find which one wins
   with a run that prints it.
4. Define a subagent with a `tools:` list and a `model:`, invoke it, and confirm from the transcript
   which model and tools it ran with.
5. Run the same job with `--max-turns 2` and without, against a scripted model that never stops.

## Sources

- Settings and their precedence: https://code.claude.com/docs/en/settings
- Permissions: https://code.claude.com/docs/en/permissions
- Hooks: https://code.claude.com/docs/en/hooks
- Subagents: https://code.claude.com/docs/en/sub-agents
- Headless runs and the CLI: https://code.claude.com/docs/en/headless, https://code.claude.com/docs/en/cli-reference

## Review

1. A `claude -p` run ends with `is_error: false` and did none of its work. Where do you look first, and
   what is the likeliest cause?

   > At `permission_denials` in the JSON result (and the tool results in the transcript). The likeliest
   > cause is a mode in which the calls would have prompted — `default` in `-p` — or allow rules that were
   > never honoured, such as ones in an untrusted checkout's `.claude/settings.json`.

2. Which one field of the init event tells you which authentication a run used, and why does it matter
   for a CI job on a subscription?

   > `apiKeySource`. A stray `ANTHROPIC_API_KEY` is used in `-p` whenever present, so a job meant to run on
   > a subscription token may be billing an API key instead.

3. List the settings levels in precedence order and explain why a deny rule in the lowest level still
   blocks a call allowed on the command line.

   > Managed, command line, local project, shared project, user. Permission rules are lists that merge
   > across levels, and deny is evaluated before allow, so a deny at any level wins.

4. Name the four steps a tool call passes before it runs.

   > Whether the tool exists in the session (`--tools`, bare deny rules); deny, ask and allow rules;
   > `PreToolUse` hooks; the permission mode for anything left undecided.

5. In the walkthrough, `Bash(git *)` was allowed and the push was still refused. By what, and what would
   have refused it without that?

   > The `PreToolUse` hook, exiting 2. With a narrower allow such as `Bash(git log *)`, `dontAsk` would have
   > refused the compound command because no rule allowed it.

6. Why is a subagent a cost lever as well as an organisation tool?

   > Its reading and tool results stay in its own context; only its result returns, so the main
   > conversation — resent every turn — stays short. It can also be pinned to a cheaper model.

7. Give four independent ways to bound a job's cost.

   > A narrow trigger, a turn cap (`--max-turns`) or budget (`--max-budget-usd`), a smaller model with
   > fewer tools and less context (and thinking off where nothing needs thinking), structured output
   > instead of prose. A workflow timeout is the backstop.

8. Why can a CI job authenticated with `CLAUDE_CODE_OAUTH_TOKEN` not use `--bare`, and what follows for
   the repository it runs in?

   > Bare mode never reads OAuth tokens, only API keys. So the job loads the repository's `.claude/`
   > (hooks, subagents, MCP servers, `CLAUDE.md`) — which runs as part of the job and must be reviewed like
   > code.
