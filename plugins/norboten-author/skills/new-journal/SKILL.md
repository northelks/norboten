---
description: Write a Norboten journal — a topic journal (journals/<topic>.md) or a lab's own journal.md — to the journal contract, with a walkthrough whose every command and output come from a real machine. Use when asked for a journal, a study text or deeper reading on a topic or lab.
argument-hint: "<topic slug or lab id> [what it should cover] [--subagent]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(uv run norboten dev lint *)
---

# A journal, to the contract

Asked for: $ARGUMENTS

A journal is a study document: it explains the mechanism, walks through one failure, names the
wrong turns people actually take, and ends with questions answered without looking. The contract
is `cli/src/norboten/journal.py` — read `REQUIRED_SECTIONS` and `Journal.validate()` first.

A **rated** lab (`rated: true`, under `rated/`) has no public journal: it would walk through the
failure the lab grades. Decline one, and say why. A note — how something in Norboten was built,
`journals/notes/<slug>.md` — is a journal with its own rules (`Journal._validate_note`).

## 1. What and for whom — ask what is missing

In one short numbered list, with a default for each, ask only what the request leaves open:

- **which journal**: a topic journal at `journals/<slug>.md`, where the slug is a topic in
  `cli/src/norboten/topics.py`, or a lab journal at `labs/<track>/<id>/journal.md`;
- **the reader**: what they already know, and what they should be able to do afterwards;
- **the failure** the walkthrough follows, and **the machine** it will be run on: a kept gate VM
  (`uv run norboten dev validate <lab> --keep`), a lab in the TUI, or a container for container
  material. Nothing in the walkthrough may be written from memory.

Then show the outline — the `###` subsections under "The mechanism", the failure, five or more
review questions — and wait for a yes.

## 2. Write it

Front matter with `title`, `topics` (taxonomy slugs) and `minutes`, then the sections in order:

- `## What you should be able to do after this` — a short imperative list;
- `## The mechanism` — `###` subsections, each one idea, with the files and commands involved;
- `## A failure, walked through` — commands **run on the machine named in step 1**, with the output
  they printed, trimmed but never edited. Say which machine and version it was run on;
- `## Common wrong turns` — what people try, and exactly why it does not work;
- `## Cheat sheet` — the commands, in one block;
- a topic journal adds `## Symptoms and causes` (a table: symptom, usual cause, the evidence),
  `## Exercises` (tasks to try on a lab machine) and `## Sources` (man pages and official
  documentation, each checked), and a `covers:` line in the front matter — one technical line of what
  it goes through; a lab journal adds `## Going deeper`, where its hints' reading leads;
- `## Review` — numbered questions, each followed by an indented `> answer`.

At least 800 words outside code, and five review questions with answers. Anchors matter: hints
point at `###` headings (`journal:<id>#<anchor>`), so do not rename a heading a hint uses without
changing the hint.

With `--subagent`, give the outline and the answers to `norboten-author:journal-author`; it writes
the prose into `journals/_drafts/<slug>.md` and marks every walkthrough step it could not run as
`TODO: run on <machine>`. Those steps are then run here, on the machine, and the draft moved into
place, before the journal is finished.

## 3. Check it

```sh
uv run norboten dev lint journals                 # topic journals
uv run norboten dev lint labs/<track>/<id>        # a lab's journal, with its lab
uv run norboten dev lint labs                     # every hint anchor still resolves
```

Report what the linter says, which walkthrough steps were run and where, and anything left as
TODO. One commit (`docs(journals): <slug> — <what it covers>`).
