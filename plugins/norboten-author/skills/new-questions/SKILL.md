---
description: Add theory questions to a Norboten bank through the verification pipeline — generate, blind solve by two other models, critic, Docker check, dedup — then review and move the survivors in. Use when asked for new theory or quiz questions.
argument-hint: "<topic> [how many] [what about] [--rated|--unrated] [--subagent]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(uv run norboten dev draft-questions *), Bash(uv run norboten dev verify-quiz), Bash(man *)
---

# New theory questions, verified before anyone reads them

Asked for: $ARGUMENTS

Questions are not written straight into a bank. The pipeline in
`cli/src/norboten/questions/pipeline.py` writes and checks them; you choose what to ask for and
review what survives. `docs/quiz-spec.md` is the standard for both.

## 1. What is missing

First, rated or unrated (default unrated; `--rated`/`--unrated` answers it). A rated bank is
`rated/quizzes/<topic>.yaml` in the private repository, served one question at a time by the API
(`docs/quiz-spec.md` §6); if `rated/README.md` does not exist the private repository is not checked
out — say so, and do not write rated questions anywhere else.

Read the bank (`quizzes/<topic>.yaml`, a lab's `theory.yaml`, or `rated/quizzes/<topic>.yaml`). Count questions by difficulty
and by `tags`, and pick the subjects the bank covers thinly. If the request leaves the bank, the
count or the subjects open, ask — one short numbered list, a default for each. Tell the user the
plan: which subjects, how many each, at which difficulty, and wait for a yes.

With `--subagent`, give the agreed plan to `norboten-author:question-author`: it runs the drafting
below in its own context and returns what survived and what was rejected. Step 3, the review, is
still yours.

## 2. Draft through the pipeline

One call per subject, a few questions at a time:

```sh
uv run norboten dev draft-questions <topic> --count 3 --difficulty 3 \
    --about "<one subject, concrete: e.g. systemd timers that never fire after a reboot>"
```

Each attempt is four headless Claude Code runs on the user's subscription — Opus writes, Sonnet and
Haiku answer without the key, Sonnet reviews — each with no tools. Say how many attempts you will
make before starting. If the user has `OPENAI_API_KEY` or `GEMINI_API_KEY` exported, pass
`--verifiers claude-code/sonnet,gpt-5-codex`: two model families catch more than one.

For a rated bank add `--rated`: the drafts go to `rated/quizzes/_drafts/<topic>.yaml` instead.

Survivors land in `quizzes/_drafts/<topic>.yaml` with their provenance; rejections are listed there
with the stage and the reason. If one stage rejects most attempts, report it rather than retrying
until something passes — a subject the solvers keep disagreeing on is usually ambiguous.

## 3. Review every survivor yourself

The pipeline catches wrong keys and ambiguity between models; it does not catch a question that is
correct but useless. For each accepted question:

- it tests something that matters on a real machine, not trivia or a version number;
- the reference exists and supports the answer — open the man page (`man 5 crontab`) or read the
  documentation page;
- the explanation says why the answer is right **and** why the tempting wrong ones are wrong;
- it is not a rewording of a question already in the bank (dedup only catches near-copies).

Drop what fails, and say why.

## 4. Move them in

Append the questions you kept to the bank **without** their `provenance` key, with ids that follow
the bank's prefix and are unique across every bank. Remove them from the drafts file. Then:

```sh
uv run norboten dev verify-quiz      # loads every bank and runs every verify block in Docker
uv run norboten dev verify-quiz --rated   # the rated banks too
```

Report: attempts, accepted by the pipeline, kept after review, and the rejection stages. One
commit per bank (`feat(theory): <topic> — <n> questions on <subjects>`); a rated bank commits
inside `rated/`, then the submodule pointer in the public repository, naming no question.
