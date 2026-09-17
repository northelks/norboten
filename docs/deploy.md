# Deploying the server

Everything Norboten runs on the internet — the API, the database, Redis, the consultant's model,
monitoring and the site — lives on **one machine** and starts with one command. This page is
the whole procedure, from an empty account to a server that deploys itself on every push.

Labs never run on the server. They run on each learner's own machine, under QEMU with hardware
acceleration; the server only holds accounts, ratings, recordings and the site.

## What you need

| | |
|---|---|
| A server | Ubuntu 26.04 LTS (24.04 works too), 2 vCPU, 4 GB RAM, 40 GB disk, public IPv4 and IPv6. The smallest rehearsed is 1 vCPU, 2 GB, 20 GB (below). The project runs on a netcup VPS; any VPS or bare-metal box with Ubuntu and root SSH works the same way. Check netcup's current offers for a plan and its price. |
| A domain | Three names point at the server: the apex, `api.` and `status.` (plus `www.`, which redirects). |
| On your machine | An SSH key. Only for the laptop route: `ansible-core` ≥ 2.19 and `ansible-galaxy collection install -r ansible/requirements.yml`. |
| Optional | A restic repository for off-box backups. No model key: the server uses its own Ollama only. |

## The stack

`deploy/compose.yaml` is the source of truth. The same file runs on the server and, with
`compose.local.yaml`, on a laptop.

| Service | Image | Job | Reachable at |
|---|---|---|---|
| caddy | `caddy:2.10-alpine` | TLS (Let's Encrypt, automatic, HTTP/3) · the static site · reverse proxy | `:80`, `:443` |
| api | `ghcr.io/<owner>/norboten-api:<commit>` | FastAPI, 2 uvicorn workers | `api.<domain>` |
| postgres | `postgres:17-alpine` | the database `norboten` (every table, `api/src/norboten_api/db.py`) | compose network only |
| redis | `redis:7.4-alpine` | live frames, rate limits, the board cache; no persistence | compose network only |
| ollama | `ollama/ollama:0.34.0` | the consultant's local model, capped at 1 GB, one request and one model at a time, and the first process killed when memory runs out; `ollama-pull` fetches it once | compose network only |
| prometheus | `prom/prometheus:v3.5.0` | scrapes the API, the host and Postgres; 30 days | compose network only |
| node-exporter, postgres-exporter | | host and database metrics | compose network only |
| grafana | `grafana/grafana:12.1.0` | dashboards over Prometheus and Postgres, behind a login | `status.<domain>` |

Only Caddy publishes ports. `/metrics` on the API returns 404 through Caddy and is read by
Prometheus on the compose network. Server-sent events pass through Caddy unbuffered
(`flush_interval -1`).

### Memory, and what fails first

Ollama is the one part allowed to fail. It is limited to 1 GB without swap, and it carries
`oom_score_adj` 1000, so when the machine runs out of memory the kernel kills it first; PostgreSQL
(-900), Caddy (-800), the API and Redis (-500) come last. It restarts on its own, and while it is
down the consultant answers with the matching passages instead of a model's reply.

Measured with `CPUS=1 MEMORY=2GiB DISK=20GiB make server-rehearsal` (arm64, 2026-09-17):

| | |
|---|---|
| idle, the model not loaded | 992 MiB of 1,949 available; the API 232 MiB (two workers), Grafana 160, Ollama 36 |
| the model loaded (`qwen2.5:0.5b`) | Ollama 712 MiB of its 1 GiB; 287 MiB available |
| the nightly backup, the model loaded | at least 307 MiB available |
| a consultant answer on one vCPU | 19–23 s |
| a host process taking memory until the kernel acts | Ollama's model runner and Ollama killed, then the process itself; Ollama restarted once, nothing else restarted, `/readyz` ready, the site 200, the next answer 18 s |
| disk after the install | 14 of 19 GB used: the images take 10.6 GB, Ollama's 7 GB of it |

On 20 GB, updating Ollama's image needs the old one removed first.

## Create the server

netcup has no official Terraform provider, and the community ones manage a server that already
exists rather than order one, so the machine is ordered by hand; everything after the first login is
the repository's Ansible, run either **on the server by the installer** or from a laptop.

1. **Order a VPS** in the netcup Customer Control Panel (CCP) and open it in the Server Control
   Panel (SCP). Under *Media → Images*, install **Ubuntu 26.04 LTS** with your SSH public key; note
   the IPv4 and IPv6 addresses.
2. **DNS.** Point `@`, `www`, `api` and `status` at the server with A and AAAA records — in the
   CCP's DNS management if the domain is registered at netcup, otherwise at its registrar. A CAA
   record for `letsencrypt.org` is optional. Caddy cannot get certificates until the names resolve,
   so give them a few minutes before installing.

## Install with one command, on the server

```sh
ssh root@<server>
git clone https://github.com/northelks/norboten.git /opt/norboten-src
python3 /opt/norboten-src/deploy/install-server.py --domain <domain> --email <you@domain> \
    --github-client-id <id> --github-client-secret <secret>
```

**The GitHub OAuth App is not optional.** Signing in is GitHub and nothing else, so a server without
one comes up and works — and nobody can sign in to it. Create it first (below, "Signing in"). Without
`--github-client-id` the installer finishes and says so; run it again with both flags once the app
exists — everything else it keeps. Discord is optional: `--discord-client-id`,
`--discord-client-secret`, `--discord-bot-token` and `--discord-guild-id` turn on linking and the
weekly digest.

`deploy/install-server.py` needs nothing but Python, which Ubuntu has. It:

1. checks the machine (Ubuntu LTS, root, memory, disk) and that every name resolves to it, and asks
   before going on if one does not;
2. installs Ansible into its own virtualenv, `/opt/norboten-installer`;
3. runs `ansible/playbooks/bootstrap.yml` on the server itself: the `deploy` user with every key
   root already accepts, a new key for GitHub Actions (`/root/norboten-ci/deploy_ed25519`), and
   passwordless sudo;
4. runs `ansible/playbooks/server.yml` the same way (next section);
5. pulls `ghcr.io/northelks/norboten-api:latest`, or builds the image from the clone when nothing
   has been published yet;
6. brings the stack up with `deploy.sh`, which rolls back if the API never turns ready;
7. builds the site from the clone into `/opt/norboten/site`;
8. prints the addresses and exactly what to put into GitHub for deploys on push.

The PostgreSQL and Grafana passwords are generated on the first run and kept in
`/etc/norboten/install.json` (root only); running the installer again keeps them. Everything it runs
is logged to `/var/log/norboten-install.log`. `--dry-run` prints the commands without running them,
`--no-site` skips the site, `--build-api` builds the image even if one could be pulled.

Before closing the root session, check from a second terminal that `ssh deploy@<server>` works:
root and password logins are off from then on.

## Or from a laptop

The same playbooks, over SSH:

```sh
cp ansible/inventory/production.yml.example ansible/inventory/production.yml   # address, domain, e-mail
make bootstrap                      # as root, once; KEY=path/to/key.pub for another key
cd ansible
cp group_vars/all/vault.yml.example group_vars/all/vault.yml
$EDITOR group_vars/all/vault.yml    # openssl rand -base64 32 for each password
ansible-vault encrypt group_vars/all/vault.yml
ansible-playbook -i inventory/production.yml playbooks/server.yml --ask-vault-pass \
  -e norboten_api_tag=latest
```

## What the playbooks set up

`server_base` hardens the host — no root or password SSH, `ufw` with only 22/tcp, 80/tcp, 443/tcp and
443/udp open, fail2ban, unattended security upgrades — and installs Docker Engine and the compose
plugin from Ubuntu's own archive. `norboten_stack` copies `deploy/` to `/opt/norboten`, writes
`/opt/norboten/.env` (mode 0600), runs `deploy.sh`, and installs the nightly backup and analytics
timers. The first run pulls about 3 GB of images; Ollama then downloads its model in the background.
Backups are the nightly database dumps below, copied off the machine by restic when a target is set;
netcup's own snapshots, taken in the SCP, are an optional extra.

Check it:

```sh
curl https://api.<domain>/readyz      # {"status":"ready","checks":{"database":"ok","redis":"ok"}}
curl -I https://<domain>/
ssh deploy@<server> 'cd /opt/norboten && sudo docker compose ps'
```

## Signing in, Discord, announcements and the digest

### Signing in: the GitHub OAuth App

GitHub → Settings → Developer settings → OAuth Apps → **New OAuth App**:

- Homepage URL `https://<domain>`, Authorization callback URL `https://api.<domain>/auth/github/callback`
  — an OAuth App has exactly one callback, so a laptop stack needs a second app ("Norboten (local)",
  callback `http://localhost:8000/auth/github/callback`);
- tick **Enable Device Flow**: the terminal signs in with it;
- no scopes are requested, ever; generate a client secret.

Put the client id and secret in the vault as `norboten_github_client_id` and
`norboten_github_client_secret` (or pass them to the installer), then re-run `server.yml`. Secrets go
into the vault or to the installer, never into a chat or a commit.

### Discord: linking and the digest (optional)

Discord Developer Portal → **New Application**:

- OAuth2 → Redirects: `https://api.<domain>/auth/discord/callback` (and
  `http://localhost:8000/auth/discord/callback` for a laptop);
- Bot → reset and copy the token; no privileged intents are needed — the bot never connects to the
  gateway, it only sends direct messages over REST;
- OAuth2 → URL Generator, scope `bot`, permissions **Create Instant Invite** and **Send Messages**:
  open the URL and add the bot to the Norboten server;
- the server's id (Developer Mode on, right-click the server, Copy Server ID).

Vault: `norboten_discord_client_id`, `norboten_discord_client_secret`, `norboten_discord_bot_token`,
`norboten_discord_guild_id`; re-run `server.yml`. The account page then offers **Connect Discord**
(with "join the Norboten server", off by default), and the Sunday digest timer turns itself on.

### Announcements and donations

These are built in and off until they have somewhere to send to:

| What | Where it is set |
|---|---|
| Telegram: a live session going public | `norboten_telegram_bot_token`, `norboten_telegram_chat` (Ansible vault), re-run `server.yml` |
| The Sunday learner digest | nothing more: the timer turns itself on once `norboten_discord_bot_token` is set |
| Discord and Telegram release announcements | GitHub secrets `DISCORD_WEBHOOK`, `TELEGRAM_BOT_TOKEN` and variable `TELEGRAM_CHAT` |
| Donations on the site | `norboten_stripe_secret_key` (Ansible vault), re-run `server.yml`. Without it the donate page says card donations are off on this deployment and shows the other ways to help; nothing else on the site changes |

**Donations.** The API creates one Stripe Checkout Session per click (`POST /donations/checkout`)
with an inline price, so no product or price has to exist in the Stripe account, and the donor
finishes on Stripe's own page: no card detail ever reaches this server, and nothing about a
donation is stored here. The tiles are €5, €10, €15, €20, €25 and €50, monthly or one-off, and a
free amount between €2 and €5000; `site/build.py` (`DONATION_TIERS`) and
`api/src/norboten_api/routers/donate.py` (`TIERS`) have to agree. Rehearse with an `sk_test_…` key
and Stripe's test cards before putting the live one in the vault.

## Deploy on every push

`.github/workflows/deploy.yml` does, on each push to `main`:

1. **test** — ruff, the whole pytest suite with PostgreSQL and Redis as service containers, and
   the node checks for the terminal player and the consultant's fallback;
2. **image** — builds `api/Dockerfile` for amd64 and arm64 and pushes
   `ghcr.io/<owner>/norboten-api:<commit>` and `:latest`;
3. **site** — generates the sample population and builds `site/dist` against `https://api.<domain>`;
4. **rollout** — rsyncs `deploy/` and `site/dist` to the server over SSH, runs
   `sudo /opt/norboten/deploy.sh <commit>`, and checks `/readyz` and the site from outside.

It needs, in the repository's settings:

| Kind | Name | Value |
|---|---|---|
| variable | `SERVER_HOST` | the server's address; without it the rollout job is skipped |
| variable | `SERVER_HOST_KEY` | `ssh-keyscan -t ed25519 <server>` — pinned, never trusted on first use |
| variable | `NORBOTEN_DOMAIN` | e.g. `norboten.org` |
| secret | `DEPLOY_SSH_KEY` | the private key the installer made (`/root/norboten-ci/deploy_ed25519`; delete the file afterwards), or the one you gave `make bootstrap` |
| environment | `production` | add required reviewers here if a push should wait for approval |

The GHCR package must be public, or the server must `docker login ghcr.io` once with a read-only
token.

## Rollback

`deploy.sh <tag>` pulls the image, restarts the API, and waits up to two minutes for `/readyz`. If
it never turns ready, it puts the previous tag back, restarts that, and exits non-zero — so a bad
image fails the workflow and leaves the previous version serving. The tag in use is in
`/opt/norboten/.deployed`, the one before it in `.deployed.previous`.

To go back deliberately:

- **from GitHub** — Actions → deploy → Run workflow → `api_tag` = the commit to return to. It
  checks out that commit's `deploy/`, skips the build, and rolls out the image already in GHCR;
- **on the server** — `sudo /opt/norboten/deploy.sh $(cat /opt/norboten/.deployed.previous)`.

The database schema only ever grows (every statement in `db.SCHEMA` is `IF NOT EXISTS`), so an
older API runs against a newer database.

## Backups

`/opt/norboten/backup.sh` runs nightly at 03:20 (`norboten-backup.timer`):

1. `pg_dump -Fc` of `norboten` into `/var/backups/norboten`, on the server's disk;
2. **restores the dump into a scratch database** and counts users and attempts — a dump that does
   not restore fails the run, and `systemctl status norboten-backup` shows it;
3. deletes dumps older than 14 days;
4. with `BACKUP_TARGET` set, copies the directory off-box with restic and keeps 14 daily and 8
   weekly snapshots.

Restore:

```sh
sudo /opt/norboten/restore.sh /var/backups/norboten/norboten-<stamp>.dump
```

Redis is not backed up: nothing in it has to survive. Ollama's model re-downloads. Caddy's
certificates are re-issued if the disk is lost.

## Operations

| Task | Command, in `/opt/norboten` |
|---|---|
| status | `sudo docker compose ps` |
| logs | `sudo docker compose logs -f --tail 100 api` |
| a shell in the database | `sudo docker compose exec postgres psql -U norboten` |
| restart one service | `sudo docker compose restart api` |
| change a secret | edit the vault, rerun the playbook |
| a larger model | `OLLAMA_MODEL=qwen2.5:3b` in the vault, rerun, and set `NORBOTEN_CONSULTANT_MODELS` |
| disk | `sudo docker system df`; images from old deploys are pruned on every successful deploy |
| a manual backup | `sudo ./backup.sh` |
| redraw the Analytics page now | `sudo systemctl start norboten-analytics` (nightly at 04:10 otherwise) |
| send the learner digest now | `sudo systemctl start norboten-digest` (Sundays at 18:00 otherwise; only with `norboten_discord_bot_token` set). `sudo docker compose --profile jobs run --rm digest python -m norboten_api.digest --dry-run` prints it instead |

Grafana (`status.<domain>`, user `admin`) has Prometheus and the Norboten database provisioned as
data sources, and two dashboards in the folder **Norboten**, both provisioned from
`deploy/grafana/provisioning/dashboards` — they come back as they are on every restart, so edits
made in the browser are not kept:

| Dashboard | Datasource | What it answers |
|---|---|---|
| **Service** | Prometheus | Is the API up and how fast is it (rate by status, median/p95/p99, the five slowest route templates), can Prometheus reach every target, how the host is doing — and how much room is left on `/`, which is the first thing to fail on a 20 GB server |
| **Norboten** | Postgres | What learners did: accounts, attempts by day passed against failed, the labs being worked on, the events the API wrote down, ratings by topic. The sample population is excluded everywhere (`users.seed`), so these are real accounts only |

Streams keep working through an API restart: viewers' browsers reconnect and replay from the
recording.

## Everything on a laptop

`make stack-up` runs the same compose file with `compose.local.yaml`: the API built from your
checkout, the site from `site/dist`, plain HTTP, the sample population loaded, and the debug
identity accepted. The site is on <http://localhost:8080>, the API on <http://localhost:8000>,
Grafana on <http://localhost:3000>. Point the TUI at it with
`NORBOTEN_API=http://localhost:8000 uv run norboten`. `make stack-down` stops it; `V=1` deletes its
data too.

Lab VMs still run on the host under QEMU, never inside Docker — there is no nested virtualization
for QEMU on macOS, and a lab needs a real kernel.

## Rehearsing the deploy

`make server-rehearsal` rehearses all of the above on a local Ubuntu LTS VM (Lima, 4 CPUs, 6 GB; `CPUS`, `MEMORY` and `DISK` size a new one): the
production playbook configures it — hardening, firewall, Docker, the compose project, the timers —
and the same `deploy.sh` rolls the API out. Three things differ, the three a laptop cannot have:
the API image is built locally and loaded into the VM instead of pulled from GHCR, the domain is
`norboten.test`, and Caddy issues certificates from its own CA (`CADDY_GLOBAL=local_certs`)
instead of Let's Encrypt. When it finishes it prints the API's readiness and the site's status
through Caddy on <https://norboten.test:8443> (curl with `-k` and `--resolve`). `make
server-rehearsal-down` deletes the VM.

The first rehearsal found two faults a real first deploy would have hit, both fixed: a compose
restart ran before the API image existed, and one image that could not be pulled aborted the
pulls of all the others.

## Hosted labs

Running learners' lab VMs on the server would need `/dev/kvm`. Cloud VPS instances do not offer
nested virtualization, so that is only possible on bare metal (a dedicated root server), and it is
not built.
