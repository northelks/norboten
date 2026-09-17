---
title: The File Server That Shows Everything — what an MCP server exposes is the server's decision
topics: [mcp, claude-code]
minutes: 25
---

An MCP server is a program that offers a model tools. A file server's tools read and list files, and
which files is not decided by the model, by Claude Code or by the prompt: it is decided by the server,
from its own settings. This lab's server was set up to share `/` — every file the user it runs as can
read — with links followed wherever they lead, dotfiles included, and a tool to write as well. The
assistant quoted a private key because nothing stopped it from reading one.

## What you should be able to do after this

- Say where the boundary of an MCP server's access is set, and why a client's prompt is not it.
- Read a file server's settings and predict what a given path will return.
- Explain why a path that starts inside a shared folder can still lead out of it.
- Keep hidden files and writing out of a server that only needs to read.
- Test a server by hand, over stdio, without Claude Code in the way.

## The mechanism

### A server runs as someone

A stdio MCP server is a child process of the client. Claude Code starts it with the command in
`.mcp.json`, as the user running Claude Code, and talks JSON-RPC to it over stdin and stdout. The
server can therefore open anything that user can open: here, `learner`'s home, `~/.ssh` included.
Unix permissions answer "may this user read the file"; they cannot answer "should the model see it",
because the model and the user are, as far as the kernel knows, the same process tree.

So a server that exposes files needs its own boundary. This one reads it from
`/etc/mcp-files/config.json` on every call: `roots` (the folders a path must lie in),
`follow_symlinks`, `show_hidden` and `read_only`.

### Roots, and the path as written

Every path a tool receives is resolved first — a relative path is taken from the first root — and then
checked: is it inside one of the roots? With `"roots": ["/"]`, every absolute path is inside, and the
check means nothing. The fix everyone reaches for first is to narrow the roots to `~/notes`, and it is
necessary. It is not enough.

### Links: where a path really leads

`~/notes/shared-keys` is a symbolic link to `~/.ssh`. The path `~/notes/shared-keys/id_ed25519` *is*
inside `~/notes` as written — its text starts with `/home/learner/notes/` — and the file it opens is
outside. A check on the path as written (`os.path.abspath`) passes it; a check on where it leads
(`os.path.realpath`, with the roots resolved the same way) refuses it. `follow_symlinks: true` is the
first kind. Links are how shared folders grow in practice — somebody links a directory in "for
convenience" — so a server has to decide on the real location, not the spelling.

### Hidden files

Dotfiles are where applications keep configuration and, often, credentials: `.env`, `.netrc`, `.git`.
A notes folder has no business showing them to a model. `show_hidden: false` makes the server leave
them out of listings and refuse to read them, even when the name is asked for directly.

### Read-only is a tool list

With `read_only: false`, the server offers `write_file`. A model that can write the runbook can change
what the next reader believes. The right shape is not a tool that checks a flag and says no: it is a
server that does not offer the tool at all, so it never appears in the model's list.

### The client is a second fence, not the first

The job allows `mcp__files` — every tool the server offers. Claude Code could narrow that
(`mcp__files__read_file,mcp__files__list_directory`), and that is worth doing. But permission rules
decide which *tools* may be called, not which *paths*: a model allowed `read_file` may pass it any
path at all. The paths are the server's business.

## A failure, walked through

Replayed on the lab's container (Ubuntu 26.04, Claude Code 2.1.270; JSON shown on one line). The project's server definition,
and the settings the server reads:

```console
$ cat ~/notes-bot/.mcp.json
{"mcpServers": {"files": {"type": "stdio", "command": "python3", "args": ["/opt/mcp-files/files_mcp.py"]}}}
$ cat /etc/mcp-files/config.json
{"roots": ["/"], "follow_symlinks": true, "show_hidden": true, "read_only": false}
$ ls -la ~/notes
-rw------- 1 learner learner   54 Sep 15 18:48 .env
-rw-r--r-- 1 learner learner  100 Sep 15 18:48 oncall.md
-rw-r--r-- 1 learner learner  207 Sep 15 18:48 runbook.md
lrwxrwxrwx 1 learner learner   18 Sep 15 18:48 shared-keys -> /home/learner/.ssh
```

`claude mcp list` in an interactive-style call shows the project server waiting for approval — yet the
headless job starts it and uses it; what counts is what the job does, so test the server directly. Two
JSON-RPC messages on its stdin are enough:

```console
$ printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
    '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read_file","arguments":{"path":"/home/learner/notes/shared-keys/id_ed25519"}}}' \
  | python3 /opt/mcp-files/files_mcp.py
{"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", ...}}
files: starting; roots ['/']
{"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "-----BEGIN OPENSSH PRIVATE KEY-----\n(lab key)\n"}]}}
```

The log line went to stderr, the answers to stdout. Now narrow the roots and nothing else — the
settings file becomes `{"roots": ["/home/learner/notes"], "follow_symlinks": true, "show_hidden": true,
"read_only": false}` — and ask again. Each line below is one call written to the server's stdin the
same way, with its answer shortened:

```text
read_file /etc/passwd                        → refused: /etc/passwd is outside the folders this server shares
read_file ~/notes/shared-keys/id_ed25519     → "-----BEGIN OPENSSH PRIVATE KEY-----..."
read_file ~/notes/.env                       → "ALERT_WEBHOOK=https://hooks.example/T7ac1899de40cf974"
```

Half the problem is gone and both of the review's findings are still there. With all four settings
right — roots on the notes, links checked where they lead, dotfiles hidden, read-only:

```text
read_file ~/notes/shared-keys/id_ed25519     → refused: ... is outside the folders this server shares
read_file ~/notes/.env                       → refused: /home/learner/notes/.env is hidden
list_directory ~/notes                       → oncall.md  runbook.md  shared-keys/
write_file ~/notes/runbook.md                → error -32602: unknown tool
read_file runbook.md                         → "# On-call runbook ..."
```

The link is still listed — it is a name in the folder — but it no longer opens anything outside it,
and the relative path works from the first root.

## Common wrong turns

- **Deleting the link and the `.env`.** The next colleague links something in again, or keeps an `.env`
  for a script. The grader creates fresh ones on every check for exactly that reason.
- **Narrowing the roots and stopping.** Shown above: links and dotfiles inside the root still leak.
- **Telling the model not to read secrets.** A system prompt is advice to a model that a hostile page or
  a bad plan can override. A boundary the server enforces cannot be talked around.
- **`chmod 000 ~/.ssh`.** The server runs as the same user as everything else, so the next thing that
  needs the key breaks — and the server still reads every other file that user can.
- **Removing `mcp__files` from the job.** The job then answers nothing; the task was to share the notes,
  not to stop sharing.

## Cheat sheet

```text
cat .mcp.json                               # which command starts which server
claude mcp list                             # what Claude Code makes of the definitions
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | <server command>   # the server by hand
realpath ~/notes/some/link                  # where a path really leads
python3 -c 'import os; print(os.path.realpath(p).startswith(root))'    # the check that matters
--allowedTools "mcp__files__read_file,mcp__files__list_directory"      # narrow the tools too
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The Model Context Protocol* (topic journal `mcp`) — What a server exposes is the server's decision

Manual pages: `man 7 symlink`, `man 1 realpath`.

Documentation:

- https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- https://modelcontextprotocol.io/specification/2026-07-28/basic/security_best_practices

The whole subject, end to end: the topic journals *The Model Context Protocol* (`mcp`), *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A stdio MCP server runs as which user, and what can it therefore read?

   > The user who runs Claude Code, since it is Claude Code's child process; anything that user can read,
   > unless the server enforces a narrower boundary of its own.

2. Why does `roots: ["/home/learner/notes"]` not stop `~/notes/shared-keys/id_ed25519` from being read
   when `follow_symlinks` is true?

   > The server checks the path as written, which starts with the root; the link inside the root points
   > outside it. Only a check on the resolved path (realpath) refuses it.

3. What is the difference between refusing `write_file` in the tool and not offering it?

   > A tool that refuses still appears in the model's list and invites attempts; a tool that is not
   > offered cannot be called or planned around, and a later change to the check cannot open it.

4. Can a Claude Code permission rule keep a model from reading `~/.ssh` through an MCP file server?

   > Not by path: rules allow or deny tools such as `mcp__files__read_file`; the arguments are the
   > server's to check.

5. How do you test what an MCP server returns without a model?

   > Start its command yourself and write JSON-RPC to its stdin: `initialize`, then `tools/list` or
   > `tools/call`; the answers come back on stdout, one per line, and the logs on stderr.
