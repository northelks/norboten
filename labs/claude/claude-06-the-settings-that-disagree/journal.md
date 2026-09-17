---
title: Five settings levels, one winner per key, and a policy only if it can be read
topics: [claude-code, linux-basics]
minutes: 40
---

Claude Code reads its configuration from up to five places, and on a shared machine each belongs to
someone different: the security team owns the managed policy, whoever runs a session owns the command
line, a developer owns their local project settings, the team owns the committed project settings,
and each user owns their own. When they disagree, Claude Code does not ask; it applies fixed rules.
Knowing those rules is the difference between "we set that" and "that is in effect".

This machine has three agreements, and each is defeated by a different rule. The security policy is
in a directory Claude Code never reads, and even in the right one it would be unreadable to the users
it governs. The team's model is overridden by a personal settings file somebody committed. And the
coding conventions are imported by a name that differs from the file's in one letter's case.

## What you should be able to do after this

- List the settings levels in order and say, for a given key, which one wins.
- Tell scalar keys, which override, from list keys such as permission rules, which merge.
- Install a managed policy on Linux where Claude Code reads it, with permissions that let it be read.
- Keep personal settings and personal memory files out of a repository.
- Predict what a `CLAUDE.md` import loads, and find out when it loads nothing.

## The mechanism

### The levels

Highest precedence first:

| level | where | owned by |
|---|---|---|
| managed | `/etc/claude-code/managed-settings.json` on Linux (macOS: `/Library/Application Support/ClaudeCode/`), or MDM / server-managed | an administrator |
| command line | `--model`, `--permission-mode`, `--allowedTools`, `--settings <file>` | whoever starts the session |
| local project | `.claude/settings.local.json` | one developer, on one machine |
| shared project | `.claude/settings.json` | the team, committed |
| user | `~/.claude/settings.json` | the user, for every project |

Two rules decide the result:

- **Scalar keys** — `model`, `permissions.defaultMode`, `outputStyle` — come from the highest level
  that sets them. Everything below is ignored for that key.
- **List keys merge.** `permissions.allow`, `permissions.deny`, hooks and similar lists from every
  level are combined. For permissions, deny is evaluated first across all of them, so a deny at any
  level cannot be undone by an allow at another — including one on the command line.

Verified in the lab image for `model`: user `sonnet`, project `haiku`, local `opus` requests Opus;
without the local file, Haiku; with `--model haiku` on the command line, Haiku.

`--setting-sources user,project,local` chooses which of the file levels load at all; managed settings
always load. Environment variables are not a level: the `env` block in a settings file is just a key,
merged like the others.

### Managed settings are read by the user

Claude Code is an ordinary process running as whoever started it. It reads the managed file with that
user's permissions. A policy file owned by root with mode `0600` cannot be read by anyone else, and
Claude Code 2.1.270 says so on stderr and carries on without it:

```
Managed settings failed to load; policies from the failed source are NOT in effect:
  /etc/claude-code/managed-settings.json: Settings file could not be read: EACCES: permission denied
```

A policy is not a secret. The correct mode is `0644`, owned by root: everyone can read it, nobody but
root can change it. A file in the wrong directory — `/etc/claude/`, `/etc/claude-code.d/` — is not an
error at all: nothing reads it, and nothing says so.

Managed settings can also restrict the other levels: `allowManagedPermissionRulesOnly` keeps
everyone else's allow rules from merging in, `allowManagedHooksOnly` runs only the organisation's
hooks. A machine that must not run `--dangerously-skip-permissions` sets
`permissions.disableBypassPermissionsMode` to `"disable"` in its managed file. Besides
`managed-settings.json`, the same directory may hold a `managed-settings.d/` of drop-ins and a
`managed-mcp.json`.

### A deny that names a tool removes it

`"deny": ["WebFetch"]` — a tool name with no specifier — takes the tool out of the session. The model
is not offered it, and a call fails as "No such tool available: WebFetch", exactly as with `--tools`.
`"deny": ["Read(~/.ssh/**)"]` keeps the Read tool and refuses matching paths; it also refuses shell
commands that name such a path (`cat ~/.ssh/id_ed25519`). `~/` in a rule means the home directory of
the user running the session, so one managed rule protects every user's keys.

### Personal files and git

Two files in a project are personal by design: `.claude/settings.local.json` and `CLAUDE.local.md`.
Claude Code adds the local settings file to git's global excludes only when Claude Code itself creates
it (for example when you answer "don't ask again" to a prompt). A file created by hand, or copied from
a colleague, is an ordinary file to git, and `git add -A` commits it. Once committed, the local level —
which outranks the team's file — applies to everyone who pulls.

### CLAUDE.md and imports

Memory files load broad to specific and are **concatenated**, not overridden: managed
(`/etc/claude-code/CLAUDE.md`), user (`~/.claude/CLAUDE.md`), the project's `CLAUDE.md` or
`.claude/CLAUDE.md` in the working directory and every parent, and `CLAUDE.local.md`. A line
`@path/to/file` imports another file, resolved relative to the importing file, up to four hops deep.

An import that names a file which does not exist adds nothing and warns about nothing. On Linux paths
are case-sensitive, so `@docs/conventions.md` does not load `docs/CONVENTIONS.md` (on a default macOS
filesystem it would — a way for this bug to pass on a laptop and fail on the build machine). An import
inside backticks is text, not an import. All three were verified in the lab image.

The transcript under `~/.claude/projects/<project>/` shows what was sent, `CLAUDE.md` included; the
interactive `/memory` command lists the files that loaded.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, the scripted model). A session with every tool
allowed on the command line, as a developer might start one:

```console
$ claude -p "Get ready for the deploy" --allowedTools "WebFetch,Read,Bash" --output-format json 2>/tmp/err \
    | jq -c '{num_turns, permission_denials, model: (.modelUsage|keys)}'
{"num_turns":3,"permission_denials":[],"model":["claude-opus-5"]}
$ jq -r 'select(.type=="user") | .message.content[]? | select(.type=="tool_result")
         | .content | if type=="array" then .[0].text else . end' "$(ls -t ~/.claude/projects/-home-learner-platform/*.jsonl | head -1)"
getaddrinfo ENOTFOUND docs.example.org
-----BEGIN OPENSSH PRIVATE KEY-----
73e5ec49b3b31f1e8f53d668adefc2f739fafe81d9150d92
-----END OPENSSH PRIVATE KEY-----
```

WebFetch was attempted (it failed only because the address does not resolve), the key was printed, and
the session ran on Opus. The policy exists — in the wrong place, with a mode only root can read:

```console
$ ls -l /etc/claude*/
-rw------- 1 root root 108 Sep 14 19:49 managed-settings.json
$ sudo cat /etc/claude/managed-settings.json
{ "permissions": { "deny": ["WebFetch", "WebSearch", "Read(~/.ssh/**)"] } }
```

Moving it to `/etc/claude-code/` turns silence into an error message, which is progress:

```console
$ sudo mkdir -p /etc/claude-code && sudo mv /etc/claude/managed-settings.json /etc/claude-code/
$ claude -p "Get ready" --allowedTools "WebFetch,Read,Bash" --output-format json 2>/tmp/err | jq -c '{permission_denials}'
{"permission_denials":[]}
$ cat /tmp/err
Managed settings failed to load; policies from the failed source are NOT in effect:
  /etc/claude-code/managed-settings.json: Settings file could not be read: EACCES: permission denied, open '/etc/claude-code/managed-settings.json'
```

With mode `0644`:

```console
$ sudo chmod 644 /etc/claude-code/managed-settings.json && sudo rmdir /etc/claude
$ claude -p "Get ready" --allowedTools "WebFetch,Read,Bash" --output-format json 2>/tmp/err \
    | jq -c '{denials: [.permission_denials[] | .tool_name]}'
{"denials":["Bash"]}
$ jq -r '… tool results …' "$(ls -t ~/.claude/projects/-home-learner-platform/*.jsonl | head -1)"
<tool_use_error>Error: No such tool available: WebFetch. WebFetch is disabled for this session, …
Permission to use Bash with command cat ~/.ssh/id_ed25519 has been denied.
```

WebFetch no longer exists in the session despite `--allowedTools`, and `cat` of the key is refused.
Next, the model. Every level that sets it:

```console
$ for f in ~/.claude/settings.json .claude/settings.json .claude/settings.local.json; do printf '%s: ' $f; jq -c . $f; done
/home/learner/.claude/settings.json: {"model":"sonnet"}
.claude/settings.json: {"model":"haiku"}
.claude/settings.local.json: {"model":"opus"}
$ git ls-files .claude
.claude/settings.json
.claude/settings.local.json
```

The local file wins, and it is committed, so it wins for everyone. Remove it from the index and the
disk, and ignore both personal files:

```console
$ git rm -q --cached .claude/settings.local.json && rm .claude/settings.local.json
$ printf '.claude/settings.local.json\nCLAUDE.local.md\n' >> .gitignore
$ git check-ignore -v .claude/settings.local.json
.gitignore:1:.claude/settings.local.json	.claude/settings.local.json
```

Last, the conventions. The transcript contains `CLAUDE.md` word for word, including the import line —
and nothing from the conventions file:

```console
$ grep -o "Follow the team.s conventions:[^\"]*" "$s" | head -1
Follow the team's conventions:\n@docs/conventions.md
$ grep -c "rev " "$s"
0
$ ls docs
CONVENTIONS.md
$ sed -i 's|^@docs/conventions.md$|@docs/CONVENTIONS.md|' CLAUDE.md
$ claude -p hi --output-format json >/dev/null 2>&1
$ grep -o "# Conventions (rev [0-9a-f]*)" "$(ls -t ~/.claude/projects/-home-learner-platform/*.jsonl | head -1)" | head -1
# Conventions (rev 4dbedac7)
```

Commit the `.gitignore`, the removal and the import. The grader:

```
PASS 01_the_machine_policy_holds_everywhere: In both directories, with every tool allowed on the command line,
     the web tools were refused and the key stayed private.
PASS 02_the_team_model_is_used: A session in ~/platform runs on claude-haiku-4-5-20251001.
PASS 03_personal_settings_stay_out_of_git: Personal settings are neither tracked nor able to be added by accident.
PASS 04_the_conventions_reach_the_model: The conventions reach the model with CLAUDE.md.
```

## Common wrong turns

**Testing the policy with `sudo claude`.** root can read a `0600` file, so the policy "works". Test as
the users it governs.

**Making the policy file `0666` "so it can be read".** Now anyone can rewrite the policy — or empty it.
`0644`, owned by root.

**Putting the policy in the user's `~/.claude/settings.json`.** The user can edit it, and it is the
lowest level; any project can override its scalar keys. Company policy is managed settings.

**Setting `"model": "haiku"` in the user settings to beat the local file.** User settings are the lowest
level. The local file has to go.

**Deleting the local file without ignoring it.** The next "don't ask again" or copied snippet recreates
it, and `git add -A` commits it again.

**Renaming `docs/CONVENTIONS.md` to lower case on a Mac.** On a case-insensitive filesystem `git mv`
needs two steps, and a plain rename may not register as a change at all. Fixing the import line is the
smaller change.

**Expecting a warning for a broken import.** There is none. Check the transcript, or `/memory` in an
interactive session.

**Denying `Read(/home/learner/.ssh/**)`.** It protects one user. `Read(~/.ssh/**)` in managed settings
protects whoever runs the session.

## Cheat sheet

```bash
# every level, for one key
for f in /etc/claude-code/managed-settings.json ~/.claude/settings.json \
         .claude/settings.json .claude/settings.local.json; do
  [ -r "$f" ] && printf '%s: %s\n' "$f" "$(jq -c '{model, permissions}' "$f")"
done
claude -p hi --output-format json 2>&1 >/dev/null | head    # "Managed settings failed to load…"

# managed policy on Linux: readable by all, writable by root
sudo install -d -m 755 /etc/claude-code
sudo install -m 644 -o root -g root policy.json /etc/claude-code/managed-settings.json
{
  "permissions": {
    "deny": ["WebFetch", "WebSearch", "Read(~/.ssh/**)"],
    "disableBypassPermissionsMode": "disable"
  }
}

# which model a session asks for
claude -p hi --output-format json | jq '.modelUsage | keys'

# personal files
git ls-files .claude CLAUDE.local.md
git rm --cached .claude/settings.local.json
printf '.claude/settings.local.json\nCLAUDE.local.md\n' >> .gitignore
git check-ignore -v .claude/settings.local.json

# memory and imports
grep -n '^@' CLAUDE.md                      # imports: relative to this file, case-sensitive
s=$(ls -t ~/.claude/projects/<project>/*.jsonl | head -1); grep -c 'a phrase from the import' "$s"
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — What a session loads

Documentation:

- https://code.claude.com/docs/en/settings
- https://git-scm.com/docs/gitignore
- https://code.claude.com/docs/en/memory

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. List the five settings levels from highest to lowest precedence.

   > Managed, command line, local project (`.claude/settings.local.json`), shared project
   > (`.claude/settings.json`), user (`~/.claude/settings.json`).

2. User settings say `sonnet`, the project file `haiku`, the local project file `opus`. Which model
   does a session in the project request, and what would make it Haiku without touching any file?

   > Opus — the local file is the highest level that sets `model`. Starting the session with
   > `--model haiku`, since the command line outranks all three files.

3. A deny rule in the project file and an allow rule for the same tool on the command line: which
   applies, and why is that not a contradiction of question 2?

   > The deny. Permission rules are lists that merge across levels, and deny is evaluated first; only
   > scalar keys such as `model` are taken from the single highest level.

4. The managed policy is `/etc/claude-code/managed-settings.json`, root-owned, mode `0600`. What does a
   user's session do, and what is the correct mode?

   > It cannot read the file, reports "Managed settings failed to load; policies … are NOT in effect",
   > and runs without the policy. `0644`, owned by root.

5. What does `"deny": ["WebFetch"]` do that `"deny": ["WebFetch(domain:example.org)"]` does not?

   > The bare name removes the tool from the session entirely (a call fails as "No such tool
   > available"); a rule with a specifier leaves the tool and refuses only matching calls.

6. Why did a committed `.claude/settings.local.json` change the model for the whole team, and why did
   git not ignore it?

   > The local level outranks the shared project file, and once committed everyone pulls it. Claude
   > Code adds it to git's excludes only when Claude Code creates it; a hand-made copy is an ordinary
   > file until `.gitignore` names it.

7. `CLAUDE.md` says `@docs/conventions.md` and the file is `docs/CONVENTIONS.md`. What happens on Linux,
   and why might it work on a developer's Mac?

   > On Linux the import finds no file and silently adds nothing. A default macOS filesystem is
   > case-insensitive, so the same path resolves there.

8. How can you confirm, after a headless run, that an imported file reached the model?

   > Search the session transcript in `~/.claude/projects/<project>/<session>.jsonl` for a phrase that
   > only the imported file contains (or use `/memory` interactively to list loaded files).
