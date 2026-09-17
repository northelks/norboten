---
description: Start here with an idea for Norboten content — "a lab where cron jobs run as the wrong user", "questions on systemd timers", "a journal on DNS". Works out whether it is a lab, theory questions or a journal, asks what the specs need that the idea does not say, shows a plan, and after a yes does it in this session or hands it to a subagent.
argument-hint: "<the idea, in a sentence> [--rated|--unrated] [--subagent]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob
---

# From an idea to Norboten content

The idea: $ARGUMENTS

You are in a Norboten checkout (or a fork of one). Everything you make is judged by the repository's
own specs, not by how it looks: `docs/lab-spec.md` and `docs/writing-a-lab.md` for labs,
`docs/quiz-spec.md` for theory questions, `cli/src/norboten/journal.py` for journals. Read the part
you need before you ask anything, so that you ask only what the spec requires and the idea leaves
open. If `docs/lab-spec.md` is not there, say this is not a Norboten checkout and stop.

## 1. What is it?

Decide which of the three the idea is, and say why in one sentence:

- **a lab** — something breaks on a machine and a person fixes it; the result is machine state a
  check can read, before and after a reboot;
- **theory questions** — knowledge to test, with one right answer that a reference supports;
- **a journal** — reading: how a mechanism works, one failure walked through, the wrong turns.

An idea can be two of them (a lab and its journal): propose doing one first.

A lab or a bank is also **rated or unrated** (docs/rated-labs.md). Unrated is public, offline, answers
included, and the default. Rated goes into the private repository checked out at `rated/`, is graded
on the server, and is what moves a rating; a rated lab has **no public journal**, so a journal idea
for a rated lab is declined. `--rated` or `--unrated` in the arguments settles it without asking.

## 2. Ask what is missing — in plain text, all at once

Ask only what the idea does not already answer, as one short numbered list the person can reply to
in a line. Offer a default for every question so that "defaults" is a complete answer. For a lab or
theory questions the **first** question is rated or unrated (default: unrated). If the answer is
rated and `rated/README.md` does not exist, the private repository is not checked out: say so and
offer unrated instead — rated material is never written into the public tree.

For a **lab**: the story in symptoms a user would report; VM or container (boot, disks, services
and the reboot check need a VM; files, users, modes and one program's configuration can be a
container); the track and one to three topics from `cli/src/norboten/topics.py`; base images from
`images/registry.yaml` that serve the track; difficulty 1–5 and minutes; the tempting symptom fix
that a check must refuse.

For **theory questions**: the topic bank (`quizzes/<topic>.yaml`) or a lab's `theory.yaml`; how
many, at which difficulty; the subjects, concretely; whether they can carry a `verify` snippet.

For a **journal**: a topic journal (`journals/<topic>.md`, named after a topic slug) or a lab's
own; the reader's level; the one failure the walkthrough follows, on which machine it will be run.

## 3. The plan, then wait

Write the plan as a short list: the files that will appear, what each check or question or section
holds, what will be run to prove it (lint, `norboten dev validate`, `verify-quiz`), and what needs
the person (a VM for minutes, their subscription for question drafting). For rated work the files
are under `rated/` and the plan says so, with the two commits it takes: the private repository
first, then the submodule pointer in the public one. Then stop and wait for a
yes. Change the plan if they answer anything else.

## 4. Where the work runs

If the arguments contain `--subagent`, use the subagent without asking. Otherwise ask once:

- **here, in this session** — you follow the matching skill (`/norboten-author:new-lab`,
  `/norboten-author:new-questions`, `/norboten-author:new-journal`) step by step, and the person
  can steer as you go; best when they want to shape the result;
- **in a subagent** — hand the agreed plan to the matching agent (`norboten-author:lab-author`,
  `norboten-author:question-author`, `norboten-author:journal-author`) through the Agent tool. It
  works from the plan alone, in its own context, and returns a draft and a report; this session
  stays small. Best for a first draft of something already well described.

A subagent cannot ask questions, so give it everything from steps 2 and 3 in its prompt: the
answers — rated or unrated among them — the file paths, and what "done" means. When it returns, read what it wrote, run the
linters yourself, and report plainly what is proven and what is not.

## 5. Finish

Nothing is finished until the repository's own checks say so: `make lint`, and for a lab the
solvability gate (`make validate LAB=<id>`, which boots VMs — ask first). Report the measured
results; never describe a draft as a lab, or a question as verified, before those have run.
