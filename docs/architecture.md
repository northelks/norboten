# Architecture

Two halves, joined by HTTPS and nothing else.

- **The learner's machine** runs the product: a terminal interface that drives real virtual
  machines, a standard-library runner inside each VM that breaks it and grades it, and everything
  needed to do that offline once an image and a lab are cached. The tutor and the review of a
  finished attempt run here too, on the learner's own Claude Code, key or Ollama.
- **One server** runs what cannot live on a learner's machine: accounts and ratings, the
  consultant on its own Ollama (no hosted model is called from it), live and recorded
  sessions, analytics, and the site. Theory questions are not generated there: they are drafted on
  a maintainer's or learner's machine (`cli/src/norboten/questions/`). It is one Docker Compose project on one machine.

```
the learner's machine                                   one server (Docker Compose)
┌─────────────────────────────────────┐                ┌──────────────────────────────────────────────┐
│ norboten  (Textual TUI)             │     HTTPS      │ caddy ── TLS · the site · reverse proxy      │
│   sections · lab screen · doctor    │ ─────────────► │   │                                          │
│   engine ─ lima (pinned) ─ QEMU     │                │   ├─ api (FastAPI, 2 workers)                │
│   │                                 │                │   │    auth · labs · quiz · profile · mcp     │
│   ▼                                 │                │   │    play · chat · telemetry · metrics      │
│ ┌─────────────────────────────┐     │                │   │      │        │         │                 │
│ │ lab VM (Rocky · Ubuntu ·    │     │                │   │  postgres   redis    ollama              │
│ │  Alpine), golden image      │     │                │   └─ grafana ── prometheus ── exporters      │
│ │  norboten-runner            │     │                │                                              │
│ │  break/ check/  grader      │     │                └──────────────────────────────────────────────┘
│ └─────────────────────────────┘     │                ┌──────────────────────────────────────────────┐
└─────────────────────────────────────┘  pull images   │ GitHub: Actions (tests · gate · deploy)      │
                                        ◄───────────── │   GHCR (API image · golden images · labs)    │
                                                       └──────────────────────────────────────────────┘
```

## The client

`cli/src/norboten`. `norboten` with no arguments opens the TUI; see the
[TUI reference](../tui-reference/index.html).

| Module | Responsibility |
|---|---|
| `tui/` | the interface: `app.py` (main screen, the sections along the top on 1–8 and the arrows, panels, activity log), `sections.py` (Home, Labs, Theory, Journals, Play, Ratings, You, System), `lab.py` (the lab screen), `quiz.py`, `widgets.py` (terminal player on pyte, heatmap, doctor panel), `data.py` (API calls) |
| `session/` | the engine: start, break, check with reboot, reset, hints, surrender; the solvability gate; live checks |
| `lima/` | install and pin Lima 2.2.0, render one `lima.yaml` per lab, lifecycle, disk snapshots with `qemu-img`, serial consoles, QMP reset |
| `containers.py` | the same machine interface for `runtime: container` labs, over Docker or Podman: build the base image from its Dockerfile, `exec` for every command, `commit` as the clean snapshot |
| `images/` | the golden image cache: pull by digest, verify, import |
| `labs/` | manifests, the linter, the local and OCI lab stores |
| `quiz/` | question banks, the sandboxed verifier, a theory run |
| `play/` | the PTY recorder, the in-guest git watcher, streaming upload |
| `tutor/` | the tutor and the review of a finished attempt, on this machine's model (`models.py`: Claude Code, then a key, then Ollama); the guard every reply passes; the commands an attempt left (`commands.py`) |
| `auth.py` | signing in with GitHub's device flow through the API, and the token file when the machine is remembered |
| `attempts.py` | reporting a graded attempt on an unrated lab |
| `rated.py`, `quiz/remote.py` | the client half of a rated lab and a rated theory run: the cached catalogue, and every call of one attempt ([Rated labs](#rated-labs-keeping-the-answer-off-the-learners-machine)) |
| `doctor.py` | can this host run labs, and what to do if not |
| `cli.py` | `norboten` → the TUI; hidden `dev` and `image` commands for authors and CI |
| `models.py` | the Pydantic schemas shared with the API — the machine-readable form of the specs |

## The runner

`runner/norboten_runner` is copied into the guest for a run and deleted after it. It imports only
the standard library, because nothing may be installed in a lab VM. It applies faults, runs checks
with a per-check timeout, collects the read-only facts the tutor reasons from, and persists
`ctx.state` so a check can know what a fault generated. For a rated lab it runs collectors instead
of checks and signs what they saw (`collect_runner.py`, `signing.py`); the judges that read those
facts (`judge.py`) are standard library too, but they run on the server and in the gate, never in a
guest. All of it runs as `norboten-grader`, a
separate account with its own key and sudo, created before the clean snapshot — so a lab can take
away the learner's sudo without taking away the grader's.

## A lab session

1. **Pull** the golden image (verified against the digest pinned in `images/registry.yaml`) and the lab.
2. **Boot** once; cloud-init creates the learner's account; the grading account is installed.
3. **Snapshot** the disks with `qemu-img`, the VM stopped. This is the clean state. Memory snapshots
   are not used: on Apple Silicon with QEMU's HVF they corrupt the next reset.
4. **Break**: the runner applies the faults; a `boot_after_break` lab then reboots into the broken
   state the learner meets.
5. **Work**: a shell (`o`), the serial console (`k`), the bootloader (`b`), hints (`h`), the tutor
   (`t`), live checks (`w`).
6. **Check** (`c`): checks run, the machine reboots, they run again. A check passes only if it passed
   both times; a quick check without the reboot (`x`) can never pass a lab.
7. **Reset** (`r`): roll the disks back, cold-boot, re-apply the faults — about ten seconds.

### Container labs, and the claude and MCP tracks

A lab whose subject has no boot in it can be `runtime: container` (`containers.py`): the base image is
built locally from a Dockerfile, the clean snapshot is a `docker commit`, every command arrives through
`exec`, and a reset recreates the container in under a second. Fourteen labs use it — two Linux labs on
`ubuntu-26.04-container`, and the six labs each of the **claude** and **MCP** tracks on
`ubuntu-26.04-claude`. The MCP track's servers — stdio and Streamable HTTP, one behind nginx, one
checking tokens from a small local identity provider — are standard-library Python in each lab's
`files/`, so every check reads a real server through a real Claude Code.

The claude track grades a real Claude Code (2.1.270, the release binary pinned by its sha256) without an
account, a token or the network. `claude` on that image is a small launcher that points Claude Code at
`fake_anthropic.py` on 127.0.0.1 — the same scripted Messages API the CI rehearsal uses, kept identical by
a test — which answers each model turn from a script. Claude Code then does what it really does with those
answers: loads settings, `CLAUDE.md`, hooks, subagents and MCP servers, applies permission rules, runs
tools. A check scripts the model to attempt something (delete a directory, read a token, call an MCP tool,
push, never stop) and grades the result: files left behind, the tool results Claude Code sent back, the
tools and model each request asked for. `claude_lab.py` gives checks that as one call. Behaviours found
this way — an untrusted checkout ignoring project allow rules, a `Read` deny that `grep -r` walks past, a
subagent with misspelled tools that "launches" and never runs — are recorded in
`docs/research/claude-code.md`.

## The server

`deploy/compose.yaml`. Only Caddy publishes ports; everything else talks on the compose network.

| Service | Job |
|---|---|
| **caddy** | TLS from Let's Encrypt, renewed by itself; serves the static site; proxies `api.` and `status.`; passes server-sent events unbuffered; hides `/metrics` |
| **api** | FastAPI under uvicorn, two workers. Stateless: everything it keeps is in PostgreSQL or Redis, so a restart or a second worker loses nothing |
| **postgres** | the one database (`norboten`). Schema in [Data model](../data-model/index.html) |
| **redis** | pub/sub for live frames, rate limits, a 30 s leaderboard cache. No persistence |
| **ollama** | a small local model (`qwen2.5:0.5b` by default, pulled by the one-shot `ollama-pull`) that answers the consultant; see [Local models](#local-models-ollama) |
| **prometheus**, exporters, **grafana** | request rates and latencies by route, host and database metrics, and dashboards behind a login |
| **analytics** (job) | nightly: redraws the Analytics page from the database |

`deploy.sh` rolls the API to a tag and back if `/readyz` does not answer; `backup.sh` dumps the
database nightly and proves the dump restores. See [Deploying the server](../deploy/index.html).

## The API

`api/src/norboten_api`. Every endpoint is in the generated [API reference](../api-reference/index.html).

| Module | Responsibility |
|---|---|
| `main.py` | the app, its lifespan (stores, bus, the hourly purge), CORS, `/healthz`, `/readyz` |
| `db.py` | the schema and the shared connection pool |
| `store.py`, `account_store.py`, `credentials.py`, `play_store.py`, `rated_store.py` | one protocol each, a memory and a PostgreSQL implementation, tested against both |
| `routers/rated.py`, `routers/rated_quiz.py` | rated attempts and rated theory runs: issued, judged and rated here |
| `live.py` | the Redis bus (and an in-process one), rate limits |
| `auth.py`, `routers/auth.py`, `github.py`, `pending.py` | signing in with GitHub (device and web flows), hashed tokens, the flows in progress |
| `discord.py`, `routers/discord.py`, `digest.py` | linking Discord, and the weekly digest as a direct message from the bot |
| `rating.py`, `accounts.py` | Glicko-2 per topic; what an attempt is worth |
| `mcp_server.py`, `routers/oauth.py` | the MCP server at `/mcp` and `/mcp/account`, the gate in front of it, and the OAuth 2.1 authorization server for its personal tools |
| `retrieval.py`, `agents/` | the consultant's BM25 index and the consultant, on Ollama only (the providers live in `norboten.questions.providers`, the guard in `norboten.tutor.guards`) |
| `analytics/` | the Analytics page: pandas, scikit-learn, networkx, matplotlib |
| `metrics.py` | Prometheus metrics by route template |
| `reference.py` | writes `docs/api-reference.md` from the app's own OpenAPI document |

## Identity

An account is a GitHub account, and nothing else: there is no password, no email address and no
registration. GitHub is asked one question — who is this — and the answer that is kept is its
numeric user id, which never changes, with the login beside it, refreshed at every sign-in because a
login can be renamed. The first sign-in creates the account. No scope is requested, so the GitHub
token could read nothing private while it existed, and it exists for one `GET /user`: the API revokes
it straight away (`DELETE /applications/{client_id}/token`) and stores no GitHub token anywhere.

**A terminal** uses GitHub's device flow, proxied by the API. `POST /auth/github/device` has GitHub
issue a device code, which stays in PostgreSQL (`pending_sign_ins`); the terminal gets only the user
code to type and `github.com/login/device`, which works from any device, so a headless machine signs
in the same way. The terminal then polls `POST /auth/github/poll`, and each poll is one call to
GitHub: 428 while it waits, 429 with a longer interval when GitHub says slow down, 403 denied, 410
expired. Proxying is the point. If the terminal talked to GitHub itself, a GitHub token would reach
the learner's machine, and the API would have to accept a token and trust that it had been issued to
this app — a token from any other GitHub app would sign its owner in.

**The site** uses the web flow. The page makes a random `state`, keeps it in `sessionStorage`, and
goes to `GET /auth/github/go`; the API keeps that state with the flow and sends the browser to
GitHub with a state of its own. GitHub returns the browser to `GET /auth/github/callback`, where the
code is exchanged with the client secret, and the API sends the browser back to the page with
`#once=…&state=…` in the fragment — never a token in a URL, and a fragment reaches no server. The page
checks the state against the one it made (login CSRF) and exchanges the one-time code, which lives
sixty seconds and works once, for a token. An MCP client's approval page (`/authorize/`) signs in with
the same button and returns to its pending request.

"Remember this browser" (or machine) is the token's life and nothing more: ninety days, or twelve
hours. The site keeps a remembered token in `localStorage` and the other in `sessionStorage`; the
TUI writes `~/.norboten/credentials.json` at 0600 only when remembered, and otherwise holds the
token in the process. A terminal's token is `cli` and labelled with the machine's name. Tokens are
random, the server stores only their SHA-256, and revoking one deletes a row. A client never sends a
user id: the id comes from the token.

**What each service sees.** GitHub sees that someone signed in to Norboten, when, and nothing Norboten
holds. Norboten keeps the GitHub id and login; the public profile links to the login. **Discord** is
optional and only for the weekly digest: the account page links a Discord user through Discord's
OAuth2 (`identify`, and `guilds.join` only when "join the Norboten server" is ticked, off by default),
keeps the Discord user id and drops Discord's token. The digest is then a direct message from the
bot, over REST with no gateway connection; a DM needs the bot and the person to share a server, and
Discord's `50007` (it will not take the message) is recorded and explained on the account page.

The cost is a hard dependency on GitHub: a server without `NORBOTEN_GITHUB_CLIENT_ID` and its secret
answers 503 on every sign-in endpoint, and nobody without a GitHub account can sign in. Labs, theory
and journals never need an account. The OAuth App has one callback URL, so a laptop stack needs its
own app; without one, the laptop's API accepts the debug identity instead.

**The nick and the country.** A profile is made once, with a nick that is then fixed — a second
`POST /me` with another nick is 409 — and a country that can change. Both forms open on a guess: the
nick from the GitHub login, the country from `GET /geo/country`, which looks the caller's address up
in an offline table on the server (`geo.py`: **DB-IP Lite IP-to-Country**, by
[DB-IP](https://db-ip.com), CC BY 4.0, compiled into the image monthly). No third party sees the
address, and the guess is never stored: only a country the learner submits is.

## Ratings

Glicko-2, one rating per topic of the nineteen in `cli/src/norboten/topics.py`, each with its own
deviation so a new profile admits what it does not know. A rated attempt is one game per topic the
lab declares, against a virtual opponent whose rating is the lab's difficulty (1100 to 1900); a
rated theory run is one game at the mean difficulty of what was served. The server reads
difficulty, topics and time limit from the manifest, never from the request — a client that could
name its opponent would name an easy one. Only rated labs and rated banks, graded on the server,
play games at all; the next chapter is why.

## Rated labs: keeping the answer off the learner's machine

**The problem.** A board is worth reading only if the people on it fixed the machine. Everything
else in Norboten runs on the learner's machine and is public — the faults, the checks, the reference
solution — which is right for learning and useless for a rating: a pass reported by a client that
can read the answer proves nothing, and a check that runs locally can be read, edited or skipped.

**What was rejected, and why.**

- *Encrypt the answers in the repository, decrypt them locally.* Whatever decrypts on the learner's
  machine holds the key, so this is obfuscation with extra steps, and the project does not print
  claims it cannot stand behind.
- *Close everything.* Grading every lab on a server would break what the product is built on: labs
  run offline, and the TUI keeps working when the server is down. For most readers the solution *is*
  the lesson. So the catalogue splits instead: **unrated** labs and banks stay public and offline,
  **rated** ones are the only thing that moves a rating.
- *A second project.* The rated half is a private repository attached as the submodule `rated/`:
  one gitlink and one `.gitmodules` entry in the public tree. The seam is visible on purpose — the
  public half is complete on its own, and anyone can see exactly where the closed material begins.
- *Answers inside the API image.* A container image is a tar of files and its layers are immutable;
  one image built with `rated/` in it and pushed once would publish the answers for good. So the
  image never contains them: the private repository is checked out on the server beside the stack
  (`/opt/norboten/rated`, with a read-only deploy key — the Ansible step waits on that key) and
  Compose mounts it into the API read-only (`NORBOTEN_RATED_DIR`). Tests assert the
  Dockerfile, the Docker context and the wheel carry nothing from `rated/`
  (`tests/test_rated_never_ships.py`), and rotating the answers is a `git pull`, not a rebuild.

**What the server grades: machine state, not a verdict.** A rated check is split in two files with
the same name (docs/lab-spec.md §13). `collect/NN_name.py` runs in the guest and returns what it
saw — command output, exit codes, file contents — never a pass or a fail. `check/NN_name.py` is the
judge, a pure function of those facts, and it never leaves the server. Reading every collector tells
you what is looked at; it does not tell you what is accepted. To pass, the machine has to be in a
state the judge accepts, which is to say fixed.

```
TUI (learner)                        API (holds judges, solutions)                guest VM
 s ── POST /rated/attempts ────────▶ attempt id · nonce · key · clock
   ◀───────────────────────────────── break bundle (break/ files/ lab.yaml)
   ── inject from memory, run, delete ─────────────────────────────────────────▶ faults applied
      … the learner works; no checks, hints, tutor or solution on this machine …
 c ── GET …/collect ───────────────▶ collect bundle (collect/ files/ lab.yaml)
   ── inject, run collectors; key on stdin ─────────────────────────────────────▶ record + HMAC
   ── POST …/facts (pre_reboot) ────▶ verify signature, nonce, phase; store
   ── reboot; collect again ────────────────────────────────────────────────────▶ record + HMAC
   ── POST …/facts (post_reboot) ───▶ new boot_id? later? → judge both passes
   ◀───────────────────────────────── pass/fail per check · score · rating change
```

**What each piece defends against.**

| Mechanism | Defends against |
|---|---|
| judges and solutions only on the server | reading the criterion or the answer, from the repository, the wheel, the image or `~/.norboten` |
| collectors that return observations | a collector that gives the answer away — the linter refuses one that decides |
| a per-attempt key, HMAC over canonical JSON | a record replayed from another attempt, or posted by someone who is not running this one |
| a nonce and one record per phase | the same record sent twice, a second run of the same attempt |
| a different `boot_id` and a later `collected_at` after the reboot | a fix that does not survive a reboot, reported as if it did |
| the clock from issue to the first record, kept by the server | a client that claims it finished in time |
| starting again, giving up and expiry all close the attempt as a loss | looking at the faults for free and walking away |
| no live checks, quick check, hints, tutor or reset in a rated attempt | a grading oracle queried until it says yes |
| rated theory served one question at a time, on the server's clock | reading ahead, and answers looked up after the time ran out |

**What it does not defend against, deliberately.** The key and the collectors reach the learner's
own VM, because the record is collected and signed there, and a determined learner can read both out
of a machine they control. The signature proves a record belongs to this attempt; it cannot prove
the person holding the key did not write it by hand. Forging a passing record, though, needs what the
judge accepts, and that is exactly the part that is never delivered — so the cheapest way to a pass
remains fixing the machine. Moving grading entirely off the learner's machine would close even this,
at the price of the offline product, and a rating is not worth that.

**How it is proven.** The gate proves a rated lab the way it proves any other, with the collectors
in the guest and the judges on the host (`norboten dev validate`); the API tests cover forged,
foreign, replayed and out-of-order records against the real app; a Docker test runs one rated
attempt end to end — the in-process API, a real container, the TUI's engine — and then searches the
learner's `~/.norboten` for any trace of the criteria.

## Recording and streaming

The lab shell runs in a pseudo-terminal and bytes are copied both ways, so the recording is what
crossed the terminal — asciicast v2, which `asciinema play` and the site's player both read. Commands
are lifted from the typed input; diffs come from keeping the guest's watched directories under git
for the session, inside the VM. `P` streams: the recorder POSTs a batch every couple of seconds, the
API stores it and publishes it on Redis, and every viewer's server-sent-events stream forwards it —
after first replaying what was stored, so a late viewer misses nothing.

## The consultant and the tutor

Both are agents that may not hand over a lab's fix. The **tutor** runs in the TUI, on the
learner's machine, and answers from the VM's evidence; its request model has no field for the
reference solution, and a guard compares its reply against the solution and the hint level before
it is shown. The model is the first this machine has — Claude Code on the learner's subscription
(no tools, an empty working directory), then an exported API key, then a local Ollama — or the one
pinned on System (`m`); with none, `t` shows the lab's own hint ladder. After a pass or a surrender,
`m` on the lab asks the same model for a **review** of the attempt, the one agent that reads the
solution: the commands come from the attempt's recordings (exact and timed) and the VM's shell
history (untimed), each labelled with its source. The **consultant** answers
questions about Norboten from Norboten: BM25 over the docs, the journals (without their
walkthroughs), the briefings and the question explanations — no solution file and no level 3–4 hint
is indexed — then a model (Ollama first), then the same guard. BM25, not embeddings, because the
useful terms in this corpus are exact ones (`lvextend`, `fstab`), and lexical ranking finds them
better, costs nothing, needs no vector database and can be explained. When the API is down, the
site's widget ranks the same passages in the browser.

## The MCP server

The API is also an MCP server, at `/mcp` ([The MCP server](../mcp/index.html)): the docs search,
the catalogue, a lab's briefing and first two hints, journals without walkthroughs, a quiz that asks
the user through the protocol's multi round-trip requests, the boards — and, with a token, the
account's own progress. It runs stateless on the 2026-07-28 revision, in the same process, so it
needs nothing new from the server. The API is its OAuth 2.1 authorization server: PKCE, client ID
metadata documents instead of registration, `iss` on the redirect, and tokens of their own kind
that only the MCP server accepts. A gate in front reads the protocol's routing headers to
rate-limit, audit and ask for a token before the request is parsed; every text result passes the
tutor's guard against every lab's reference solution.

## Local models: Ollama

Ollama runs in three places, for different reasons.

**On the learner's machine** it is the last choice for the tutor and the review, after Claude Code
and an API key: `norboten` looks for one at `OLLAMA_HOST` or on its default port and uses what it
has pulled (`qwen2.5:1.5b` first). Nothing is installed for this; it is used if it is there.

**On the server** it serves the consultant. `NORBOTEN_CONSULTANT_MODELS` lists candidates in order and
the consultant uses the first one the server can serve — Ollama models only, `ollama/qwen2.5:0.5b` by
default — so a question about the docs costs nothing per
answer and never leaves the machine. The model answers from the passages
BM25 retrieved and the guard filters what it says; a half-billion-parameter model is poor at knowing
things and adequate at restating retrieved text, which is exactly the job. It is reached only on the
compose network (`expose`, never `ports`), because Ollama has no authentication. Measured on the laptop
stack (2026-09-14): the idle container holds 35 MiB, and 628 MB once `qwen2.5:0.5b` is loaded; the model
file is 398 MB. On the planned 4 GB server that leaves room for the API, PostgreSQL, Redis and monitoring.

**In the automation track** it is the subject. `ubuntu-26.04-automation` bakes in Ollama 0.34.0 with
`qwen2.5:0.5b` and the `all-minilm` embedding model (424 MB of models; the image is 913 MiB), so the labs
work offline. `ai-01` runs it as a service account behind nginx for streamed answers; `ollama-01` takes it
off the network and allows one browser origin; `ollama-02` builds a custom model whose context window cuts
its system prompt (a 1,388-token prompt evaluated as 130 tokens at `num_ctx` 256); `ollama-03` sizes
context × parallelism to memory (734 MiB peak at 4,096 × 2 against a 3 GB cache at 32,768 × 8) and caps
the service with `MemoryMax=`. The Ollama theory bank and topic journal cover the rest.

## Relations and analytics

How labs, topics, question banks and journals relate is computed, not curated: TF-IDF over their
text, cosine similarity, and a graph of declared topics plus the strongest textual neighbours
(scikit-learn, networkx). Deterministic and explainable, and a vector store would add nothing yet;
pgvector in the same PostgreSQL remains the next step if semantic similarity is ever needed. The
Analytics page is built from the attempts the same way — see [Pipelines](../pipelines/index.html).

## Distribution

Labs are OCI artifacts in GHCR (`images/Dockerfile.lab`, signed with cosign). Golden images are
blobs in GHCR pinned by digest in `images/registry.yaml`. The API is a multi-arch image in GHCR
tagged by commit. All three are content-addressed: a client or a server gets exactly what CI
published, or nothing.

## Infrastructure

One netcup VPS, ordered by hand; `ansible/` bootstraps it, hardens it (ufw, fail2ban, keys-only
SSH) and installs the compose project. `.github/workflows/deploy.yml` tests,
builds, and rolls out on every push to main. See [CI/CD](../ci-cd/index.html). There is no
Kubernetes and no hosted lab mode: running learners' VMs on the server would need `/dev/kvm`,
which a cloud VPS does not offer.

## Automation

The chores a maintainer would otherwise do by hand are jobs in `automation/jobs/`, run by GitHub
Actions — or, where they need the database, by a systemd timer on the server. A model is used only
where reading prose is the job: four jobs run **Claude Code** headless (`claude -p`); the rest are
plain code, because a failed gate job, a new `lab.yaml` or a learner's attempts are facts already.

| Job | Trigger | Model | What it does |
|---|---|---|---|
| triage (`triage.yml`) | an issue is opened | Claude Code, Haiku, **no tools**, one turn, a JSON-schema answer | one of `bug`, `lab-request`, `question`, `broken-lab`, applied by the script; an open issue with the same title gets a pointer |
| stuck points (`stuck-points.yml`) | Mondays 08:00 | Claude Code, Haiku, no tools | the API's ranking of the most-failed checks summarised on Discord; the worst becomes a `hints` issue, from the data, once |
| lab author (`lab-author.yml`) | an issue labelled `lab-request` | Claude Code as the project subagent `.claude/agents/lab-author.md`, Sonnet, Read/Glob/Grep/Write, writes only under `labs/_drafts/`, `dontAsk`, 20 turns, $1 | one draft file; the script checks nothing else changed, then branches, pushes and opens a **draft** pull request |
| release notes (`release.yml`) | a `v*` tag | Claude Code, Haiku, no tools | a grouped summary of the commits since the last tag, with the full commit list appended by the script |
| lab health (`lab-validate.yml`, `report`) | nightly 02:00 | none | the gate on every lab × image; an issue per failed `gate (<lab>, <image>)` job unless one is open |
| announcements (`release.yml`, `announce`) | after the release | none | Discord gets the release; Telegram one message per `lab.yaml` new since the last tag |
| live sessions (`api/…/announce.py`) | a real session starts | none | Telegram: "<nick> is working on <lab> right now", sent by the API after it answers |
| learner digest (`api/…/digest.py`) | Sundays 18:00, `norboten-digest.timer` | none | to each learner who linked Discord, opted in and did something that week: their attempts, rating and least certain topic, from a template, as a Discord direct message |

**Guard rails, enforced by flags rather than by the prompt.** Every Claude job authenticates with
`CLAUDE_CODE_OAUTH_TOKEN` (a subscription token from `claude setup-token`) — which is also why none
passes `--bare`: bare mode never reads that token. The jobs that read what a stranger wrote (issue
titles and bodies, commit messages) run in an empty directory with `--tools ""`, so no project
hooks, MCP servers or CLAUDE.md load and the model has nothing to act with; triage's answer is
further held to an enum. The lab author gets a checkout, but `--tools` removes the shell,
`--allowedTools "Edit(/labs/_drafts/**)"` with `--permission-mode dontAsk` denies every write
elsewhere, and the script refuses to open a pull request unless exactly one draft appeared. No model
holds a GitHub token: labels, issues, branches and pull requests are made by the script. Each job has
`timeout-minutes` and a concurrency group, and Claude Code is pinned
(`.github/actions/claude-code`, the version the rehearsal ran).

**Rehearsal.** `make jobs-rehearsal` runs every job as its workflow does, with the real `claude`
binary, against stand-ins: `automation/stand_ins/fake_anthropic.py` answers the Messages API from a
script (a label, a summary, a `Write` tool call), and `sink.py` plays GitHub, Discord, Telegram and
the API. The scripted model also tries what it must not — writing `README.md`, running Bash, writing
a second file — and the rehearsal checks each was refused. No token is spent; five jobs in about
seven seconds. `tests/test_automation.py` runs the same scenarios where Claude Code is installed and
checks the workflows statically (caps, token, pin, no `--bare`). The digest is rehearsed with
`--dry-run`, which prints each message instead of sending it, and against the Discord stub in
`api/tests/oauth_stubs.py`.

What each model call may see and do, what it costs and how that is kept down — for these jobs,
the product's own agents and the content skills — is in
[How Norboten uses Claude](../claude-code-in-norboten/index.html).

The API has no private endpoints for any of this: the digest reads the database from inside the
server, the lab author works in a checkout, and a release's catalogue is the image that release
deployed.
