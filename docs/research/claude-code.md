# Claude Code as it is today — research notes

Read from the official documentation at <https://code.claude.com/docs> on 2026-09-14, against
Claude Code **2.1.270**. Every lab, theory question and journal of the Claude Code track cites this
file or the page linked beside a fact. Where a behaviour matters for grading, it was also run
locally (section 14); those results are marked **verified**.

The documentation is published as Markdown: append `.md` to a page URL, and the whole index is
<https://code.claude.com/docs/llms.txt>.

---

## 1. Install and versions — [setup](https://code.claude.com/docs/en/setup)

- Native installer: `curl -fsSL https://claude.ai/install.sh | bash` (optionally `-s stable` or a
  version number). A single binary; **no Node.js needed**. Also Homebrew casks (`claude-code`,
  `claude-code@latest`), and apt / dnf / apk packages.
- The launcher lives at `~/.local/bin/claude`, a symlink into `~/.local/share/claude/versions/`.
- Requirements: 4 GB+ RAM, x64 or ARM64; Alpine 3.19+ needs `bash`, `curl`, `libgcc`,
  `libstdc++`, `ripgrep`.
- Release channels `latest` and `stable` (about a week behind); `minimumVersion` sets a floor;
  `DISABLE_AUTOUPDATER=1` stops background updates, `DISABLE_UPDATES` blocks all of them.
- `claude doctor` diagnoses the install and configuration.

## 2. Headless runs — [headless](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference)

- `claude -p "<prompt>"` runs one non-interactive session and exits 0 on success, non-zero on
  failure. Failures inside the run (for example missing authentication) are printed on stdout as
  the result; invalid flags go to stderr before the run starts. SIGTERM exits 143.
- `--output-format text|json|stream-json`. `json` carries `result`, `session_id`, `num_turns`,
  `total_cost_usd` (a client-side estimate), `modelUsage`, `permission_denials`, `is_error`.
  `stream-json` needs `--verbose`; `--include-partial-messages` adds token deltas.
- `--json-schema '<schema>'` with `--output-format json` puts validated output in
  `structured_output`; an invalid schema is an error.
- Stdin is read (capped at 10 MB), so `git diff | claude -p "review"` works without Bash permission.
- `--continue` / `--resume <session-id>` continue a conversation; `--no-session-persistence` keeps
  nothing on disk.
- **Caps:** `--max-turns N` (print mode; exits with an error at the limit; no limit by default) and
  `--max-budget-usd X` (print mode; subagent spend counts). `--model` takes an alias
  (`haiku`, `sonnet`, `opus`, `fable`) or a full id; `--fallback-model` a comma-separated chain;
  `--effort low|medium|high|xhigh|max`.
- **`--bare`** skips auto-discovery of hooks, skills, commands, subagents, plugins, MCP servers,
  auto memory and CLAUDE.md; recommended for scripts and "will become the default for `-p`". Load
  what you need explicitly with `--settings`, `--mcp-config`, `--agents`,
  `--append-system-prompt[-file]`, `--plugin-dir`. **Bare mode never reads OAuth credentials or
  `CLAUDE_CODE_OAUTH_TOKEN`** — only `ANTHROPIC_API_KEY` or an `apiKeyHelper`.
- **Without `--bare`, `-p` runs the project's `.claude/settings.json` hooks and connects its
  `.mcp.json` servers with no trust dialog** — a repository you run `claude -p` in can execute code.
- Tool control: `--allowedTools` (auto-approve, permission-rule syntax), `--disallowedTools`
  (deny rules; a bare name removes the tool), `--tools "Bash,Read"` (restrict the built-in set,
  `""` for none; does not touch MCP tools).
- `--permission-mode default|acceptEdits|plan|auto|dontAsk|bypassPermissions` (`manual` is an alias
  of `default`); `-p` starts in Manual. `--permission-prompts none` (2.1.259+) denies anything that
  would prompt and tells Claude not to retry.
- Background Bash tasks are killed ~5 s after the final result; background subagents are waited for
  up to 10 minutes of idle (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`).
- In `stream-json`, the `system/init` event lists `mcp_servers` (with `status`) and
  `mcp_server_errors`; a CI gate can fail when a server did not load.

## 3. Authentication — [authentication](https://code.claude.com/docs/en/authentication)

Precedence, highest first: cloud provider (`CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY`) →
`ANTHROPIC_AUTH_TOKEN` (Bearer) → `ANTHROPIC_API_KEY` (`X-Api-Key`; in `-p` always used when
present) → `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → Anthropic profiles / federation →
subscription login from `/login`.

- `claude setup-token` prints a **one-year OAuth token** tied to a Pro, Max, Team or Enterprise
  subscription; it saves nothing — export it as `CLAUDE_CODE_OAUTH_TOKEN`. It can only make model
  requests (no Remote Control, no claude.ai connectors; local MCP servers still work).
- A stray `ANTHROPIC_API_KEY` silently wins over a subscription in `-p` — a common cause of
  "authentication failed" in CI when the key's organization is disabled.
- `ANTHROPIC_BASE_URL` points Claude Code at a proxy or gateway (and at a fake API in tests —
  section 14).

## 4. Settings — [settings](https://code.claude.com/docs/en/settings), [settings reference](https://code.claude.com/docs/en/settings-reference)

Precedence, highest first: **managed** (`managed-settings.json`, MDM, server-managed) → **command
line** (`--settings`, flags) → **local project** `.claude/settings.local.json` → **shared project**
`.claude/settings.json` → **user** `~/.claude/settings.json`.

- Scalar keys: the highest level wins. **List keys merge** across files (`permissions.allow`, …),
  except `fallbackModel`, `modelPicker`, `availableModels` and `modelSettings`.
- `.claude/settings.local.json` is added to the global git excludes when Claude Code writes it;
  create it by hand and you must ignore it yourself.
- Environment variables are not a level; the `env` block in a settings file is an ordinary key.
- `--setting-sources user,project,local` chooses which files load at all.
- `CLAUDE_CONFIG_DIR` moves `~/.claude` (settings, sessions, plugins).

## 5. Permissions — [permissions](https://code.claude.com/docs/en/permissions), [permission modes](https://code.claude.com/docs/en/permission-modes)

- Rules are `Tool` or `Tool(specifier)` in `permissions.allow`, `ask`, `deny`. **Deny is evaluated
  first at every level**: a deny anywhere cannot be allowed anywhere else, including by
  `--allowedTools`. Ask rules prompt even in `bypassPermissions`; allow rules do nothing in
  `bypassPermissions`.
- Bash: `*` matches any text including spaces. `Bash(git log *)` matches `git log` and
  `git log -5`; `Bash(ls *)` does not match `lsof` but `Bash(ls*)` does; `:*` at the end equals
  ` *`. Put `*` after the subcommand: `Bash(git * main)` also allows `git push origin main`.
- Compound commands (`&&`, `||`, `;`, `|`, `&`, newline) are split; an allow rule must match every
  part, a deny/ask rule matches if any part (including `$(…)` and subshells) matches.
- Wrappers `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob` and bare
  `xargs` are stripped before matching. `npx`, `docker exec`, `devbox run` are not: `Bash(npx *)`
  allows anything.
- **A Bash rule is not a security boundary**: `Bash(rm *)` in deny does not stop `/bin/rm`,
  `sh -c 'rm …'`, or `git -C . push` for `Bash(git push *)`. Use the sandbox or a `PreToolUse` hook.
- A built-in read-only command set (`ls`, `cat`, `grep`, `find`, `git` read forms, …) never prompts.
- File rules use gitignore syntax: `//abs/path`, `~/home/path`, `/relative-to-settings-source`,
  `path` relative to the cwd. `Edit(...)` covers every editing tool; `Read(...)` deny also blocks
  Edit/Write on that path. Rules written as `Write(...)`, `Glob(...)` are accepted but **never
  consulted** (a startup warning names them).
- "Yes, and don't ask again" for Bash or WebFetch saves the rule to `.claude/settings.local.json` at
  the repository root.
- Modes: `default` (Manual: reads only), `acceptEdits` (edits + `mkdir`/`touch`/`mv`/`cp`), `plan`,
  `auto` (a classifier reviews actions), `dontAsk` (anything that would prompt is denied — for CI),
  `bypassPermissions` ("isolated containers and VMs only"). No mode auto-approves ask rules,
  `AskUserQuestion`, or `rm` of critical paths.

## 6. Hooks — [hooks](https://code.claude.com/docs/en/hooks), [hooks guide](https://code.claude.com/docs/en/hooks-guide)

- Configured under `"hooks"` in any settings file (also plugin `hooks/hooks.json`, and skill or
  subagent frontmatter): event → matcher group → handlers. Entries merge across levels.
- Handler types: `command`, `http`, MCP tool, `prompt` (a model judges), `agent`; `async: true`
  runs in the background.
- Events include `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`,
  `PostToolUse`, `PostToolUseFailure`, `Notification`, `SubagentStart`/`Stop`, `Stop`,
  `StopFailure`, `PreCompact`/`PostCompact`, `ConfigChange`, `FileChanged`, `SessionEnd`, and more.
- **Matcher:** `*`, `""` or omitted match all; only letters, digits, `_ - , |` and spaces means
  exact names (`Edit|Write`); anything else is an **unanchored JavaScript regex** (`Edit.*` also
  matches `NotebookEdit`). Tool names are case-sensitive: a matcher `bash` never fires for `Bash`
  (**verified**, section 14).
- Input is JSON on stdin (`tool_name`, `tool_input`, `tool_use_id`, `session_id`, `cwd`, …);
  file paths in `tool_input` are absolute. `$CLAUDE_PROJECT_DIR` is set for command hooks.
- **Exit codes:** 0 = success (stdout is parsed as JSON if it starts with `{` and ends with `}`;
  plain stdout is context only for `UserPromptSubmit`, `UserPromptExpansion`, `SessionStart`,
  `PostModelSwitch`). **2 = blocking error**: stderr is the reason, `PreToolUse` blocks the call,
  and no JSON `allow` can override it. Any other code = non-blocking error; the action proceeds.
- `PreToolUse` JSON: `hookSpecificOutput.permissionDecision` = `allow` | `deny` | `ask` | `defer`,
  plus `permissionDecisionReason` and `updatedInput`. Deny and ask rules are still evaluated.
- `disableAllHooks`; `allowManagedHooksOnly` (managed). `/hooks` lists what loaded.

## 7. Subagents — [sub-agents](https://code.claude.com/docs/en/sub-agents)

- Markdown files with YAML frontmatter in `.claude/agents/` (project, priority 3),
  `~/.claude/agents/` (user, 4), `--agents '<json>'` (session, 2), managed (1), plugins (5). Same
  name: the higher priority wins. Scanned recursively; identity is the `name` field, not the file.
- Required: `name` (lowercase and hyphens, no `:`) and `description` ("when Claude should delegate";
  add "use proactively" to encourage it). Optional: `tools` (omitted = inherit all; a list where no
  entry resolves to a tool fails to launch), `disallowedTools`, `model` (`haiku`, `sonnet`, `opus`,
  `fable`, full id, `inherit`), `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`,
  `memory`, `background`, `effort`, `isolation: worktree`, `color`.
- The body is the subagent's whole system prompt — it does not get Claude Code's system prompt.
- Delegation is chosen from the task, the `description`, and context; you can also name the agent.

## 8. Skills and commands — [skills](https://code.claude.com/docs/en/skills)

- A skill is a directory with `SKILL.md`: `~/.claude/skills/<name>/`, `.claude/skills/<name>/`,
  or a plugin's `skills/`. `.claude/commands/<name>.md` still works as a command. The **directory
  name is the command** (`/deploy-staging`); `name` is only a display label outside plugins.
- Frontmatter is read only if `---` is the first line. Fields: `description` (recommended; with
  `when_to_use` truncated at 1,536 chars), `argument-hint`, `arguments`,
  `disable-model-invocation: true` (only you can run it), `user-invocable: false` (only Claude),
  `allowed-tools` (pre-approved for that turn), `disallowed-tools`, `model`, `effort`,
  `context: fork` + `agent`, `hooks`, `paths` (globs), `shell`.
- Substitutions: `$ARGUMENTS`, `$0`/`$1`, named `$arg`, `${CLAUDE_SESSION_ID}`,
  `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`. `` !`cmd` `` injects command output before Claude
  reads the skill.
- Skills load on demand, so moving workflow instructions out of CLAUDE.md into skills saves context.
- In `-p`, a prompt of `/skill-name` expands the skill.

## 9. Memory: CLAUDE.md — [memory](https://code.claude.com/docs/en/memory)

- Locations, loaded broad to specific: managed (`/etc/claude-code/CLAUDE.md` on Linux) → user
  `~/.claude/CLAUDE.md` → project `./CLAUDE.md` or `./.claude/CLAUDE.md` → local `./CLAUDE.local.md`
  (gitignore it yourself).
- Files from the cwd and every parent are **concatenated, not overridden**, root first; files in
  subdirectories load when Claude reads files there. HTML block comments are stripped.
- `@path` imports (relative to the importing file; max depth four hops; ignored inside code spans).
- `.claude/rules/*.md` load at launch; with `paths:` frontmatter only when matching files are used.
- Auto memory is separate (Claude's own notes); `/memory` opens both. Keep CLAUDE.md under ~200 lines.

## 10. MCP — [mcp](https://code.claude.com/docs/en/mcp)

- `claude mcp add [--scope local|project|user] [--transport stdio|http|sse] [--env K=V] <name> --
  <command> [args]`; everything after `--` goes to the server untouched.
- Scopes: **local** (default; this project, stored in `~/.claude.json`), **project** (`.mcp.json` at
  the project root, committed), **user** (all projects, `~/.claude.json`). Same name in several:
  local > project > user > plugin > claude.ai connectors; **the whole entry is taken, fields are not
  merged**.
- `.mcp.json`: `{"mcpServers": {"name": {"type": "stdio", "command": "…", "args": […], "env": {…}}}}`
  or `{"type": "http", "url": "…", "headers": {…}}`. `${VAR}` and `${VAR:-default}` expand in
  `command`, `args`, `env`, `url`, `headers`; an unset variable without a default stays literal and
  `claude mcp list` warns.
- Interactive sessions ask before using `.mcp.json` servers; `-p` and SDK sessions load them without
  asking. Keep one out with `disabledMcpjsonServers`, `--strict-mcp-config`, or `--setting-sources`.
- Tools are named `mcp__<server>__<tool>`; permission rules and hook matchers use that name.
- `MCP_TIMEOUT` (default 30 s) bounds startup; `claude mcp list` / `/mcp` show status.

## 11. CI: GitHub Actions — [github-actions](https://code.claude.com/docs/en/github-actions)

- `anthropics/claude-code-action@v1` with `prompt` (automation mode; without it, it answers the
  `@claude` trigger phrase), `claude_args` (any CLI flags: `--max-turns`, `--model`,
  `--allowedTools`, `--mcp-config`), `anthropic_api_key` **or** `claude_code_oauth_token`
  (`claude setup-token`, subscription), `github_token`, `settings`, `plugins`.
- Before running, the action requires the triggering actor to have write access on issue/PR events
  (`allowed_non_write_users` widens it) and rejects bots unless in `allowed_bots`.
- With a plain `prompt`, Claude has no shell or GitHub API access until tools are granted.
- Costs: Actions minutes plus tokens (or subscription usage with an OAuth token). The docs'
  levers: specific prompts, a concise CLAUDE.md, `--max-turns`, workflow `timeout-minutes`,
  `concurrency`.
- `claude -p` in a plain job step works too — the action is a wrapper, not a requirement.
- Routines ([routines](https://code.claude.com/docs/en/routines)) run a saved prompt on
  Anthropic's cloud on a schedule, an API call, or GitHub events (research preview, subscription).

## 12. Costs and models — [costs](https://code.claude.com/docs/en/costs), [model config](https://code.claude.com/docs/en/model-config), [prompt caching](https://code.claude.com/docs/en/prompt-caching)

- `/usage` shows the session's token use and estimated cost (list prices), prompt-cache hit rate,
  and, on subscriptions, plan usage bars and attribution to skills, subagents and MCP servers.
- Levers from the docs: Sonnet for most coding, Opus for hard reasoning, `model: haiku` for simple
  subagents; keep CLAUDE.md short and move workflows to skills; let hooks pre-filter large output;
  delegate verbose work to subagents; lower effort/thinking; specific prompts.
- Prompt caching is automatic; a model switch or CLAUDE.md edit breaks the cached prefix.
- `--max-budget-usd` compares against the same client-side estimate as `total_cost_usd`.

## 13. The rest, briefly

- **Sandboxing** ([sandboxing](https://code.claude.com/docs/en/sandboxing)): OS-level filesystem
  and network isolation for Bash (Seatbelt on macOS, bubblewrap on Linux). `sandbox.enabled`,
  `sandbox.filesystem.allowWrite/denyRead`, a network proxy with `allowedDomains`;
  `allowUnsandboxedCommands: false` removes the unsandboxed-retry escape hatch. Unlike Bash rules,
  this holds for every subprocess.
- **Plugins** ([plugins](https://code.claude.com/docs/en/plugins),
  [marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)): a directory with
  `.claude-plugin/plugin.json` bundling skills, agents, hooks, MCP and LSP servers; skills are
  namespaced `/plugin:skill`; test with `--plugin-dir`.
- **Output styles** ([output-styles](https://code.claude.com/docs/en/output-styles)), **status line**
  ([statusline](https://code.claude.com/docs/en/statusline): a command fed session JSON including
  cost), **checkpoints** ([checkpointing](https://code.claude.com/docs/en/checkpointing): file edits
  before each prompt are rewindable; Bash changes are not tracked; not version control),
  **worktrees** ([worktrees](https://code.claude.com/docs/en/worktrees): `--worktree`, subagent
  `isolation: worktree`).
- **Agent SDK** ([overview](https://code.claude.com/docs/en/agent-sdk/overview)): the same loop as a
  Python or TypeScript library.
- **Dev containers** ([devcontainer](https://code.claude.com/docs/en/devcontainer)): the reference
  container with a firewall, the documented place for `bypassPermissions`.

## 14. Verified locally (2026-09-14, Claude Code 2.1.270, macOS)

A 44-line fake of the Messages API (`POST /v1/messages`, streaming SSE) returned a scripted
assistant turn: a `Bash` tool call `rm -rf data`, then "done". Claude Code was run with
`ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`, `ANTHROPIC_API_KEY=sk-fake`, a throwaway
`CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, in a directory holding `data/`.

| Configuration | `data/` | `permission_denials` |
|---|---|---|
| `--allowedTools Bash` | deleted | `[]` |
| `.claude/settings.json` deny `Bash(rm *)` + `--allowedTools Bash` | kept | the call |
| `--permission-mode dontAsk`, no allow rule | kept | the call |
| `PreToolUse` hook (matcher `Bash`) exiting 2 on `rm*` + `--allowedTools Bash` | kept | the call |
| the same hook, run with `--bare` | **deleted** (hooks not loaded) | `[]` |
| the same hook with matcher `bash` (lower case) | **deleted** (never fired) | `[]` |
| `--bare` with only `CLAUDE_CODE_OAUTH_TOKEN` | — | exit 1, "Not logged in · Please run /login" |
| no `--bare`, only `CLAUDE_CODE_OAUTH_TOKEN` | — | works; sent as `Authorization: Bearer`, beta `oauth-2025-04-20` |

**Verified in the claude track's container (2026-09-14, 2.1.270, linux-arm64)**, with
`images/base/ubuntu-26.04-claude/claude_lab.py`; the six claude labs that depend on these results
pass the gate again on the container's Ubuntu 26.04 rebuild (2026-09-15):

| Configuration | Result |
|---|---|
| `-p` in a directory never trusted, allow `Edit(./docs/**)` in `.claude/settings.json`, `dontAsk` | edit **denied**; stderr: "Ignoring 1 permissions.allow entry from .claude/settings.json: this workspace has not been trusted" |
| the same allow rule in `.claude/settings.local.json`, `~/.claude/settings.json`, `--settings` or `--allowedTools` | edit allowed |
| deny rules in that untrusted `.claude/settings.json` | honoured |
| hooks, `CLAUDE.md` (with an `@` import), `.claude/agents/*.md`, `.mcp.json` in that untrusted directory | all loaded by `-p` |
| `defaultMode: bypassPermissions` in `~/.claude/settings.json`, no flag | every call runs, `permission_denials: []` |
| `dontAsk`, no Read deny: Read `.env`, Bash `cat .env` | both return the file (read-only commands need no permission) |
| `dontAsk`, deny `Read(./.env)`: Read, Grep on the file, `cat/head/tail/sort .env`, `cat /abs/.env` | refused; Grep over the directory skips the file |
| the same: Bash `grep -r TOKEN .`, `cat .e*` | **print the file** |
| `--tools "Read,Edit"`, model calls Bash | "No such tool available: Bash. Bash is disabled for this session" (not a permission denial) |
| default tool list of `-p` (no `--tools`) | no Grep or Glob tools; they exist when named in `--tools` |
| sessions | a transcript per run in `~/.claude/projects/<cwd with / as ->/<id>.jsonl`, tool results included; `--no-session-persistence` writes none |

What this settles for Norboten:

- **Labs can grade a real Claude Code offline.** A scripted model makes the agent attempt the
  dangerous action; the check inspects machine state (was the file deleted, did the hook log fire)
  and `permission_denials`. No token, no network, deterministic.
- **CI jobs rehearse for free** through the same fake (`ANTHROPIC_BASE_URL`).
- **Subscription-token CI jobs must not pass `--bare`**, so they load the repository's
  `.claude/` — which is then part of what the job runs and must be reviewed like code. Pin tools
  with `--allowedTools`/`--tools`, cap with `--max-turns`, and use `--setting-sources` or
  `--strict-mcp-config` to keep out what the job must not load.
- Besides the model calls, Claude Code made one `GET /api/hello` to the base URL; the fake must
  tolerate unknown paths.
