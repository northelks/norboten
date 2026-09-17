# Data model

Norboten keeps data in four places, and each place holds only what belongs there:

| Where | What | Survives |
|---|---|---|
| **PostgreSQL** (server) | accounts, credentials, tokens, attempts, ratings, play sessions and frames, verified questions, events | everything; backed up nightly with a restore check |
| **Redis** (server) | live frames in flight, rate-limit counters, a short cache | nothing needs to — losing it costs a reconnect and a cold cache |
| **The learner's machine** (`~/.norboten`) | lab VMs, images, sessions, grade reports, recordings, theory progress, the sign-in token | until the learner deletes it |
| **The repository** | labs, question banks, journals, docs, recordings shipped with the site | git |

The schema is `SCHEMA` in `api/src/norboten_api/db.py`: plain SQL, applied on every start, every
statement idempotent (`CREATE … IF NOT EXISTS`), under a PostgreSQL advisory lock so two API
workers starting together do not race. A column that holds data is never renamed or dropped, so an
older API image runs against a newer database — which is what makes a rollback safe. The one
exception came before any account existed: the password and email columns of the earlier sign-ins,
and the `login_codes` table, went on 2026-09-16. Times are
`timestamptz` in the database and Unix seconds in Python.

## PostgreSQL

```
credentials 1──* tokens            users 1──* attempts
     │                               │
     └──────── user_id ──────────────┤ 1──* ratings (one per topic)
                                     │
                                     ├─ nick shown on play_sessions 1──* play_batches
                                     │
                                     ├──* rated_attempts ──────┐
                                     └──* rated_quiz_sessions ─┴─ closed ─▶ one attempts row

events
```

`user_id` is a random 32-character hex id created by a GitHub account's first sign-in. It is the key
everywhere and never changes; the nick is a label on top of it and is chosen once.

### `credentials`

Who an account is: a GitHub account, and nothing else. Created by the first sign-in with that GitHub
account (`POST /auth/github/poll` from a terminal, `POST /auth/github/exchange` on the site). There is
no password and no email column (both dropped 2026-09-16), and no GitHub token is ever stored.

| Column | Type | Notes |
|---|---|---|
| `user_id` | text | primary key |
| `github_id` | bigint | GitHub's numeric user id; unique (`credentials_github_idx`); never changes |
| `github_login` | text | the login as GitHub last reported it, refreshed at every sign-in; the public profile links to it |
| `created_at` | timestamptz | |
| `discord_id` | text | the linked Discord user, or null; unique (`credentials_discord_idx`) |
| `digest` | boolean | the weekly learner digest; `false` until the learner turns it on, and only possible with Discord linked (`PUT /auth/preferences`); read by the digest job (`norboten_api/digest.py`) on the server |
| `discord_error` | text | why the last digest could not be delivered (Discord's `50007`), shown on the account page; cleared on a new link |

### `tokens`

Opaque bearer tokens. The client keeps the token; the server keeps only its SHA-256.

| Column | Type | Notes |
|---|---|---|
| `token_hash` | text | primary key; hex SHA-256 of the token |
| `user_id` | text | → `credentials.user_id`, `ON DELETE CASCADE` |
| `kind` | text | `web` (the site) or `cli` (a terminal); either 90 days when remembered, 12 hours when not. `mcp` and `mcp-refresh` are an MCP client's |
| `label` | text | for `cli`, the machine that signed in, e.g. `tower.local (Darwin)` |
| `created_at`, `expires_at`, `last_used_at` | timestamptz | `last_used_at` is updated on each authenticated request |

Index: `tokens_user_idx (user_id)` — "where am I signed in" and revoking all.

### `pending_sign_ins`

A sign-in or a Discord link that has started and not finished (`norboten_api/pending.py`), in the
database rather than Redis so that a restart strands nobody mid-sign-in. Every row is used once — it
is deleted as it is read — and expires.

| Column | Type | Notes |
|---|---|---|
| `id` | text | primary key; random; the terminal's poll handle, GitHub's `state`, the one-time code |
| `kind` | text | `device` (a terminal), `web` (the site), `once` (the one-time code the site exchanges), `discord-link` |
| `data` | jsonb | `device`: GitHub's device code (never sent to the terminal), the polling interval, the terminal's label, `remember`; `web`: the page's own state, `remember`, where to return; `once`: the GitHub id and login, `remember`; `discord-link`: the account and whether to join the server |
| `expires_at` | timestamptz | 15 minutes; a `once` code 60 seconds |

Index: `pending_sign_ins_expiry_idx (expires_at)`.

### `users`

The public profile. Created by `POST /me` once a signed-in account chooses a nick.

| Column | Type | Notes |
|---|---|---|
| `user_id` | text | primary key |
| `nick` | text | unique; `^[a-z0-9][a-z0-9_-]{1,18}[a-z0-9]$` |
| `country` | char(2) | ISO 3166-1 alpha-2; drawn as a flag |
| `created_at` | timestamptz | |
| `seed` | boolean | a generated sample account, labelled wherever it is shown |

### `attempts`

One graded lab attempt or one finished theory run. Written by `POST /attempts`, and by a rated
attempt when it closes (`rated_attempts`); never updated.

| Column | Type | Notes |
|---|---|---|
| `id` | bigserial | primary key |
| `user_id` | text | |
| `kind` | text | `lab` or `quiz` |
| `lab_id` | text | the lab id, or the quiz topic for `quiz` |
| `started_at` | timestamptz | when the faults were applied (the clock's start) |
| `duration_seconds` | integer | |
| `score_percent` | smallint | 0–100 |
| `passed` | boolean | |
| `rated` | boolean | practice attempts are recorded and never rated |
| `within_limit` | boolean | false when a rated attempt ran over its clock (then it is a loss) |
| `difficulty` | smallint | **from the lab manifest**, never from the client |
| `topics` | text[] | from the manifest too |
| `rating_delta` | jsonb | `{topic: change}` this attempt caused; empty for practice |

Indexes: `(user_id, started_at desc)` for a profile, `(lab_id, started_at desc)` for analytics.

### `ratings`

The current Glicko-2 rating per learner per topic. Upserted after each rated attempt.

| Column | Type | Notes |
|---|---|---|
| `user_id`, `topic` | text | composite primary key; `topic` is one of the nineteen slugs in `cli/src/norboten/topics.py` |
| `r`, `rd`, `sigma` | double precision | rating, rating deviation, volatility (start 1500 / 350 / 0.06) |
| `games` | integer | |
| `updated_at` | timestamptz | |

Index: `ratings_topic_idx (topic)` for a topic board. The overall rating is not stored: it is the
inverse-variance-weighted mean of the topic ratings, computed when read.

### `rated_attempts`

A rated lab attempt between being issued and being judged (docs/lab-spec.md §13). Created by
`POST /rated/attempts`; closed by the last fact record, by `…/abandon`, by starting another one, or
by the hourly sweep once it expires. Closing writes one `attempts` row with `rated = true`.

| Column | Type | Notes |
|---|---|---|
| `attempt_id` | text | primary key; 24 random url-safe characters |
| `user_id` | text | |
| `open` | boolean | false once closed |
| `expires_at` | timestamptz | issued + three times the lab's clock, at least an hour |
| `data` | jsonb | the rest, read whole: lab, image, nonce, the attempt key, the received records, the outcome, each check's verdict, the rating change |
| `created_at` | timestamptz | |

Indexes: `(user_id) WHERE open` — one open attempt per learner is looked up on every start — and
`(expires_at) WHERE open` for the sweep. The key is stored because the server verifies with it; it
signs this attempt's records and nothing else.

### `rated_quiz_sessions`

A rated theory run (docs/quiz-spec.md §6), in the same five columns as `rated_attempts`: the run's
id as `attempt_id`, its owner, `open`, `expires_at` (an hour after it started) and `data` — the
topic, the questions it will ask in order, each served question with when it was served and what
came back, the outcome and the rating change. Closing it writes one `attempts` row with
`kind = 'quiz'` and `rated = true`. Indexes as for `rated_attempts`.

### `play_sessions`

A recorded or live terminal session. Created by `POST /play/sessions`.

| Column | Type | Notes |
|---|---|---|
| `session_id` | text | primary key; 16 random url-safe characters |
| `user_id`, `nick`, `country` | text | the nick and country as they were when it started |
| `lab_id`, `lab_title` | text | |
| `width`, `height` | smallint | the terminal, for the player |
| `started_at`, `last_frame_at`, `ended_at` | timestamptz | live = not ended and a frame in the last 25 s |
| `frames`, `commands` | integer | running counts |
| `passed` | boolean | set when it ends, if known |
| `seed` | boolean | |
| `expires_at` | timestamptz | `started_at` + 7 days; `purge()` deletes past it hourly |

Index: `play_sessions_recent_idx (last_frame_at desc)`.

### `play_batches`

What the recorder flushed every couple of seconds. Deleted with its session.

| Column | Type | Notes |
|---|---|---|
| `session_id`, `seq` | text, integer | composite primary key; a retried batch is ignored (`ON CONFLICT DO NOTHING`) |
| `at` | double precision | seconds into the recording |
| `events` | jsonb | asciicast v2 events `[time, "o"|"i", data]` |
| `commands` | jsonb | `[{at, text}]` |
| `changes` | jsonb | `[{path, diff, truncated, command}]` — diffs taken inside the guest |

### `events`

Append-only operational events, as JSON: `chat` (answered, blocked), `progress`
(anonymous, opt-in), `stuck_point` (opt-in telemetry). No question is stored: the banks are files in
the repository (a `questions` table from before 2026-09-15 is dropped on start).

| Column | Type |
|---|---|
| `id` | bigserial primary key |
| `kind` | text |
| `payload` | jsonb |
| `created_at` | timestamptz |

Index: `events_kind_idx (kind, created_at desc)`.

## Redis

`api/src/norboten_api/live.py`. No persistence (`--save "" --appendonly no`), 256 MB with LRU
eviction.

| Key or channel | Type | TTL | Written by | Read by |
|---|---|---|---|---|
| `play:<session_id>` | pub/sub channel | — | `POST …/frames` and `…/end` publish `{type: batch|end}` | every open `GET …/stream` |
| `rate:<bucket>:<who>:<window>` | counter | the window + 5 s | every rate-limited endpoint | the same |
| `board:<topic|overall>:<limit>` | string (JSON) | 30 s | `GET /leaderboard` | the same |
| `readyz` | string | 10 s | `GET /readyz` | the same |

Rate limits: chat 20 a minute per client (`NORBOTEN_CHAT_PER_MINUTE`); starting a sign-in and
exchanging a one-time code 10 a minute per client each (`NORBOTEN_SIGN_INS_PER_MINUTE`); starting a
Discord link 10 a minute. The
client is the first `X-Forwarded-For` address Caddy sets.

## The learner's machine

`~/.norboten`, or `NORBOTEN_HOME`.

| Path | What |
|---|---|
| `lima/<version>/` | the pinned Lima |
| `vms/` | the lab VMs (`LIMA_HOME`): disks, snapshots, serial logs and sockets |
| `images/<id>/<arch>/` | golden base images, with the metadata they were verified against |
| `labs/<id>/<version>/` | labs pulled from the registry |
| `sessions/<lab>.json` | a lab session: state, image, attempts, hint levels, clock |
| `sessions/<lab>.last.json` | the last grade report, with every check's result per pass |
| `plays/<lab>-<stamp>.cast`, `.log.json` | recordings: asciicast v2, and the commands and diffs |
| `journals/<id>.pdf` | exported journals |
| `progress.json` | theory results per topic |
| `credentials.json` | mode 0600: the `cli` token, its expiry, which API issued it |

Nothing here is sent anywhere unless the learner signs in (graded attempts, rated theory runs) or
streams a session.
