# Theory question specification

**Status: normative.** The TUI, the question-bank linter and the drafting pipeline
(`cli/src/norboten/questions/`) all implement this document. Machine-readable form:
`cli/src/norboten/models.py` (`QuestionBank`, `Question`); `make schema` exports
`docs/schema/quiz.schema.json`.

Theory is a separate way to practise. It **never** affects a lab's grade — labs are graded only
against machine state.

---

## 1. Where questions live

| Location | Shown as |
|---|---|
| `quizzes/<topic>.yaml` | a topic in the TUI's **Theory** section (Linux, networking, Bash, Python, Ansible, Terraform, Claude Code, Ollama, memory & CS) |
| `labs/<track>/<lab>/theory.yaml` | the lab's **Theory** tab |
| `~/.norboten/quizzes/<topic>-yours.yaml` | a learner's own practice bank, drafted with `g` (section 5) |
| `rated/quizzes/<topic>.yaml` | a **rated** bank, in the private repository; served only by the API (section 6) |

---

## 2. A question bank

```yaml
schema_version: 1
topic: networking                # slug; for a lab's theory.yaml, the lab id
topics: [networking, firewall-selinux]   # taxonomy slugs (lab-spec §12); questions inherit them
title: Networking
description: Addresses, routes, sockets and name resolution, from a Linux shell.
questions:
  - id: net-004                  # <prefix>-NNN, unique across every bank in the repo
    type: single                 # single | multiple
    difficulty: 2                # 1-5
    prompt: Which command shows listening TCP sockets together with the owning process?
    choices:
      - {id: a, text: "ss -tlnp"}
      - {id: b, text: "ip route show"}
      - {id: c, text: "netstat -r"}
      - {id: d, text: "arp -n"}
    answer: [a]
    explanation: >-
      ss -t selects TCP, -l listening sockets, -n skips name resolution, -p shows the process.
      ip route and netstat -r print the routing table; arp -n the neighbour cache.
    references: ["man 8 ss"]
    tags: [sockets]
```

| Field | Rule |
|---|---|
| `id` | `^[a-z0-9]+-\d{3}$`, unique across all banks. |
| `type` | `single`: exactly one correct choice. `multiple`: one or more; the learner must select exactly the correct set. |
| `difficulty` | 1–5. Also sets the clock a rated question runs against (section 3). |
| `topics` | Optional. Taxonomy slugs; narrows the bank's `topics` for this one question. |
| `prompt` | 10–600 characters. A question, not a trick. |
| `code` | Optional snippet shown under the prompt, with `code_lang` (`bash`, `python`, `hcl`, `yaml`, `json`, `text`). |
| `choices` | 3–6, ids `a`–`f` in order, texts unique. No "all of the above", "none of the above", "both a and b". The right answer's position is spread across the bank, not always first. |
| `answer` | Choice ids; consistent with `type`. |
| `explanation` | ≥ 30 characters. Why the answer is right **and** why the tempting wrong ones are wrong — naming a choice by what it says, never by its letter, because the TUI shows the choices in a random order. |
| `references` | ≥ 1: a man page (`man 8 ss`) or an official documentation URL. |
| `verify` | Optional. See section 4. Required for generated questions about program output. |

---

## 3. Grading in the TUI

- A run shows the questions, and each question's choices, in a random order.
- A single-choice question is right when the chosen id is the answer.
- A multiple-choice question is right only when the selected set equals the answer set — no
  partial credit, as in the exams this prepares for.
- After every answer the TUI shows the explanation and the references, right or wrong.
- Results are kept per topic in `~/.norboten/progress.json`: answered, correct, best streak.

**Rated questions run against a clock**, derived from the difficulty — a question you have to
think about is not a question you have to look up:

| difficulty | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| seconds | 15 | 15 | 20 | 25 | 30 |

A question carrying a `code` snippet gets 10 seconds more, because it has to be read before it can
be answered. When the clock runs out the question is recorded as wrong with nothing selected, and a
correct answer that arrives late does not count either.

Only a **rated bank** (section 6) is rated. On an unrated bank the same clock is there as a timed
run, at exam pace, and the run is recorded on the profile without moving a rating — the bank's
answers are public. Untimed runs are not sent at all. Theory keeps results only — no command logs,
nothing to replay.

---

## 4. Executable verification

A question about what a snippet does carries the snippet in `verify`:

```yaml
    code: |
      x=5; x+=1; echo "$x"
    code_lang: bash
    verify:
      runtime: bash              # bash | python
      code: |
        x=5; x+=1; echo "$x"
      expect: output_is_answer   # the snippet's stdout, stripped, equals the correct choice's text
```

`norboten dev verify-quiz` runs every `verify` block in a throwaway container
(`--network none`, read-only root, 10 s limit) and fails if the output does not match the key.
It runs in CI for every bank, and in the drafting pipeline for every drafted question.

---

## 5. Drafted questions

Questions are drafted by models and kept only after a pipeline that runs where they are drafted —
never on the server, which neither generates nor stores questions. A draft survives only if it:

1. validates against this spec;
2. is answered **identically to the key** by at least two other models that never saw the key;
3. passes a critic review (no factual error, no ambiguity, no second defensible answer);
4. passes its `verify` block, when it has one;
5. is not a near-duplicate of a question already in a bank or a draft (a text similarity of
   0.85 or more, `difflib`, on the prompt).

It keeps its provenance — generator, verifiers and their answers, execution result, date.

**A published bank** is filled on a maintainer's machine, and published with the repository:

```sh
uv run norboten dev draft-questions networking --count 5 --about "firewalld zones"
```

By default every model is reached through the local Claude Code, headless and on a subscription
(`claude-code/opus` writes, `claude-code/sonnet` and `claude-code/haiku` answer blind, Sonnet
reviews), so no API key is needed; each run gets no tools and an empty working directory. Models
of one family share blind spots, so where keys exist a mixed set (`--verifiers
claude-code/sonnet,gpt-5-codex`) is the stronger check. What passes lands in
`quizzes/_drafts/<topic>.yaml` with its provenance — never in a bank: a person reads each draft,
moves the good ones in, and `norboten dev verify-quiz` runs again. The
`/norboten-author:new-questions` skill of the Claude Code plugin walks through exactly this.

**A learner's own bank** comes from `g` on a Theory bank (docs/tui-reference.md): the same
pipeline, with Claude Code on the learner's subscription when `claude` is installed, otherwise
their exported `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY` — a writer and two other
models are required. A question with a snippet is dropped when Docker cannot run it. Survivors go to
`~/.norboten/quizzes/<topic>-yours.yaml` (all attempts, with provenance, in
`~/.norboten/quizzes/_drafts/`). Nobody else has reviewed them, so such a bank is practice only:
never rated, never sent to the server.

---

## 6. Rated banks

A rated bank has exactly the shape of section 2 and lives in the private repository
(`rated/quizzes/<topic>.yaml`, docs/rated-labs.md). Nothing about it reaches a learner's disk: the
server serves a run one question at a time and grades every answer itself.

```
POST /rated/quiz/sessions {topic}           → up to 10 of the bank's questions, shuffled; the first,
                                               without answer, explanation or references
POST /rated/quiz/sessions/{id}/answers      → right or wrong, the answer, the explanation, the
       {question_id, selected}                references; the last one closes and rates the run
POST /rated/quiz/sessions/{id}/next         → the next question; its clock starts now
```

- **The clock is the server's.** A question is timed from the moment it was served, against
  section 3's seconds plus two for the round trip. An answer after that is wrong, and an empty
  selection is how a client says its own clock ran out. Asking for the next question is separate
  from answering, so reading an explanation costs no time.
- **A run is one game**, as in section 3: the bank's topics, the mean difficulty of the questions
  served, won at 70%. Every question served counts, answered or not — starting another run closes
  this one on what it had, and a run left for an hour expires the same way.
- A learner's own banks and the published banks under `quizzes/` are never rated.
