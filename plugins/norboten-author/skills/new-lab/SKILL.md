---
description: Turn a lab request into a finished Norboten lab — checks, faults, hints, solution, journal and theory — proven by the solvability gate. Use when asked to write, build or finish a lab, or to turn a labs/_drafts/ file into one.
argument-hint: "<one-line lab request, or a _drafts/<id>.md file> [--rated|--unrated] [--subagent]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(uv run norboten dev lint *), Bash(cp -r labs/_template *)
---

# A new lab, from request to a green gate

The request: $ARGUMENTS

A lab is done when the gate says so, not when the files look right. Work through these in order and
do not skip the proof steps; say plainly which ones you could not run.

## 1. The draft

Before anything else, ask what the request leaves open and the spec needs — **rated or unrated**
first (default unrated; `--rated`/`--unrated` answers it), then the story in symptoms, VM or
container, track, topics, images, difficulty, the symptom fix a check must refuse — in one short
numbered list with a default for each. Skip what the request already says.

**Rated** means the private repository (docs/rated-labs.md): the lab is written in
`rated/<track>/<id>/`, its draft in `rated/_drafts/<id>.md`, and nothing about it — fault, check,
solution, not even its idea in detail — goes into a public file, issue, commit message or pull
request. If `rated/README.md` does not exist, `rated/` is not checked out: stop and say so rather
than write rated material anywhere else.

If the request is a `labs/_drafts/<id>.md` (or `rated/_drafts/<id>.md`) file, start from it. A
rated lab is drafted here, in this session, into `rated/_drafts/<id>.md` — the drafting agent only
writes public drafts. Otherwise delegate to the
`norboten-author:lab-author` subagent (in a checkout without the plugin, the project's
`lab-author`) with the request and the answers: it writes that draft — the same agent the CI job
runs on `lab-request` issues. With `--subagent`, let it go on from there and report back; without,
read the draft critically in this session — it is a starting point.

Settle before writing any file, and tell the user what you chose:

- **one story** with symptoms a user would report (`docs/writing-a-lab.md` §1);
- **VM or container**: boot, kernel, disks, services or the reboot check mean `vm`; files, users,
  modes and one program's configuration can be `runtime: container` on `ubuntu-26.04-container`;
  a claude track lab is `runtime: container` on `ubuntu-26.04-claude`, and its checks script the model
  with `claude_lab.run()` (`labs/claude/claude-01-*` shows the pattern);
- the track (`Track` in `cli/src/norboten/models.py`), the next free number under `labs/<track>/`,
  one to three topics from `cli/src/norboten/topics.py`, and base images that exist in
  `images/registry.yaml`.

## 2. The lab

`cp -r labs/_template labs/<track>/<id>` (rated: `cp -r labs/_template rated/<track>/<id>`, then
`rated: true` in `lab.yaml`), then, following `docs/writing-a-lab.md` §3–6 and `docs/lab-spec.md`
where a detail matters:

1. **checks first** — read-only, each says what it observed, never what to do; true only when the
   cause is fixed. A rated lab splits every check (`docs/lab-spec.md` §13): `collect/NN_name.py`
   returns what it saw and never a verdict, `check/NN_name.py` is `judge(facts, ctx)`, a pure
   function that runs on the server;
2. **faults** — idempotent, no wall clock, no internet, nothing left behind that explains them;
3. **hints** — four levels per check; levels 1–2 name no path the solution touches; level 4 names
   the problem, never the command; `refs` give each level something to read — a topic journal
   heading or a man page at level 2, the lab's own journal from level 3 (`docs/lab-spec.md` §7);
4. **solution/solution.sh** — POSIX sh, as root, no reboot.

The project hook runs `norboten dev lint` on the lab after every edit and shows you what fails; fix
it before moving on. `uv run norboten dev lint labs/<track>/<id>` runs it by hand.

## 3. Proof

```sh
export NORBOTEN_HOME=/tmp/nb NORBOTEN_IMAGE_MIRROR=$PWD/images/out
uv run norboten dev validate <id>          # every image the lab claims; --keep to look inside
```

Ask the user before starting it: it boots real VMs and takes minutes. The gate must show every
check failing on the broken machine and passing after the solution, before and after the reboot
(and, for a `boot_after_break` lab, failing again after booting into the broken system).

Then the check that the gate cannot make: **a fix of the symptom rather than the cause must leave
a check failing.** Name the tempting symptom fix for each check and explain which check catches it;
where that is not obvious, play the lab (`uv run norboten`, Labs, Enter, `s`), apply only the
symptom fix, and press `c`.

## 4. Journal and theory

A **rated** lab gets neither a `journal.md` (a journal walks the very failure it grades) nor a
public `theory.yaml`; skip to step 5.

- `journal.md` beside the lab, with the sections in `cli/src/norboten/journal.py`
  (`REQUIRED_SECTIONS`), at least 800 words and five review questions with answers. The
  walkthrough is **run on a real machine** — a kept gate VM or the TUI — and shows the output it
  actually printed. Never invent command output.
- `theory.yaml` beside the lab: three or four questions to `docs/quiz-spec.md`, each with a man page
  or documentation reference; a question about what a snippet prints carries a `verify` block.
  Then `uv run norboten dev verify-quiz`.

## 5. Finish

- Delete the `labs/_drafts/` file the lab came from.
- `make lint` and `uv run python -m pytest -m "not docker"` pass.
- One commit for the lab (`feat(labs): <id> — <what breaks>`). Report the gate's measured time per
  image — those numbers are quoted on the site.
- A **rated** lab is two commits, in order: the lab, inside `rated/` (its own repository), and then
  the submodule pointer in the public repository, with a message that names no fault
  (`chore(rated): bump the rated labs`). Never `git add rated/<…>` from the public repository.
