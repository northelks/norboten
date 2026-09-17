---
title: A subagent exists only where Claude Code looks, with the keys it requires
topics: [claude-code, ai-agents]
minutes: 30
---

A subagent is a Markdown file: a few lines of YAML frontmatter and a system prompt. Teams put real
effort into the prompt — the payments team's security reviewer lists exactly what to look for and
how to report it — and almost none into the six lines above it. Those six lines decide whether the
agent exists at all, which tools it holds and which model it bills to.

When the definition is wrong, nothing fails loudly. The main agent asks for the reviewer, Claude
Code tells it no such agent exists, and the main agent does the review itself, on its own model
with its own tools, and reports success. The job's JSON result is indistinguishable from a real
review. This lab's reviewer is wrong four ways: the wrong directory, a misspelled required key, no
tool list, and a model nobody budgeted for.

## What you should be able to do after this

- Put a project or user subagent where Claude Code finds it, and know which definition wins when
  the same name exists in several places.
- Write the frontmatter a subagent requires, and know which mistakes hide it completely.
- Restrict a subagent's tools, and predict what it gets when the list is missing or misspelled.
- Pin the model a subagent runs on, independently of the session.
- Find out, after a headless run, whether a subagent really ran — and on what.

## The mechanism

### Where subagents come from

Claude Code assembles its list of subagents at startup from several places. When two define the same
`name`, the higher priority wins:

| priority | source |
|---|---|
| 1 | managed settings (an organisation's) |
| 2 | `--agents '<json>'` on the command line, for one session |
| 3 | **project**: `.claude/agents/*.md`, scanned recursively |
| 4 | **user**: `~/.claude/agents/*.md` |
| 5 | plugins |

A subagent's identity is its `name` field, not its file name. A directory that is almost right —
`.claude/agent/`, `.claude/subagents/`, `agents/` at the project root — is simply not read.
Claude Code also ships built-in agents (`general-purpose`, `Explore`, `Plan` and others), which is
the list it offers when a requested name is missing:

```
Agent type 'security-reviewer' not found. Available agents: claude, Explore, general-purpose, Plan, statusline-setup
```

A headless `-p` run loads project subagents without a trust dialog, like hooks and `CLAUDE.md`.

### The frontmatter

```markdown
---
name: security-reviewer
description: Reviews a diff for security problems before it merges. Use it for every pre-merge review.
tools: Read, Grep, Glob
model: haiku
---
You are the payments team's security reviewer. …
```

- `name` — required; lower-case letters and hyphens.
- `description` — required; this is what Claude reads to decide when to delegate, so it should say
  when, not only what. "Use proactively" encourages automatic delegation.
- `tools` — optional; a comma-separated list of tool names **as Claude Code spells them**. Omitted:
  the subagent inherits every tool of the session that starts it, MCP tools included.
- `model` — optional; `haiku`, `sonnet`, `opus`, a full model id, or `inherit`. Omitted: the
  subagent uses its default (the session's model).
- Others: `disallowedTools`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`,
  `background`, `effort`, `isolation: worktree`, `color`.

The frontmatter is read only if `---` is the first line. The body is the subagent's **whole** system
prompt: it does not also get Claude Code's.

What each mistake does, verified with Claude Code 2.1.270 by a model that asks for the agent by name:

| definition | result |
|---|---|
| correct, in `.claude/agents/` | the subagent runs, with `Read, Grep, Glob`, on Haiku |
| correct, in `.claude/agent/` | "not found" |
| `desc:` instead of `description:` | "not found" |
| no frontmatter delimiters | "not found" |
| no `tools:` line | runs with Agent, Bash, Edit, Write, WebFetch, WebSearch and the rest |
| `tools: read, grep` | "Async agent launched successfully" — and the subagent never sends a request |

The last row is the nastiest. No listed name resolves to a tool, so the subagent cannot start, yet the
main agent is told it launched.

### What the subagent's tools and model cost

A subagent's tools are a security boundary in a way the main agent's prompt is not: a reviewer that
holds `Edit` can "fix" what it reviews, and one that holds `Bash` can run what it reads. The session's
permission mode still applies — in this lab's `dontAsk` job an edit would be refused — but a subagent
definition is shared by every session that uses it, including interactive ones where a person clicks
"allow". Restrict it where it is defined.

The model matters for money. A subagent that names no model runs on the session's; this job's session
defaults to Opus, so every daily review ran there. `model: haiku` pins the reviewer regardless of who
starts it.

### Evidence that a subagent ran

The job's JSON result reports the main agent's final text and `modelUsage` per model; it says nothing
reliable about delegation. The session transcript does. Each run writes
`~/.claude/projects/<project>/<session>.jsonl`, and a session that delegated has a directory beside it:

```
<session>.jsonl
<session>/subagents/agent-<id>.jsonl        the subagent's own conversation
<session>/subagents/agent-<id>.meta.json    {"agentType": "security-reviewer", …}
```

The tool results in the main transcript show "not found"; the subagent's transcript shows the model
each of its turns used.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, the scripted model). The job's result claims a
review:

```console
$ tail -n1 ~/review.json | jq -c '{result, num_turns, is_error}'
{"result":"Review finished: see the findings above.","num_turns":2,"is_error":false}
```

The transcript of that session says what the Agent tool actually answered:

```console
$ f=$(ls -t ~/.claude/projects/-home-learner-payments/*.jsonl | head -1)
$ jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content' "$f"
Agent type 'security-reviewer' not found. Available agents: claude, Explore, general-purpose, Plan, statusline-setup
$ find .claude -type f
.claude/agent/security-reviewer.md
```

Moving the file to `.claude/agents/` changes nothing:

```console
$ mkdir -p .claude/agents && mv .claude/agent/security-reviewer.md .claude/agents/ && rmdir .claude/agent
$ ~/bin/review-diff
$ jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content' \
    "$(ls -t ~/.claude/projects/-home-learner-payments/*.jsonl | head -1)"
Agent type 'security-reviewer' not found. Available agents: claude, Explore, general-purpose, Plan, statusline-setup
$ head -5 .claude/agents/security-reviewer.md
---
name: security-reviewer
desc: Reviews a diff for security problems before it merges. Use it for every pre-merge review.
model: opus
---
```

`desc:` is not `description:`. With that fixed, the session grows a `subagents/` directory, and the
review really runs in the reviewer:

```console
$ sed -i 's/^desc: /description: /' .claude/agents/security-reviewer.md && ~/bin/review-diff
$ ls ~/.claude/projects/-home-learner-payments/f53f961e-*/subagents
agent-ac82c9a07e4fb4461.jsonl  agent-ac82c9a07e4fb4461.meta.json
$ cat ~/.claude/projects/-home-learner-payments/f53f961e-*/subagents/*.meta.json
{"agentType":"security-reviewer","description":"Pre-merge security review","toolUseId":"toolu_fake_000004",
 "spawnDepth":1,"requestShape":"background","requestNonInteractive":true}
$ jq -c 'select(.type=="assistant") | {model: .message.model}' …/subagents/agent-*.jsonl | head -1
{"model":"claude-opus-5"}
```

It runs — on Opus. The grader, at this point, also sees what the reviewer was offered:

```
PASS 01_the_review_runs_in_the_reviewer: The security-reviewer subagent ran the review (1 request(s) of its own).
FAIL 02_the_reviewer_can_only_read: The reviewer is offered tools beyond reading: Agent, Bash, Edit,
     EnterWorktree, ExitWorktree, NotebookEdit, SendMessage, Skill, TaskStop, WebFetch, WebSearch, Write.
FAIL 03_the_reviewer_runs_on_haiku: The reviewer asks for claude-opus-5, not Haiku.
     reviewer model: claude-opus-5
     main agent model: claude-opus-5
```

Two more lines of frontmatter:

```console
$ sed -i 's/^model: opus$/model: haiku\ntools: Read, Grep, Glob/' .claude/agents/security-reviewer.md
$ ~/bin/review-diff
$ jq -c 'select(.type=="assistant") | {model: .message.model}' …/subagents/agent-*.jsonl | head -1
{"model":"claude-haiku-4-5-20251001"}
```

```
PASS 01_the_review_runs_in_the_reviewer: The security-reviewer subagent ran the review (1 request(s) of its own).
PASS 02_the_reviewer_can_only_read: The reviewer is offered only Glob, Grep, Read.
PASS 03_the_reviewer_runs_on_haiku: The reviewer runs on claude-haiku-4-5-20251001.
     main agent model: claude-opus-5
```

The main agent still runs on Opus; the job could say `--model sonnet` too. That is a separate choice
from the reviewer's, which is the point of pinning it in the definition.

## Common wrong turns

**Trusting the job's result.** "Review finished" was written by the main agent after it was told the
reviewer did not exist. Read the tool results in the transcript, or look for `subagents/`.

**Fixing only the directory.** With `desc:` the file is still not a subagent. Both faults hide it, so
either fix alone looks like "no change".

**Writing `tools: read, grep`.** Case matters. The launch is reported as successful and nothing runs.

**Leaving `tools` out "so it can look around".** It can also edit, run commands and fetch URLs. A
reviewer reads.

**Setting `--model haiku` on the job.** It changes the main agent; a subagent with `model: opus` still
asks for Opus. Pin the subagent's model in its file.

**Putting the reviewer in `~/.claude/agents/`.** It works on your machine and nowhere else — not in CI,
not for a teammate. A project's agents belong in the project, reviewed with its code.

**Renaming the file to "fix" the name.** The name is the `name` field. Two files with the same `name`
at the same level is an ambiguity you do not want; at different levels, the higher priority silently
wins.

## Cheat sheet

```bash
# where Claude Code looks (project wins over user)
ls .claude/agents/ ~/.claude/agents/

# a minimal, restricted subagent
cat > .claude/agents/security-reviewer.md <<'EOF'
---
name: security-reviewer
description: Reviews a diff for security problems before it merges. Use it for every pre-merge review.
tools: Read, Grep, Glob
model: haiku
---
You are the security reviewer. …
EOF

# one-off agents for a single session, without files
claude -p "…" --agents '{"reviewer": {"description": "Reviews diffs", "prompt": "You review.", "tools": ["Read"], "model": "haiku"}}'

# did the last session delegate, to what, on which model?
s=$(ls -t ~/.claude/projects/<project>/*.jsonl | head -1)
jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | .content' "$s"
cat "${s%.jsonl}"/subagents/*.meta.json
jq -c 'select(.type=="assistant") | .message.model' "${s%.jsonl}"/subagents/agent-*.jsonl | sort | uniq -c

# models per run, main agent and subagents together
jq '.modelUsage | keys' run.json
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — What the model may do
- *Claude Code in a job* (topic journal `claude-code`) — What a run costs

Documentation:

- https://code.claude.com/docs/en/sub-agents

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A subagent file with valid frontmatter sits in `.claude/agent/`. What does the model get when it
   asks for the agent by name, and what does the main agent typically do next?

   > "Agent type '…' not found", with the list of agents Claude Code does know. The main agent carries
   > on without it — usually doing the work itself and reporting success.

2. Which two frontmatter keys are required, and what is the second one for?

   > `name` and `description`. The description is what Claude reads to decide when to delegate to the
   > subagent; without it the file is not loaded as a subagent at all.

3. A subagent has no `tools:` line. What can it do?

   > Everything the starting session can: it inherits all tools, including Bash, Edit, Write, web
   > tools and MCP tools. The session's permission rules still apply to its calls.

4. `tools: read, grep` — what happens when the subagent is requested, and why is the tool result
   misleading?

   > No name resolves to a tool (names are case-sensitive), so the subagent never runs. Claude Code
   > 2.1.270 still tells the main agent the background agent launched successfully.

5. The job runs with `--model haiku`, and the reviewer's file says `model: opus`. Which model does the
   review use?

   > Opus. A subagent's own `model` overrides the session's; only `inherit` or an omitted model follows
   > the session.

6. The same `name` is defined in `.claude/agents/` and in `~/.claude/agents/`. Which is used, and what
   outranks both?

   > The project's (priority 3 beats the user's 4). Managed agents and `--agents` on the command line
   > outrank both.

7. After a headless run, where do you find proof that a subagent ran, and on which model?

   > In the session's directory beside its transcript:
   > `~/.claude/projects/<project>/<session>/subagents/agent-<id>.meta.json` names the agent type, and
   > the model of each assistant turn is in `agent-<id>.jsonl`.

8. Why restrict a reviewer's tools in its definition rather than relying on the job's `dontAsk` mode?

   > The definition is shared by every session that uses the agent, including interactive ones where a
   > person may approve an edit. Restricting tools where the agent is defined holds everywhere; a
   > job's permission mode protects only that job.
