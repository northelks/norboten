# Self-hosting and configuration

Three ways to run the server side yourself, from least to most:

| | Command | What you get |
|---|---|---|
| **The API alone** | `uv run python -m uvicorn norboten_api.main:app --reload` | the API on :8000 with everything in memory — fine for developing the TUI or the API |
| **The whole stack on a laptop** | `make stack-up` | the production compose project with a local override: site :8080, API :8000, Grafana :3000, sample data loaded |
| **A real server** | [Deploying the server](../deploy/index.html) | the same compose project on an Ubuntu machine with TLS, backups and deploy-on-push |

Then point the TUI at it:

```sh
NORBOTEN_API=http://localhost:8000 uv run norboten
```

The boards, live sessions, signing in and the consultant then use that server. Without
`NORBOTEN_API`, the TUI uses `https://api.norboten.org`; without any reachable server, the labs,
theory, journals, local recordings, the tutor and the review all still work — those two run on the
learner's machine — and the Ratings and You sections say they are offline.

## The API's settings

Every setting is an environment variable with the `NORBOTEN_` prefix
(`api/src/norboten_api/settings.py`).

| Variable | Default | Meaning |
|---|---|---|
| `NORBOTEN_DATABASE_URL` | `memory://` | `postgresql://user:password@host:5432/db`; memory keeps everything in the process |
| `NORBOTEN_REDIS_URL` | *(empty)* | `redis://host:6379/0`; empty keeps live frames and rate limits in the process — only correct with one worker |
| `NORBOTEN_REQUIRE_AUTH` | `false` | `true` on a server: every signed endpoint needs a token; `false` also accepts `X-Debug-User` |
| `NORBOTEN_SITE_URL` | `https://norboten.org` | the site, for the links the API hands out (the account page, the MCP sign-in page) |
| `NORBOTEN_API_URL` | `https://api.norboten.org` | the API's own public address: the OAuth issuer, and `<api>/mcp` is the MCP server's resource identifier |
| `NORBOTEN_MCP_PER_MINUTE` | `120` | MCP requests per client per minute |
| `NORBOTEN_MCP_STATE_KEY` | *(empty)* | seals a `quiz_me` question between its two requests; every worker needs the same one, and empty (a key per process) is right with one worker only |
| `NORBOTEN_TELEGRAM_BOT_TOKEN`, `NORBOTEN_TELEGRAM_CHAT` | *(empty)* | a real session going live is announced to this chat (`announce.py`); empty sends nothing |
| `NORBOTEN_GITHUB_CLIENT_ID`, `NORBOTEN_GITHUB_CLIENT_SECRET` | *(empty)* | **required to sign anyone in**: the GitHub OAuth App (callback `<api>/auth/github/callback`, Enable Device Flow ticked). Empty and every sign-in endpoint answers 503 "sign-in is not configured on this server" |
| `NORBOTEN_GITHUB_URL`, `NORBOTEN_GITHUB_API_URL` | `https://github.com`, `https://api.github.com` | GitHub's two hosts; only a rehearsal points them at a stub |
| `NORBOTEN_SIGN_INS_PER_MINUTE` | `10` | sign-ins one client may start, and one-time codes it may exchange, per minute |
| `NORBOTEN_DISCORD_CLIENT_ID`, `NORBOTEN_DISCORD_CLIENT_SECRET`, `NORBOTEN_DISCORD_BOT_TOKEN` | *(empty)* | optional: linking Discord on the account page, and the weekly digest as a direct message from the bot. Empty and Discord is hidden and no digest is sent |
| `NORBOTEN_DISCORD_GUILD_ID` | *(empty)* | the Norboten Discord server that "join the server" adds a member to |
| `NORBOTEN_DISCORD_API_URL`, `NORBOTEN_DISCORD_AUTHORIZE_URL` | Discord's | only a rehearsal changes them |
| `NORBOTEN_ALLOWED_ORIGINS` | `https://norboten.org,https://www.norboten.org` | browser origins allowed by CORS |
| `NORBOTEN_OLLAMA_URL` | *(empty)* | `http://ollama:11434`; empty means no local model |
| `NORBOTEN_CONSULTANT_MODELS` | `ollama/qwen2.5:0.5b` | tried in order; the first this server can reach answers the consultant |
| `NORBOTEN_CHAT_PER_MINUTE` | `20` | consultant questions per client per minute |
| `NORBOTEN_TELEMETRY_ENABLED` | `true` | accept opt-in stuck-point telemetry |
| `NORBOTEN_RATED_DIR` | *(empty)* | the rated labs and banks, mounted read-only (`/app/rated` in the compose file); empty or missing means this server has none — a self-hosted server has no rated content unless it brings its own |
| `NORBOTEN_STRIPE_SECRET_KEY` | *(empty)* | donations: `sk_live_…`, or `sk_test_…` to rehearse. Empty and the donate page says the card path is off on this deployment |
| `NORBOTEN_DONATIONS_PER_MINUTE` | `6` | Checkout Sessions one client may start per minute |

The server uses Ollama models only (`ollama/<name>`); it reads no hosted model key, so a key in its
environment changes nothing.

## The stack's settings

`deploy/.env` on a server (written by Ansible from the vault), `deploy/.env.local` on a laptop
(written by `make stack-up` with fresh passwords). See `deploy/.env.example`.

| Variable | Meaning |
|---|---|
| `NORBOTEN_DOMAIN` | the apex; `api.`, `status.` and `www.` are derived |
| `ACME_EMAIL` | Let's Encrypt's contact for expiry notices |
| `API_IMAGE`, `API_TAG` | the API image; `deploy.sh` rewrites the tag |
| `API_WORKERS` | uvicorn workers, default 2 |
| `POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD` | required; `openssl rand -base64 32` |
| `MCP_STATE_KEY` | the MCP server's shared state key (`NORBOTEN_MCP_STATE_KEY`); `install-server.py` generates one |
| `API_URL` | overrides `NORBOTEN_API_URL`; default `https://api.<domain>` |
| `OLLAMA_MODEL` | the model `ollama-pull` fetches; default `qwen2.5:0.5b` |
| `OLLAMA_MEMORY` | Ollama's memory limit, default `1g`; past it only Ollama is killed, and it restarts. It runs one request and keeps one model loaded at a time, with a 4,096-token context |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT` | live sessions announced by the API; empty sends nothing |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | the GitHub OAuth App; without it nobody can sign in. A laptop stack needs an app of its own, with the callback `http://localhost:8000/auth/github/callback`, and without one uses the debug identity |
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` | optional: Discord linking and the Sunday digest; without the bot token the digest timer stays off |
| `CONSULTANT_MODELS` | overrides `NORBOTEN_CONSULTANT_MODELS` |
| `SITE_DIR` | where Caddy serves the site from, default `./site` |
| `RATED_DIR` | the rated content on the host, default `/opt/norboten/rated`; mounted into the API read-only, never into the image |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS` | local dumps, default `/var/backups/norboten`, 14 |
| `BACKUP_TARGET`, `RESTIC_PASSWORD` | an off-box restic repository, optional |
| `CADDY_GLOBAL` | extra Caddy global options; the rehearsal sets `local_certs` |

## The site's settings

`site/build.py` reads three variables; all three are empty or defaulted in a plain checkout, so a
self-hosted build ships no third-party script at all.

| Variable | Default | Meaning |
|---|---|---|
| `NORBOTEN_SITE_API` | `https://api.norboten.org` | the API the pages call for ratings, live sessions and the consultant |
| `NORBOTEN_SITE_URL` | `https://norboten.org` | the site's own address: canonical links, Open Graph and the JSON-LD |
| `NORBOTEN_SITE_GA_ID` | *(empty)* | a GA4 measurement ID (`G-…`) adds the analytics tag; empty adds no script and sets no cookie |

## The client's settings

| Variable | Meaning |
|---|---|
| `NORBOTEN_API` | the API the TUI talks to |
| `NORBOTEN_HOME` | where everything local is kept, default `~/.norboten` (keep the path short: UNIX socket paths are limited to 104 bytes) |
| `NORBOTEN_LABS_DIR` | labs from a directory instead of the cache |
| `NORBOTEN_IMAGE_MIRROR` | a directory or URL of locally built golden images |
| `NORBOTEN_LAB_REGISTRY` | the OCI repository prefix labs are pulled from |
| `NORBOTEN_DEBUG_USER` | act as this user against an API with `NORBOTEN_REQUIRE_AUTH=false` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | optional: models for the tutor, the review and drafting your own questions (`g` on Theory), after Claude Code |
| `OLLAMA_HOST` | an Ollama for the same, last in order; without it the TUI looks for one on `127.0.0.1:11434` |
| `NORBOTEN_CLAUDE_BIN` | the Claude Code binary for `claude-code/…` model ids, default `claude` |

## Choosing models

The server never calls a hosted model, and runs only one: the consultant's, on Ollama. The tutor
and the review of a finished attempt run in the TUI on the learner's own model — Claude Code on
their subscription, then an exported key, then a local Ollama, or the one pinned with `m` on System
— and with none of them `t` shows each lab's four-level hint ladder. Theory questions are not generated on the server at all: they are drafted on a maintainer's machine
on a Claude subscription and published in the repository's banks (docs/quiz-spec.md §5).

A 0.5B model answers the consultant in seconds on a CPU, and its answers are plain. Most of what makes
an answer right is the retrieval in front of it: on the ten questions in
`api/tests/consultant_eval.py`, `qwen2.5:0.5b` gets 8 right and `qwen2.5:1.5b` 9, and the two it
misses are numbers it misreads from the passage it was given. `OLLAMA_MODEL` and
`CONSULTANT_MODELS` can name a larger one — `qwen2.5:1.5b` needs about 1.4 GB of memory while
loaded, more than Ollama's 1 GB limit (raise `OLLAMA_MEMORY` on a server with room for it), and
`qwen2.5:3b` about 4 GB to itself. Run the eval against the model before switching.
