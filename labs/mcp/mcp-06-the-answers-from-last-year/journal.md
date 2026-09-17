---
title: The Answers From Last Year — Claude Code's MCP scopes, and which one wins
topics: [mcp, claude-code]
minutes: 25
---

Claude Code reads MCP server definitions from three places, and the same name can appear in more than
one. The repository's `.mcp.json` is the one everybody reviews; the others live in `~/.claude.json`,
outside any repository, where a colleague's experiment from last year can sit unnoticed for ever. When
two places define `docs`, one wins, and it is not necessarily the file you are looking at. This lab's
team kept reading a correct `.mcp.json` while their answers came from somewhere else — and, while
looking, found the service key committed in the file they were reading.

## What you should be able to do after this

- Name Claude Code's three MCP scopes, where each is stored, and which wins for a project.
- Find every definition of a server name and the one in effect, with `claude mcp`.
- Remove a definition from the right scope without touching the others.
- Keep a server's secret out of `.mcp.json` with variable expansion, and know what it does when unset.
- Say what is left to do when a secret has already been committed.

## The mechanism

### Three scopes

- **project** — `.mcp.json` at the repository's root, committed and shared: what the team agreed on.
- **local** — `~/.claude.json`, under `projects["/path/to/repo"].mcpServers`: yours, for this project
  only, never committed. `claude mcp add` writes here by default.
- **user** — `~/.claude.json`, top-level `mcpServers`: yours, for every project.

### Which one wins

For a name defined in more than one scope, the more personal definition wins for this project: local,
then project, then user. Measured with Claude Code 2.1.270 in this lab's image, with a server named
`docs` defined in each scope and a tool that says which one it is:

```text
all three defined        → I am LOCAL
local and project        → I am LOCAL
project and user         → I am PROJECT
project only             → I am PROJECT
```

So a local `docs` shadows the team's, silently, in every run in that directory — interactive or
headless, the job included. That is useful when you are testing a new server, and a trap once you forget
it is there.

### Seeing it

`claude mcp list` shows the definitions in effect and their health, and — when a name is defined in
several scopes with different commands — a *Conflicting scopes* diagnostic naming both, with the
command to remove either. `claude mcp get docs` shows the scope a definition came from.
`claude mcp remove docs -s local` removes one scope's definition and leaves the others.

### Secrets: `${VAR}` in `.mcp.json`

`.mcp.json` is committed, so a key written into it is published to everyone with the repository, and
stays in its history. Claude Code expands `${VAR}` (and `${VAR:-default}`) in a server's `command`,
`args`, `env`, `url` and `headers` from its own environment. The job loads the key from
`~/.config/handbook/env` before starting `claude`, so the server still gets it. When the variable is
missing, `claude mcp list` warns: *Missing environment variables: DOCS_API_KEY*.

### A committed secret is a burned secret

Removing the key from the file and committing fixes the next clone. Every existing clone, fork and
backup still has it in history; the only real fix is to rotate the key at the service. The grader
checks the files and the latest commit; a person has to do the rest.

## A failure, walked through

Replayed on the lab's container (Ubuntu 26.04, Claude Code 2.1.270; JSON compacted, long lines
trimmed). What the team reviewed:

```console
$ cat ~/handbook-bot/.mcp.json
{"mcpServers": {"docs": {"type": "stdio", "command": "python3",
  "args": ["/opt/docs-mcp/docs_mcp.py", "--edition", "3"],
  "env": {"DOCS_API_KEY": "hb_59322a1e5347785048e7a5717df62fcf"}}}}
```

What Claude Code runs, in that directory:

```console
$ claude mcp list
docs: python3 /opt/docs-mcp/docs_mcp.py --edition 1 - ✔ Connected

MCP config diagnostics ⚠
[Conflicting scopes]
├ Server "docs" is defined in multiple scopes with different endpoints: project (python3
│ /opt/docs-mcp/docs_mcp.py --edition 3), local (python3 /opt/docs-mcp/docs_mcp.py --edition 1). ...
└ Keep the correct endpoint and remove the others: `claude mcp remove docs -s project` or
  `claude mcp remove docs -s local`
$ claude mcp get docs
docs:
  Scope: Local config (private to you in this project)
  Args: /opt/docs-mcp/docs_mcp.py --edition 1
$ jq '.projects["/home/learner/handbook-bot"].mcpServers' ~/.claude.json
{"docs": {"type": "stdio", "command": "python3", "args": ["/opt/docs-mcp/docs_mcp.py", "--edition", "1"], ...}}
```

Edition 1 is last year's. Remove the local definition — and only that one:

```console
$ claude mcp remove docs -s local
Removed MCP server docs from local config
File modified: /home/learner/.claude.json [project: /home/learner/handbook-bot]
$ claude mcp list
docs: python3 /opt/docs-mcp/docs_mcp.py --edition 3 - ⏸ Pending approval (run `claude` to approve)
```

(*Pending approval* is the interactive prompt for a project server; the headless job starts it.) Then
the key: `"DOCS_API_KEY": "${DOCS_API_KEY}"` in `.mcp.json`. Without the variable set, Claude Code says
so:

```text
[Contains warnings] Project config (shared via .mcp.json)
 └ [Warning] [docs] mcpServers.docs: Missing environment variables: DOCS_API_KEY
```

and with it loaded the way the job loads it, the warning is gone. Commit, and the latest commit is
clean — the first one is not:

```console
$ git commit -qam "docs: take the key from the environment"; git grep -c hb_ HEAD || echo "no key in HEAD"
no key in HEAD
$ git log --oneline -S hb_
5e5327b docs: take the key from the environment
b45a2eb handbook-bot: the docs server, edition 3
```

`git log -S` lists both commits that changed the key's count — the one that removed it here, and the
first one that added it. The job, afterwards:

```text
search: [handbook edition 3] Credential rotation: Database credentials are rotated every 90 days; the
security lead approves each rotation.
```

## Common wrong turns

- **Editing `.mcp.json` again.** It was right; the answer comes from another scope.
- **Changing the local definition to edition 3.** The job answers correctly, and the next change to the
  team's `.mcp.json` is silently ignored on this machine again.
- **`claude mcp remove docs` without `-s`.** Know which definition you are removing; the diagnostic names
  both.
- **Deleting `~/.claude.json`.** It holds much more than MCP servers: trust decisions, project history.
- **Removing the key from the file and calling it done.** It is in the history; rotate it.

## Cheat sheet

```text
claude mcp list                         # in effect, with health and scope conflicts
claude mcp get NAME                     # one definition and its scope
claude mcp remove NAME -s local|project|user
jq '.projects[env.PWD].mcpServers, .mcpServers' ~/.claude.json    # local, then user
"env": {"KEY": "${KEY}"}                # in .mcp.json; ${KEY:-default} for a fallback
git log --oneline -S SECRET             # every commit that added or removed it
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The Model Context Protocol* (topic journal `mcp`) — Clients, scopes and secrets

Documentation:

- https://code.claude.com/docs/en/mcp

The whole subject, end to end: the topic journals *The Model Context Protocol* (`mcp`), *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. Where are Claude Code's local-scope and user-scope MCP servers stored?

   > Both in `~/.claude.json`: local ones under `projects["<project path>"].mcpServers`, user ones in the
   > top-level `mcpServers`.

2. `docs` is defined in `.mcp.json` and in the user scope. Which runs in the project?

   > The project's — project beats user; a local-scope definition would beat both.

3. How do you find out that a name is defined in more than one scope?

   > `claude mcp list` reports a *Conflicting scopes* diagnostic naming each scope's command, and
   > `claude mcp get NAME` shows the scope of the one in effect.

4. What does Claude Code do with `${DOCS_API_KEY}` in `.mcp.json` when the variable is not set?

   > It cannot expand it and warns about a missing environment variable in `claude mcp list`; set it in
   > Claude Code's environment, or give a default with `${DOCS_API_KEY:-…}`.

5. The key is out of the latest commit. What is still to do, and why?

   > Rotate the key: every clone and the repository's history still contain it.
