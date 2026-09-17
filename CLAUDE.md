# Norboten

Learn Linux by fixing it: a TUI boots a real VM (or container) with something broken, and grades
the machine's state — before and after a reboot. `README.md` is the overview; the specs in `docs/`
are normative (`lab-spec.md`, `quiz-spec.md`, `writing-a-lab.md`).

This file is read by every Claude Code session in the checkout, including the `lab-author` CI job:
keep it short. Workflows are the `norboten-author` plugin's skills (`plugins/`, enabled here).

## Layout

- `cli/src/norboten/` — the TUI and engine (`session/`, `lima/`, `containers.py`, `labs/`, `quiz/`)
- `runner/norboten_runner/` — copied into guests: **standard library only**
- `api/src/norboten_api/` — FastAPI: accounts, ratings, the consultant (`agents/`); the tutor and
  the question pipeline run on the learner's machine (`cli/src/norboten/tutor/`, `questions/`)
- `labs/<track>/<id>/` — `lab.yaml`, `briefing.md`, `hints.yaml`, `break/`, `check/`, `solution/`,
  `journal.md`, `theory.yaml`; `labs/_template/` to start from
- `quizzes/<topic>.yaml` — topic banks; `journals/` — topic journals
- `images/` — golden image registry and builder; `ansible/`, `deploy/` — the server
- `automation/jobs/` — the CI jobs (some run Claude Code headless); `automation/rehearse.py`
- `site/` — the static site generator
- `plugins/norboten-author/` — the Claude Code plugin; the repo is its marketplace (`.claude-plugin/`)

## Commands

```sh
uv sync --all-packages --all-extras          # the venv
uv run python -m pytest -m "not docker"      # tests (~70 s); -m docker for container labs
make lint                                    # ruff check, ruff format --check, lab lint
uv run norboten dev lint labs/<track>/<id>   # one lab against the spec, no VM
make validate LAB=<id>                       # the solvability gate: boots VMs, minutes
uv run norboten dev verify-quiz              # executable questions, in Docker
make jobs-rehearsal                          # CI jobs with a real claude and a scripted model
make schema                                  # after changing models.py or the API
```

VM work needs a short sandbox home: `export NORBOTEN_HOME=/tmp/nb` (UNIX sockets cap paths at 104
bytes) and `NORBOTEN_IMAGE_MIRROR=$PWD/images/out` for locally built images.

## Rules

- A check grades machine state and must still pass after the reboot; a fix of the symptom rather
  than the cause must leave a check failing. The tutor and consultant never see a solution file.
- After changing the runner, guest paths, `images/registry.yaml` or the baseline role, re-run the
  gate for every lab.
- Numbers quoted in docs and on the site are measured, never estimated.
- `seed/accounts.json` is generated (`make seed`), never committed. No secrets in the repo.
- Commits: conventional (`feat(labs): …`), one change per commit.

## Traps

- After rebuilding an image, `norboten image rm <id>` — the CLI keeps serving the old import.
- `/run` is noexec on the systemd images: `sh script`, not `./script`.
- A lab may take sudo from the learner: anything after the faults runs as `guest.GRADER`.
- Test modules need unique basenames across `tests/`, `cli/tests/`, `api/tests/`.
- Textual: wait on conditions, not idle; `App.suspend()` only resumes on a clean exit
  (`handed_over()` in `tui/lab.py`).
- `docker info` hangs when Docker Desktop is stopped; macOS `sed -i` needs `''`.
