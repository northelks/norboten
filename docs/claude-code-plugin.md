# The Claude Code plugin

`norboten-author` is a Claude Code plugin for writing Norboten content. You bring an idea — "a lab
where the cron job runs as the wrong user", "questions on systemd timers", "a journal on DNS" — and
it works out whether that is a lab, theory questions or a journal, asks what the specifications
need that the idea does not say, shows a plan, and after your yes does the work: in your session,
or in a subagent. It ends where the repository's own checks end — the linter, the question
pipeline, the solvability gate — and says plainly what it proved and what it did not.

It is for people writing content for Norboten or a fork of it. Learners never need it.

## What is in it

| | Name | Does |
|---|---|---|
| skill | `/norboten-author:idea <idea> [--subagent]` | the entry point: lab, questions or journal? asks, plans, waits for a yes, then hands over to one of the skills or agents below |
| skill | `/norboten-author:new-lab <request>` | a request or a `labs/_drafts/` file → checks, faults, hints with reading, solution, journal, theory, proven by `norboten dev validate` |
| skill | `/norboten-author:new-questions <topic>` | the thin subjects of a bank → the verification pipeline (write, blind solve by two other models, critic, Docker run, dedup) → your review → the bank |
| skill | `/norboten-author:new-journal <topic or lab>` | a topic or lab journal to the contract in `cli/src/norboten/journal.py`, walkthrough run on a real machine |
| skill | `/norboten-author:captures [name]` | re-renders the TUI screenshots the site shows, and checks what they show |
| agent | `norboten-author:lab-author` | drafts a lab into `labs/_drafts/<id>.md` — the same agent CI runs on `lab-request` issues |
| agent | `norboten-author:question-author` | runs the question pipeline from an agreed plan and reports survivors and rejections |
| agent | `norboten-author:journal-author` | drafts a journal into `journals/_drafts/`, every walkthrough step it could not run marked `TODO` |
| hook | after `Edit` and `Write` | formats Python with ruff and runs `norboten dev lint` on the lab a file belongs to; a failing lint goes back to Claude |
| MCP server | `norboten` | Norboten's public MCP server, `https://api.norboten.org/mcp` — docs search, labs, journals, a quiz ([The MCP server](../mcp/index.html)) |

Every skill is started by a person (`disable-model-invocation`): each one boots machines, spends
subscription usage or rewrites committed files. Measured with `claude plugin details` (Claude Code
2.1.272): about 540 tokens are added to every session for the listings; a skill's body, 450–1,100
tokens, is paid when it runs.

## Asking first

The specifications decide what a good question is. For a lab the plugin needs a story told in
symptoms, VM or container, the track and topics, the images, and the symptom fix that a check must
refuse; for questions, the bank, the subjects and the difficulty; for a journal, the reader and the
machine its walkthrough will be run on. It asks only what the idea leaves open, as one short
numbered list with a default for each, so "defaults" is a complete answer. Then it writes the plan
— files, what each holds, what will be run to prove it, what needs you (a VM for minutes, your
subscription for drafting) — and waits.

## Rated or unrated

The first thing it asks about a lab or a bank is whether it is **rated** or **unrated**
(docs/rated-labs.md); unrated is the default, and `--rated` or `--unrated` answers it without a
question. Unrated work lands where it always has: `labs/<track>/<id>/`, `quizzes/<topic>.yaml`.
Rated work goes into the private repository checked out at `rated/` — `rated/<track>/<id>/` with a
collector and a judge per check (docs/lab-spec.md §13), `rated/quizzes/<topic>.yaml`, drafts in
`rated/_drafts/` and `rated/quizzes/_drafts/` — and nowhere else:

- when `rated/README.md` is missing, the submodule is not checked out and the skill stops instead of
  writing rated material into the public tree (`norboten dev draft-questions --rated` refuses too);
- a rated lab has no journal and no public theory bank, and `new-journal` declines one;
- rated work is two commits: inside `rated/`, then the submodule pointer in the public repository,
  with a message that names no fault or question;
- the drafting agent writes only public drafts, so a rated lab is drafted in your session; and the
  CI job that answers `lab-request` issues declines one labelled `rated` with a comment, before any
  model runs, because an issue is public.

The project hook lints a lab under `rated/` exactly as one under `labs/`.

## In your session or in a subagent

After the plan, `idea` asks once where the work runs, unless you passed `--subagent`:

- **here** — the matching skill runs step by step in your session. You see and steer every step.
  Best when you want to shape the result.
- **a subagent** — the agreed plan goes to the matching agent through the Agent tool. It works in
  its own context and returns a draft and a report, and your session stays small. Best for a first
  draft of something already well described.

The questions always come first, in your session: a subagent cannot ask you anything, and a skill
run with `context: fork` runs in the background with a narrower set of tools. So the plugin does
not fork its skills; it asks, then delegates the part that needs no answers. Whichever runs, the
session that started it reads the result and runs the linters itself before it reports.

## Install

From the repository, once it is published on GitHub:

```text
/plugin marketplace add northelks/norboten
/plugin install norboten-author@norboten
```

or from a shell, `claude plugin marketplace add northelks/norboten` and
`claude plugin install norboten-author@norboten`. From a clone, the path works the same way:
`claude plugin marketplace add ./norboten`. The skills expect a Norboten checkout (or a fork) as
the working directory, with its venv (`uv sync --all-packages --all-extras`).

**Inside a Norboten checkout you install nothing.** Its `.claude/settings.json` declares the
repository itself as the `norboten` marketplace (a `directory` source, `"."`) and enables the
plugin, so once you trust the folder, `/norboten-author:idea` is there, read from the working tree
— an edit to a skill applies to the next session. Checked on 2026-09-15 with Claude Code 2.1.272:
an interactive session in the checkout completes `/norboten-author:` and sends the `idea` skill
with its argument to the model. A headless `claude -p` in an untrusted checkout, which is how CI
runs, does not load it; the CI job keeps using the project's own `lab-author` and hook, byte-identical
copies of the plugin's (a test compares them), and where both hooks are registered the plugin's
copy steps aside.

## Update

A plugin with a `version` is updated when that version changes. `/plugin marketplace update
norboten`, then `/plugin update norboten-author@norboten` (or the same under `claude plugin`), or
turn on auto-update for the marketplace in `/plugin`.

## Publishing a new version

1. Change the plugin under `plugins/norboten-author/`.
2. Raise `version` in both `plugins/norboten-author/.claude-plugin/plugin.json` and the plugin's
   entry in `.claude-plugin/marketplace.json` — a test fails when they differ.
3. `claude plugin validate --strict .` and `claude plugin validate --strict plugins/norboten-author`
   (the tests run both), then `uv run python -m pytest tests/test_claude_plugin.py`: it installs the
   plugin into a throwaway configuration and expands every skill in a real `claude` against a
   scripted model, spending nothing.
4. Commit, tag `plugin-v<version>`, push. Users get it with `/plugin marketplace update`.

## How it is tested

`tests/test_claude_plugin.py` checks the manifests, every skill's frontmatter and the files it
cites, that plugin agents use only fields a plugin agent may carry, that the CI copies match, and
that the plugin's hook steps aside; then, with Claude Code installed, validates both manifests with
`--strict`, installs the plugin from the checkout into a throwaway `CLAUDE_CONFIG_DIR`, and runs
each skill as `/norboten-author:<skill> ARG-MARKER` against the scripted Messages API from
`automation/`: the skill's text and the argument must reach the model, and the three agents must be
offered to it.
