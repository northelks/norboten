---
title: An MCP server has to be enabled, startable, allowed and given its secret
topics: [claude-code, ai-agents]
minutes: 35
---

The Model Context Protocol lets Claude Code use tools that live outside it: a ticket queue, a
database, an internal API. A project declares its servers in `.mcp.json`, Claude Code starts each
one when a session starts, asks it which tools it has, and offers those tools to the model under
names of its own. Between "declared" and "the model gets the queue" there are four separate gates,
and a job that fails at any of them fails the same way — the model has nothing to call, or its call
comes back empty, and it writes a digest that says so.

This lab's digest fails at all four. The server is disabled by a settings file someone forgot about;
its command does not exist on the machine; the job allows a tool name that does not exist; and the
token reaches the server as the literal text `${TICKET_TOKEN}`. Last Friday's attempt at a fix also
committed the token.

## What you should be able to do after this

- Declare a stdio MCP server in `.mcp.json` and know every place that can disable or override it.
- See whether a headless run's servers connected, and read a server's own messages.
- Name an MCP tool the way permission rules and hooks see it, and allow exactly that tool.
- Pass a server a secret from the job's environment with `${VAR}`, and predict what an unset variable
  does.
- Get a secret out of a repository — and know why that is not enough.

## The mechanism

### Declaring a server

`.mcp.json` at the project root is the **project** scope, meant to be committed:

```json
{
  "mcpServers": {
    "tickets": {
      "type": "stdio",
      "command": "python3",
      "args": ["/opt/tickets/tickets_mcp.py"],
      "env": {"TICKETS_TOKEN": "${TICKETS_TOKEN}"}
    }
  }
}
```

A stdio server is a program Claude Code starts and talks JSON-RPC to over its stdin and stdout; an
`http` server is a URL with optional `headers`. The same name can also exist in the **local** scope
(this project, stored in `~/.claude.json`, set with `claude mcp add`) and the **user** scope (all
projects). When it does, local beats project beats user, and **the whole entry is taken** — fields
are not merged.

Interactive sessions ask before using a project's `.mcp.json` servers. A headless `-p` run loads them
without asking. Three things keep one out:

- `"disabledMcpjsonServers": ["tickets"]` in a settings file;
- `--strict-mcp-config` with `--mcp-config <file>`, which uses only the servers in that file;
- `--setting-sources`, which chooses which settings files load.

`"enableAllProjectMcpServers": true` and `"enabledMcpjsonServers"` approve servers; they do not
start one that is disabled elsewhere.

### Variables in the configuration

`${VAR}` and `${VAR:-default}` are expanded from Claude Code's own environment in `command`, `args`,
`env`, `url` and `headers`. A variable that is not set and has no default is **left as it is**: the
server starts and receives the text `${TICKET_TOKEN}`. `claude mcp list` notices, in its diagnostics:

```
[Contains warnings] Project config (shared via .mcp.json)
 └ [Warning] [tickets] mcpServers.tickets: Missing environment variables: TICKET_TOKEN
```

This is the right way to give a server a secret: the committed file names the variable, the job's
environment supplies the value, and nothing secret is in the repository.

### Did it connect?

The final `--output-format json` result says nothing per server. Two things do:

- the **init event** of `--output-format stream-json --verbose`, the first line a run prints, with
  `mcp_servers` (`connected`, `failed`, …) and the tool list;
- `--debug-file <path>`, which records each server's start, its connection and **its stderr**.

In a project nobody has trusted, `claude mcp list` shows `.mcp.json` servers as "⏸ Pending approval
(run `claude` to approve)" instead of checking them — which says nothing about whether `-p` can
start them.

A stdio server must keep stdout for JSON-RPC and log to stderr. (Claude Code 2.1.270 skipped a stray
non-JSON line on stdout in testing, but a server that prints its logs there is one careless `print`
from corrupting a message.)

### Tool names and permissions

A server's tool `list_tickets` becomes **`mcp__tickets__list_tickets`**, with the server's name from
the configuration. Permission rules, `--allowedTools`, hooks' matchers and `permission_denials` all
use that name; `mcp__tickets` (or `mcp__tickets__*`) covers all of a server's tools. In `dontAsk`, an MCP tool that is
not allowed is refused like any other.

### Where secrets end up

A token in a committed file is in every clone and in history. `git rm --cached` and a new commit
remove it from the working tree and from the latest commit, not from the commits before: anyone with
the repository can still read it with `git show <old-commit>:<file>`. A committed secret is a leaked
secret — rotate it at the service that issued it. Rewriting history (`git filter-repo`) is a
separate, disruptive step for a shared repository, and does not help with copies already fetched.

`.claude/settings.local.json` is meant to stay on one machine. Claude Code adds it to git's global
excludes only when Claude Code itself creates the file; one created by hand must be ignored by hand.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, the scripted model). The digest ran without a
single denial and produced nothing useful:

```console
$ tail -n1 ~/digest.json | jq -c '{result, num_turns, permission_denials}'
{"result":"Morning digest: see the tickets above.","num_turns":2,"permission_denials":[]}
$ git ls-files
.claude/settings.local.json
.mcp.json
README.md
```

No denial, because the tool the model asked for did not exist in the session. The init event shows no
server at all, and `claude mcp list` has nothing to list either — but its diagnostics already spot the
variable:

```console
$ set -a; . ~/.config/support-digest/env; set +a
$ claude -p "hi" --output-format stream-json --verbose 2>/dev/null \
    | jq -c 'select(.type=="system" and .subtype=="init") | {mcp_servers}'
{"mcp_servers":[]}
$ claude mcp list
No MCP servers configured. Use `claude mcp add` to add a server.
MCP config diagnostics ⚠
 └ [Warning] [tickets] mcpServers.tickets: Missing environment variables: TICKET_TOKEN
$ cat .claude/settings.local.json
{
  "disabledMcpjsonServers": ["tickets"],
  "env": {"TICKETS_TOKEN": "tk_live_…"}
}
```

The local settings file switches the server off, holds the token, and is tracked. Take it out of the
repository and ignore it; now the server is attempted, and fails:

```console
$ git rm -q --cached .claude/settings.local.json && rm .claude/settings.local.json
$ echo .claude/settings.local.json >> .gitignore
$ claude -p "hi" --output-format stream-json --verbose 2>/dev/null | jq -c 'select(.subtype=="init") | {mcp_servers}'
{"mcp_servers":[{"name":"tickets","status":"failed"}]}
$ command -v python python3
/usr/bin/python3
```

`python` does not exist here. With `"command": "python3"` the server connects and its tool appears —
and the job refuses it:

```console
$ claude -p "hi" --output-format stream-json --verbose 2>/dev/null \
    | jq -c 'select(.subtype=="init") | {mcp_servers, tools: [.tools[] | select(startswith("mcp"))]}'
{"mcp_servers":[{"name":"tickets","status":"connected"}],"tools":["mcp__tickets__list_tickets"]}
$ ~/bin/support-digest; tail -n1 ~/digest.json | jq -c '[.permission_denials[] | .tool_name]'
["mcp__tickets__list_tickets"]
```

The job allows `mcp__ticket__list_tickets` — one letter short. With the name corrected, nothing is
refused, and the session transcript shows what the tool returned:

```console
$ sed -i 's/mcp__ticket__list_tickets/mcp__tickets__list_tickets/' ~/bin/support-digest && ~/bin/support-digest
$ s=$(ls -t ~/.claude/projects/-home-learner-support-digest/*.jsonl | head -1)
$ jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result")
         | .content | if type=="array" then .[0].text else . end' "$s" | tail -1
401 unauthorized: bad TICKETS_TOKEN
```

The server is running and answering; it simply got `${TICKET_TOKEN}`. A debug log confirms the server
itself is healthy — its stderr is captured there:

```console
$ claude -p "hi" --debug-file /tmp/claude-debug.log --output-format json >/dev/null 2>&1
$ grep tickets /tmp/claude-debug.log | cut -c26- | head -3
[DEBUG] MCP server "tickets": Starting connection with timeout of 30000ms
[ERROR] MCP server "tickets" Server stderr: tickets: starting
[DEBUG] MCP server "tickets": Successfully connected (transport: stdio) in 12ms
```

(The `[ERROR]` label is only how Claude Code files anything a server writes to stderr.) Correct the
variable to `${TICKETS_TOKEN}`, which the job exports, and commit:

```console
$ sed -i 's/\${TICKET_TOKEN}/\${TICKETS_TOKEN}/' .mcp.json
$ git add -A && git commit -qm "tickets server: python3, the right variable, no local settings in git"
$ git grep -c tk_live HEAD || echo "HEAD clean"
HEAD clean
$ git grep -l tk_live $(git rev-list --all)
ec87913c2320a84b0f5069d57b51389fa7dcf916:.claude/settings.local.json
```

The latest commit is clean; the first one still holds the token, which is why it must be rotated.

```
PASS 01_the_server_starts_for_the_job: The tickets server started; the model was offered mcp__tickets__list_tickets.
PASS 02_the_job_may_call_the_tool: The job called mcp__tickets__list_tickets without being refused.
PASS 03_the_tool_is_authorised: The tool returned the open queue, TCK-6821 included.
PASS 04_no_token_in_the_repository: No tracked file, and nothing in the latest commit, holds the token.
```

## Common wrong turns

**Trusting `claude mcp list` in a project nobody trusted.** "Pending approval" is about interactive
approval; `-p` starts the server anyway. Use the init event or a debug log.

**Pasting the token into `.mcp.json` to make the 401 go away.** It works, and it commits the secret
again. Name the variable; let the job's environment carry the value.

**Deleting `settings.local.json` without ignoring it.** The next person to create one commits it again.

**Allowing the whole server when the job needs one tool.** `mcp__tickets` (or `mcp__tickets__*`)
allows every tool the server has today and every tool it adds next month. A job that lists tickets
should be allowed `mcp__tickets__list_tickets`.

**Editing the server.** It worked all along. When a server answers "unauthorized", find out what it
was given before changing what it checks.

**Running the job's `claude` without the job's environment.** The job sources
`~/.config/support-digest/env`; a `claude -p` in a fresh shell has no `TICKETS_TOKEN`, so every test
from that shell reproduces the 401 whether or not `.mcp.json` is fixed.

**Declaring success when the latest commit is clean.** History still has the token. Rotate it.

## Cheat sheet

```bash
# the project's servers, and the files that can switch them off
cat .mcp.json
grep -rn 'McpjsonServers\|enableAllProjectMcpServers' .claude/ ~/.claude/settings.json 2>/dev/null
claude mcp list                         # config diagnostics (missing variables); untrusted: "pending"

# did this run's servers connect?
claude -p "hi" --output-format stream-json --verbose 2>/dev/null \
  | jq -c 'select(.type=="system" and .subtype=="init") | {mcp_servers, tools: [.tools[]|select(startswith("mcp"))]}'
claude -p "hi" --debug-file /tmp/claude-debug.log >/dev/null; grep 'MCP server' /tmp/claude-debug.log

# run the server's command by hand, with the job's environment
set -a; . ~/.config/support-digest/env; set +a
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 /opt/tickets/tickets_mcp.py

# names and permissions
#   tool list_tickets on server tickets  →  mcp__tickets__list_tickets
claude -p "…" --permission-mode dontAsk --allowedTools "mcp__tickets__list_tickets"
claude -p "…" --strict-mcp-config --mcp-config ci-mcp.json   # only these servers

# secrets: name the variable, never the value
"env": {"TICKETS_TOKEN": "${TICKETS_TOKEN}"}        # unset → passed literally
"env": {"LOG_LEVEL": "${LOG_LEVEL:-info}"}          # with a default

# a committed secret
git rm --cached .claude/settings.local.json && echo .claude/settings.local.json >> .gitignore
git grep -l "$TOKEN" $(git rev-list --all)          # still in history → rotate it
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

Documentation:

- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/permissions
- https://git-scm.com/docs/gitignore

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. Name four independent reasons a `.mcp.json` server's tool is unusable in a headless job.

   > The server is disabled (`disabledMcpjsonServers`, or excluded by `--strict-mcp-config` /
   > `--setting-sources`); its command cannot start; the job does not allow the tool by its
   > `mcp__server__tool` name in a strict mode; the server starts but is given a wrong credential.

2. How do you see whether each MCP server connected during a `claude -p` run?

   > Run with `--output-format stream-json --verbose` and read `mcp_servers` in the first event (type
   > `system`, subtype `init`), or use `--debug-file`, which logs each server's start and stderr.

3. What does a stdio server receive for `"TOKEN": "${TICKET_TOKEN}"` when `TICKET_TOKEN` is unset?

   > The literal string `${TICKET_TOKEN}`. Unset variables without a `:-default` are not expanded;
   > `claude mcp list` reports them as missing in its diagnostics.

4. A server named `tickets` offers `list_tickets`. Write the rule that allows only that tool, and the
   one that allows all its tools.

   > `mcp__tickets__list_tickets`; `mcp__tickets`.

5. The same server name is configured with `claude mcp add` (local scope) and in `.mcp.json`. Which
   configuration is used, and are their `env` blocks combined?

   > The local one: local beats project beats user. The whole entry is taken; fields are not merged.

6. Why does `claude mcp list` saying "Pending approval" not tell you whether the digest job can use the
   server?

   > It reflects interactive approval in a project nobody trusted. `-p` loads `.mcp.json` servers
   > without asking, so the job may start it anyway (or fail to, for other reasons).

7. After `git rm --cached` of a file holding a token and a new commit, `git grep` over `HEAD` finds
   nothing. Is the token safe?

   > No. Earlier commits still contain it (`git grep` over `git rev-list --all` finds it), and every
   > clone has them. Rotate the token; rewriting history is a separate and disruptive step.

8. Why should a stdio MCP server log to stderr?

   > Its stdout is the JSON-RPC channel Claude Code reads. Anything else there risks corrupting or
   > confusing messages; stderr is captured separately (visible in a debug log).
