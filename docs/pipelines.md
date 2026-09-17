# Pipelines

Everything that turns source into something a learner or a viewer sees, step by step. Each
pipeline names its entry point, its inputs and outputs, and what makes it refuse.

## 1. A lab, from a pull request to a learner's machine

```
labs/<track>/<id>/  ──lint──►  gate (every base image)  ──merge──►  tag v*  ──►  OCI artifact  ──►  u in the TUI
 lab.yaml                      break → all checks fail                         ghcr.io/…/norboten-labs/<id>
 briefing.md                   solution → all pass                              signed with cosign
 break/ check/ hints.yaml      reboot → all pass again
 solution/ theory.yaml journal.md
```

| Step | Entry point | Refuses when |
|---|---|---|
| **Lint** | `norboten dev lint` (`make lint-labs`, pre-commit, CI) | the manifest breaks `docs/lab-spec.md`: an objective with no check, a check id out of order, a hint ladder short of four levels, a guest script importing outside the standard library, a journal missing a section |
| **Gate** | `norboten dev validate <lab>` (`lab-validate.yml`, a matrix of the labs a change touches × the images each supports) | a check passes on the broken machine, or fails after the reference solution, before or after the reboot |
| **Publish** | `lab-publish.yml` on a `v*` tag | — builds `images/Dockerfile.lab` (`FROM scratch`, one layer with the lab at `/lab`), pushes `:<version>` and `:latest`, signs the digest keylessly |
| **Pull** | `u` in the Labs section → `labs.store.pull` | the tag does not resolve, the manifest id does not match the repository name |

A change to the runner, the guest-facing engine code, the image registry or the baseline role
validates every lab, not just the touched ones (`.github/scripts/changed_labs.py`).

## 2. A golden base image

```
upstream cloud image ──fetch, verify sha256──► Lima VM ──ansible lab_baseline──► finalize.sh ──► qemu-img convert -c
(pinned in images/registry.yaml)                                                  (no build traces)     images/out/<id>-<arch>.qcow2 + .json
                                                                                                         ──oras push──► ghcr.io/…/norboten-base/<id>:<version>
                                                                                                         ──PR──► new digest in registry.yaml
```

Entry point: `images/build.py <id>` (`make image IMAGE=…`), `image-publish.yml` on demand. The
upstream download is resumable and digest-checked before anything boots. The baseline installs
every package the track needs (nothing is installed while a learner works), puts GRUB and the
kernel on the serial console, sets a persistent journal and per-command history, removes what slows
a cold boot (NoCloud-only cloud-init, a 1 s GRUB timeout, chrony's initial step on Alpine), and
installs git for the recording diffs. A new digest in `registry.yaml` re-runs the gate for every
lab.

Measured builds (Apple Silicon, 2026-09-12): alpine 90 s / 105 MB, rocky-10 166 s / 835 MB. The
three Ubuntu 26.04 images are measured when they are first built.

## 3. A theory question

The repository's banks (`quizzes/*.yaml`, each lab's `theory.yaml`) are validated against
`docs/quiz-spec.md`, and every question with a `verify` block is executed by `quiz-verify.yml`. New
questions are drafted on a maintainer's machine (`norboten dev draft-questions`) or, for a learner's
own practice bank, by `g` on Theory — through `cli/src/norboten/questions/pipeline.py`, never on the
server:

```
generate ──► schema ──► solve blind ×2 ──► critic ──► execute ──► dedup ──► a draft
 writer       Question    other models,     a second    container,  against    with provenance
 model        model +     no key in the     defensible  no network  the banks  → read → a bank
              spec rules  prompt            answer?
```

| Stage | Rejects |
|---|---|
| setup | fewer than two usable models other than the writer (`--min-verifiers`) |
| schema | anything the `Question` model or the spec refuses |
| blind solve | any verifier answering differently from the key, or calling it ambiguous |
| critic | a second defensible answer, a wrong fact, a trick question |
| execute | a `verify` snippet whose output is not the key (for a learner, also one Docker could not run) |
| dedup | a prompt 85% similar (difflib) to one already in a bank or a draft |

A surviving draft keeps its provenance: the writer, each solver's answer and note, the critic's
verdict, the sandbox's output. A maintainer reads it before it moves into a published bank.

## 4. A recording, and a live session

```
p / P on a lab ──► PTY recorder ──► frames (asciicast v2) ──┬──► ~/.norboten/plays/*.cast + .log.json
                     │                commands              │
                     └── git in the guest ──► diffs ─────────┘
                                                            └── P only: POST /play/sessions/<id>/frames every ~2 s
                                                                   ├─► play_batches (PostgreSQL, 7 days)
                                                                   └─► PUBLISH play:<id> (Redis) ──► SSE ──► every viewer
```

The shell runs in a pseudo-terminal and bytes are copied both ways, so pipes, editors and colour
record exactly. Commands are lifted from what was typed; diffs come from keeping the guest's
watched directories under git for the session (`/var/lib/norboten/watch`, with the work tree
pointing at `/etc` so no `.git` appears there), and a diff is attributed to the last command that
finished before it was taken. A viewer's stream subscribes to the Redis channel first, replays
what is already stored, then forwards what is published — so a viewer can arrive before the first
frame or long after it.

The site's canned recordings are made the same way with a scripted typist:
`norboten dev record <slug>` boots the lab on a fresh VM, types `site/streams/<slug>.script`,
and writes `site/streams/<slug>.json`. Only the typing is scheduled; the machine, its output and
its diffs are real.

## 5. The consultant's index

```
docs/*.md ─┐
journals ──┼─ without the walkthrough ─┐
briefings ─┤                           ├─► passages (≤180 words, split at headings) ─► BM25 index (in memory, at API start)
questions ─┘   no solution file,       │                                          └─► site/dist/ask-index.json (at site build)
               no level 3–4 hint ───────┘
```

`retrieval.build_corpus()` builds both from the same function, so the API and the browser fallback
search the same passages. The API ranks with BM25 (k1 1.5, b 0.75), hands the top five to the model
chosen from `NORBOTEN_CONSULTANT_MODELS` (Ollama first), and puts the answer through the tutor's
guard (`norboten.tutor.guards`) before it leaves. The browser, when the API cannot be reached, ranks the same passages with
the same tokenizer (`site/static/ask-engine.js`) and quotes the best three.

## 6. Analytics

```
users + attempts ──► pandas frames ──► charts (matplotlib → SVG) + facts.json ──► /analytics/
(PostgreSQL nightly,                    TF-IDF + networkx relation graph
 or seed/accounts.json at site build)   k-means on topic ratings
```

`python -m norboten_api.analytics --database-url … --out <site>/analytics` on the server
(`norboten-analytics.timer`, 04:10), or from the sample population during `site/build.py`. Ratings
are replayed through the same `accounts.rate` the API uses, so the rating charts are not a second
implementation. The page's sentences read their numbers from `facts.json`, which the job writes
with the charts.

## 7. The site

`site/build.py` renders everything from the repository — labs, briefings, journals, docs, question
counts, the sample population, the recordings, the captures, the analytics — into `site/dist`
(224 pages). `site/capture.py` (`make captures`) renders the TUI screenshots by driving the real
app headlessly. The deploy workflow builds the site against the production API and rsyncs it to
the server, where Caddy serves it.

## 8. The server

See [CI/CD](../ci-cd/index.html) for the workflow and [Deploying the server](../deploy/index.html)
for the machine. In one line: push to main → tests → API image → site → rsync → `deploy.sh`, which
waits for `/readyz` and rolls back by itself.
