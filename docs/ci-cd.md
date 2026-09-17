# CI/CD

Every workflow in `.github/workflows`, what triggers it, what it proves, and what it ships.

```
pull request ──► cli-test (lint · specs · tests on 3 OSes) ──► labs (the gate, touched labs × images) ──► quiz (verify)
                                                                                                        │
push to main ──► deploy: test (PostgreSQL + Redis) ──► image (GHCR, amd64 + arm64) ──┐                  │
                                              └────► site (build) ───────────────────┴─► rollout (rsync + deploy.sh + smoke test)
tag v* ────────► release: wheels (tested outside the checkout) ──► PyPI ──► GitHub release (notes: Claude)
                                                                                           └──► announce (Discord, Telegram)
tag v* ────────► publish labs (OCI + cosign)
manual ────────► publish base images (KVM runner) ──► PR with the new digests
manual ────────► deploy with api_tag = an older commit  (rollback)
nightly ───────► labs --all ──► report (an issue per lab that stopped solving)
issue opened ──► triage (Claude Code, Haiku, no tools)
issue labelled lab-request ──► lab-author (Claude Code subagent) ──► draft pull request
Mondays ───────► stuck-points (Claude Code, Haiku, no tools) ──► Discord, a hints issue
```

## `cli-test.yml` — on every push and pull request

Ubuntu only: macOS and Windows are not run here (macOS is what development happens on, and
Windows is unsupported — see `docs/faq.md`).

1. `uv sync --all-packages --frozen` — the lockfile must be current.
2. `ruff check` and `ruff format --check`.
3. `python -m norboten.labs.lint labs` — every lab and journal against the spec.
4. Regenerates `docs/schema/*.json` and `docs/api-reference.md` and fails if either differs from
   the committed copy.
5. `python -m pytest -m "not docker"` — the whole suite (about 480 tests): the TUI through
   Textual's pilot, the API through its test client, the stores in memory.
6. On Ubuntu, the node checks: the terminal player against every shipped recording, and the
   consultant's browser fallback against the Python tokenizer.
7. `norboten dev doctor` — printed, never gating: runners have no KVM.

## `lab-validate.yml` — the solvability gate

On every push and pull request. `.github/scripts/changed_labs.py` picks the labs a change touches
(all of them if it touches the runner, the engine, the registry or the baseline role) and emits a
matrix of lab × base image. Each job needs `/dev/kvm`, installs QEMU, and runs
`norboten dev validate <lab> --image <image>`: clean VM, faults, every check must fail, reference
solution, every check must pass, reboot, every check must pass again. A `boot_after_break` lab then
gets a second phase on a fresh VM: faults, one more boot as the learner's machine gets, and every
check must still fail — over SSH, or over a serial-port debug shell when that boot stops at a
maintenance prompt (docs/lab-spec.md §9, Q18). On failure it prints the serial console of the gate
VM. 22–77 s per job on an M-series laptop (about 100 s for the two `boot_after_break` labs); longer on
a runner.

Nightly at 02:00 the same workflow runs on a schedule with every lab on every image, changed or not
— upstream distributions change under labs that did not — and a last job, `report`, reads the run's
own jobs back and opens a `broken-lab` issue for each failed `gate (<lab>, <image>)` unless one is
open (`automation/jobs/lab_health.py`).

## `quiz-verify.yml`

Validates every question bank and runs every executable question in a network-less container:
the snippet's output must equal the answer key.

## `deploy.yml` — push to main

| Job | Does | Needs |
|---|---|---|
| `test` | ruff, pytest with `NORBOTEN_TEST_DATABASE_URL` and `NORBOTEN_TEST_REDIS_URL` pointing at service containers (so the store and bus tests run against the real thing), node checks | — |
| `image` | `docker buildx` of `api/Dockerfile` for amd64 and arm64, pushed as `ghcr.io/<owner>/norboten-api:<sha>` and `:latest`, with the GitHub Actions cache | `packages: write` |
| `site` | `seed/generate.py`, then `site/build.py` with `NORBOTEN_SITE_API=https://api.<domain>`, `NORBOTEN_SITE_URL=https://<domain>` and the optional `NORBOTEN_SITE_GA_ID` variable, uploaded as an artifact | — |
| `rollout` | rsync `deploy/` (never `.env`) and `site/dist` to `/opt/norboten`, `sudo deploy.sh <sha>` over SSH, then `curl` `/readyz` and the site from outside | `SERVER_HOST`, `SERVER_HOST_KEY`, `NORBOTEN_DOMAIN` variables; `DEPLOY_SSH_KEY` secret; the `production` environment |

`rollout` is skipped until `SERVER_HOST` exists, so the workflow is safe in a fork. It runs in the
`production` environment — add required reviewers there to make every deploy wait for a person.
The concurrency group never cancels a rollout halfway.

**Rollback.** Run the workflow by hand with `api_tag` set to an earlier commit: the build jobs are
skipped, the rollout checks out that commit's `deploy/` and rolls out its image, which is still in
GHCR. `deploy.sh` also rolls back on its own when a new image does not report ready within two
minutes, and the job then fails.

## `release.yml` — on a `v*` tag

Builds the `norboten` and `norboten-runner` wheels, installs them into a clean environment outside
the checkout and checks the installed package finds its labs, banks and journals, runs `install.sh`
end to end against them, then publishes to PyPI (trusted publishing), creates the GitHub release
with the wheels and `install.sh`. See
[Releasing](../releasing/index.html).

The release notes are drafted by Claude Code (Haiku, no tools) from the commits since the previous
tag, with the full commit list appended; without `CLAUDE_CODE_OAUTH_TOKEN` they are the list alone.
After the release, `announce` posts it to Discord and each lab it adds to Telegram — no model.
Between releases, `announce-content` does the other half: every push to main that adds a lab, a
journal or a question bank posts one message to the same channel, read from the push's own diff
(`automation/jobs/announce_content.py`). Both do nothing without `DISCORD_WEBHOOK`, and neither
ever names anything under `rated/`.

## Claude Code jobs — `triage.yml`, `stuck-points.yml`, `lab-author.yml`

Each installs one pinned Claude Code (`.github/actions/claude-code`), authenticates with the
`CLAUDE_CODE_OAUTH_TOKEN` secret, has a timeout and a concurrency group, and skips with a notice
when the secret is not set. What each may do, and why, is in
[Architecture](../architecture/index.html#automation).

| Workflow | Trigger | Secrets and variables |
|---|---|---|
| `triage.yml` | `issues: opened`, not by a bot | `CLAUDE_CODE_OAUTH_TOKEN` |
| `stuck-points.yml` | Mondays 08:00, or by hand | `CLAUDE_CODE_OAUTH_TOKEN`, `DISCORD_WEBHOOK`; variable `NORBOTEN_API` |
| `lab-author.yml` | `issues: labeled` with `lab-request` | `CLAUDE_CODE_OAUTH_TOKEN`, `DISCORD_WEBHOOK` |
| `release.yml` (`announce`) | after the GitHub release | `DISCORD_WEBHOOK`, `TELEGRAM_BOT_TOKEN`; variable `TELEGRAM_CHAT` |

## `lab-publish.yml` — on a `v*` tag

Builds each lab into an OCI image with `images/Dockerfile.lab`, pushes `<id>:<version>` and
`:latest` to `ghcr.io/<owner>/norboten-labs`, and signs the digest with cosign (keyless, the
workflow's OIDC identity).

## `image-publish.yml` — manual

Builds one golden image on a KVM runner with `images/build.py`, pushes it with `oras` as
`ghcr.io/<owner>/norboten-base/<id>:<version>`, and opens a pull request that writes the new digest
into `images/registry.yaml` — which runs the gate for every lab before it can merge.

## Locally

| Command | Mirrors |
|---|---|
| `make check` | `cli-test.yml` without the OS matrix |
| `make test-db` | the `test` job's PostgreSQL and Redis tests, in throwaway containers |
| `make validate LAB=<id>` | one job of the gate |
| `make infra-validate` | both playbooks' syntax, both compose files and the Caddyfile |
| `make server-rehearsal` | the `rollout` job, against a local VM instead of the server |
| `make release-check` | the `build` job of `release.yml` |
| `make jobs-rehearsal` | triage, stuck-points, lab-author, the nightly report and the release jobs, with a real `claude` and a scripted model |
