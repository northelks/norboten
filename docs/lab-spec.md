# Lab specification

**Status: normative.** The CLI, the guest runner, the CI solvability gate and the Lab Author agent
all implement this document. If code and this document disagree, the code is wrong. A breaking
change to this document requires a `schema_version` bump.

The machine-readable form of this spec is `cli/src/norboten/models.py` (Pydantic). `make schema`
exports it to `docs/schema/lab.schema.json` and `docs/schema/registry.schema.json` for editors and
for the Lab Author agent.

---

## 1. A lab is a directory

```
<lab-id>/
├── lab.yaml              # manifest (section 2)
├── briefing.md           # what the learner sees on start (section 6)
├── break/                # faults, applied once to a clean snapshot (section 4)
│   └── NN_name.py
├── check/                # what "fixed" means (section 5)
│   └── NN_name.py
├── hints.yaml            # the hint ladder (section 7)
└── solution/
    ├── solution.sh       # reference fix — CI and post-mortem only (section 8)
    └── <base_image>.sh   # optional per-image override
```

- The directory name **must** equal `id` in `lab.yaml`.
- Labs live in `labs/<track>/<id>/`. Two exceptions: `labs/hello/` (the intro track) and
  `labs/_template/`.
- Files in `break/` and `check/` are named `NN_snake_case.py`, where `NN` is two digits. They run
  in lexical order. A check's id is its file stem (`01_boots_clean`).
- Extra files (for example fixtures under `files/`) are allowed and ship with the lab. Scripts see
  the lab directory as `ctx.lab_dir`.

---

## 2. `lab.yaml`

```yaml
schema_version: 1
id: rhcsa-03-storage-and-lvm
version: 1.0.0                # semver; bump on any content change — it is the OCI tag
title: The Disk That Ate /var
track: rhcsa                  # rhcsa | linux | automation | bash | python | ansible | docker | terraform | claude | mcp | intro
topics: [storage-lvm, boot-systemd]   # 1-5 slugs from the taxonomy (section 10)
difficulty: 3                 # 1-5
estimated_minutes: 45
base_images: [rocky-10]       # ids from images/registry.yaml; the first is the default
runtime: vm                   # vm | container (container: no kernel, boot, LVM or reboot)
resources:
  cpus: 2
  memory: 2GiB                # >= the base image's min_memory
  disks: [{size: 4GiB}]       # extra disks beyond the root disk: /dev/vdb, /dev/vdc, …
objectives:                   # RHCSA: EX200 domains. Linux / intro: plain skill statements.
  - "Manage local storage: create and extend LVM volumes"
  - "Mount filesystems persistently by UUID"
checks:                       # every file in check/, in file order, mapped to an objective
  - {id: 01_boots_clean, objective: 2}
  - {id: 02_var_has_headroom, objective: 1, weight: 2}
reboot_required: true         # check → reboot → check again; both passes must pass
boot_after_break: true        # reboot once after the faults, so the learner meets the broken boot
time_limit_minutes: null      # 90 for the exam simulation
pass_percent: 100             # weighted score needed to pass; 70 for the exam simulation
```

| Field | Type | Rule |
|---|---|---|
| `schema_version` | int | `1` for this document. |
| `id` | str | `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 63 chars, equals the directory name. |
| `version` | str | Semver `MAJOR.MINOR.PATCH`. |
| `title` | str | 3–60 chars. A situation, not a topic ("The Disk That Ate /var", not "LVM"). |
| `track` | enum | `rhcsa`, `linux`, `automation`, `bash`, `python`, `ansible`, `docker`, `terraform`, `claude`, `mcp` or `intro`. |
| `topics` | list[str] | 1–5 unique slugs from the taxonomy (section 10). What the attempt rates. |
| `difficulty` | int | 1–5. Also sets the rated clock and the opponent a rated attempt plays. |
| `estimated_minutes` | int | 5–240. |
| `base_images` | list[str] | Non-empty, unique. Each id exists in the registry and serves `track` (section 3). |
| `runtime` | enum | `vm` or `container`. A `container` lab runs on a `kind: container` image (§3), cannot be `reboot_required` or `boot_after_break`, and has no extra disks. |
| `resources.cpus` | int | 1–4, default 1. |
| `resources.memory` | size | `NNNMiB` or `N.NGiB`. Default and floor: the base image's `min_memory`. |
| `resources.disks` | list | 0–4 extra disks, each `{size}` between 1GiB and 32GiB. |
| `objectives` | list[str] | Non-empty. Referenced from `checks[].objective` by 1-based index. |
| `checks` | list | Non-empty, ids unique, in file order, matching `check/*.py` exactly. |
| `checks[].objective` | int | 1-based index into `objectives`. Every objective has at least one check. |
| `checks[].weight` | int | 1–10, default 1. |
| `checks[].baseline_pass` | bool | Default `false`. See section 9. |
| `checks[].maintenance_pass` | bool | Default `false`. Only with `boot_after_break`. See section 9. |
| `reboot_required` | bool | Must be `true` for every `vm` lab outside the `intro` track. |
| `boot_after_break` | bool | Default `false`. |
| `time_limit_minutes` | int \| null | Default `null`. |
| `pass_percent` | int | 1–100, default 100. |
| `rated` | bool | Default `false`. `true` only for a lab under `rated/`, which then has `collect/` (section 13). |

---

## 3. Tracks and base images

Base images are defined once, in `images/registry.yaml`. Each entry lists the tracks it serves. A
lab may use a base image only if that image serves the lab's track.

| Image | Distro | init | pkg | MAC | Tracks |
|---|---|---|---|---|---|
| `rocky-10` | Rocky Linux 10 | systemd | dnf | SELinux | `rhcsa`, `intro` |
| `ubuntu-26.04` | Ubuntu 26.04 LTS | systemd | apt | AppArmor | `linux`, `intro` |
| `alpine` | Alpine Linux 3.23 | OpenRC | apk | none | `linux`, `intro` |
| `ubuntu-26.04-automation` | Ubuntu 26.04 + Ollama (qwen2.5:0.5b, all-minilm), PostgreSQL, nginx | systemd | apt | AppArmor | `automation` |
| `ubuntu-26.04-devops` | Ubuntu 26.04 + Docker, Terraform, Ansible, Python tooling | systemd | apt | AppArmor | `bash`, `python`, `ansible`, `docker`, `terraform` |
| `ubuntu-26.04-container` | Ubuntu 26.04, as a container | none | apt | none | `linux` |
| `ubuntu-26.04-claude` | Ubuntu 26.04 + Claude Code 2.1.270 and a scripted model, as a container | none | apt | none | `claude`, `mcp` |

The `intro` track exists for `hello`: one lab that runs on every image. It exercises the full
download → boot → break → check path on each base before any real lab depends on it.

A registry entry carries two image sources:

- `upstream` — the distro's own cloud image, per arch (`url`, `digest`). Only the golden image
  builder reads it.
- `golden` — the image the CLI actually downloads: an OCI reference plus a per-arch `digest` and
  `size_bytes`. A golden image is the upstream image with the lab baseline applied by Ansible
  (`ansible/roles/lab_baseline`). Labs never install packages at runtime, so once an image and a
  lab are cached, the CLI works offline.

**Container images** (`kind: container`) have neither: a `container` block names a Dockerfile under
`images/` and the local tag to build it as. The CLI builds it with Docker or Podman the first time a
container lab starts (`docker build` with the Dockerfile's directory as the context), and the wheel
carries that directory. `init` is `none` — PID 1 is `sleep infinity` and every shell, break, check and solution
arrives through `exec` — and a lab's `runtime` must match its images' kind. The container contract is
the golden image contract below, except: no boot, no console, no reboot, no root-password recovery;
the learner is `learner`; and grading runs as root through `exec`, which a lab cannot take away, so no
grader account is created. The clean snapshot is a `commit` of the container before the faults, and a
reset recreates it from that image (under a second).

The golden image contract — runner and labs may rely on it:

| Item | Guarantee |
|---|---|
| `/etc/norboten/base.json` | `{"id", "distro", "init", "pkg", "mac", "version"}`, the source of `ctx.facts`. |
| `python3` | In `$PATH`. The runner uses the standard library only. |
| packages | Everything any lab of the image's tracks needs is preinstalled. |
| root password | `norboten`, until a lab changes it. `briefing.md` states it when it matters. |
| learner account | The Lima default user (named after the host user), with passwordless `sudo`. |
| shell history | Bash appends after every command (`PROMPT_COMMAND='history -a'`). |
| console | Bootloader and kernel on the serial console; `k` on the lab's screen attaches to it. |

What `ubuntu-26.04-devops` adds for its tracks, all usable with no network:

| Item | Guarantee |
|---|---|
| Docker | `docker.io` and the Compose plugin (`docker-compose-v2`), **disabled**: a lab that needs it enables `docker.service`. Pre-pulled: `redis:7.4-alpine`, `nginx:1.29-alpine`. |
| Terraform | `/usr/local/bin/terraform` (pinned in `ansible/roles/devops_stack`), with `hashicorp/local ~> 2.5`, `hashicorp/random ~> 3.7` and `hashicorp/null ~> 3.2` mirrored in `/usr/share/terraform/plugins`, so `terraform init` needs no registry. `CHECKPOINT_DISABLE=1`. |
| Ansible | `ansible-core` from Ubuntu. It refuses a non-UTF-8 locale: a break or check that runs it passes `env={"LC_ALL": "C.UTF-8"}` (the runner defaults to `C`). |
| Python | `python3-venv`, `pip`, and a wheelhouse in `/opt/wheels` (`setuptools`, `wheel`, `pyyaml`) for `pip install --no-index --find-links /opt/wheels`. |
| Shell | `shellcheck`, `jq`. |

---

## 4. Break scripts

```python
"""The /var LV has no free extents left."""  # one-line docstring, for maintainers only


def apply(ctx):
    ctx.run("lvcreate -n filler -l 100%FREE vg0", check=True)
    ctx.state["filler_lv"] = "filler"
```

- Run as root, inside the guest, once, on the clean snapshot, in lexical order.
- **Idempotent**: running `apply` twice leaves the same state as running it once.
- Each finishes in under 120 seconds.
- Leave no trace of the fault: no explanatory comments written into the guest, no files outside
  `/var/lib/norboten/` (root-only, `0700`), no output to the learner.
- Copied into the guest for the run and deleted afterwards.
- May store values the checks need (a generated UUID, a random port) in `ctx.state`. The runner
  persists it to `/var/lib/norboten/state.json` and loads it for checks.

---

## 5. Check scripts

```python
def check(ctx):
    r = ctx.run(["findmnt", "--verify", "--tab-file", "/etc/fstab"])
    if r.code != 0:
        return ctx.failed("fstab references a device the system cannot find.", evidence=r.out)
    return ctx.passed("fstab verifies cleanly.")
```

A check returns, via `ctx.passed` or `ctx.failed`, exactly:

```json
{"id": "01_boots_clean", "passed": true, "message": "…", "evidence": "…"}
```

- `message` is written for a learner who just failed: **say what was observed, not what to do.**
  "Nothing is listening on port 8080", not "Run semanage port -a …". A message never names the fix.
- `evidence` is raw output (command output, file excerpts), truncated to 4 KiB. The learner can
  see it on request; it feeds the tutor's fact bundle.
- **Read-only.** A check never changes the system. One exception: a functional probe may create
  a file named `.norboten-probe-*` (for example, to prove a user can write where they should) and
  must remove it before returning.
- Each finishes in under 30 seconds. A check that raises or times out counts as failed, with the
  exception as evidence.
- `ctx.phase` is `live` (the TUI's live panel), `pre_reboot` or `post_reboot`.
- Copied into the guest for the run and deleted afterwards, except while the TUI live panel is
  open.

### Grading sequence

```
reboot_required: false   check
reboot_required: true    check (pre_reboot) → reboot → wait for boot → check (post_reboot)
```

A check passes only if it passes in every pass. If the guest is not back within 180 seconds of the
reboot, every check fails the `post_reboot` pass, with the serial console tail as evidence (the
usual cause is a boot that stopped in emergency mode). Score = weight of passing checks ÷ total
weight. The lab is passed when the score reaches `pass_percent`.

---

## 6. `briefing.md`

What the learner reads when a lab opens. **Symptoms only, never causes.** It describes what
people report and what the system is supposed to do. It may state what a real admin would be told
(the root password, the expected hostname, the port a service should use). It never names the
file, unit, boolean or command involved.

---

## 7. `hints.yaml`

```yaml
checks:
  01_boots_clean:
    level_1: "The system did not reach a normal login. Something during boot gave up and waited."
    level_2: "When a filesystem in the boot sequence cannot be mounted, systemd stops and tells you
              which unit failed. Have you read what it said?"
    level_3: "Look at the mount unit that failed and compare its device reference against what the
              system can actually see."
    level_4: "The UUID in /etc/fstab does not match any device. Find the real one."
    refs:                                   # optional: reading, by level
      2: ["man 5 fstab", "journal:rhcsa-03-storage-and-lvm#fstab-and-what-systemd-does-with-it"]
      3: ["https://www.freedesktop.org/software/systemd/man/latest/systemd.mount.html"]
```

- Every check has exactly four levels, all non-empty.
- Level 1 restates the symptom. Level 2 names the **category** of tool or evidence. Level 3 narrows
  to the component. Level 4 names the problem. **No level names the command that fixes it**: the
  learner always types the fix.
- Levels 1 and 2 never name a path that the reference solution touches.
- The learner chooses the level (`h` on the lab's screen), never the tutor.
- `refs` (optional) maps a level to reading: `journal:<topic slug or lab id>#<anchor>`, where the
  anchor is a level 1–3 heading's id as the site renders it; `man <section> <page>`; or an
  `https://` URL. A level's reading is shown with that level and every later one, and all of it once
  the check passes. A reference never points into a journal's walkthrough section, and names the
  lab's own journal only from level 3.

---

## 8. Reference solution

- `solution/solution.sh` is a POSIX `sh` script, run as root in the guest by the solvability gate.
  It takes a broken lab to a fully passing state, including after the reboot.
- A lab with several base images may add `solution/<base_image>.sh`; the gate uses it instead of
  `solution.sh` on that image.
- The solution never reboots. If the fix needs a boot-time action (an SELinux relabel), the script
  arranges it and the grading reboot performs it.
- The TUI shows the solution **only** after the lab is passed or surrendered
  (`S`). The tutor never receives it. The review (`m`, the post-mortem) receives it only
  after the attempt is over.

---

## 9. Solvability gate

For every lab and every image in its `base_images`, starting from a clean snapshot:

1. apply the faults;
2. run every check — **each must fail** (a check that passes on a broken system tests nothing);
3. run the reference solution;
4. run the full grading sequence — **each check must pass, in every pass.**

For a `boot_after_break` lab, a second phase follows on a fresh VM, because the learner meets the
machine only after one more boot and a fault that does not survive that boot is gone before anyone
sees it (docs/open-questions.md Q18):

5. apply the faults and boot once more, exactly as the learner's machine does;
6. run every check again — **each must still fail.** When the broken machine has a network the
   checks run over SSH; when the boot stopped at a maintenance prompt they run over the serial
   console, in a root shell opened with the golden image's root password, with the runner shipped
   across in acknowledged chunks.

For a `container` lab the gate is steps 1–4 in a fresh container; there is no reboot pass.

`norboten dev validate <lab> [--image <id>]` runs the gate locally; `lab-validate.yml` runs it in CI.
A lab that fails the gate cannot merge.

A check that cannot fail before the fix is declared with `baseline_pass: true` and justified in a
YAML comment next to it. Steps 2 and 6 skip it.

A check that cannot fail while the machine sits at a maintenance prompt — because what it observes,
a running service or a mounted volume, does not exist before the boot completes — is declared with
`maintenance_pass: true` and justified in a YAML comment. Step 6 skips it only when the boot really
stopped at a maintenance prompt; if the broken machine comes up on the network, the check must fail
like any other. The fault behind such a check must reappear on the first boot that completes, and the
comment says how.

The solution never runs after the break boot: that boot may leave no network for it to arrive over
(Q14). The grading reboot in step 4 proves the fix survives a boot.

---

## 10. Packaging

A lab ships as an OCI image, `ghcr.io/<owner>/norboten-labs/<id>:<version>` (plus `:latest`), built
by `images/Dockerfile.lab`: `FROM scratch`, one layer holding the lab directory at `/lab`, OCI
labels for title, version and source. Nothing in it ever runs — Docker is the packaging and
distribution format: content-addressed, versioned, cacheable, and signed with cosign by
`lab-publish.yml`.

Pulling a lab (`u` in the Labs section) resolves the tag (skipping attestation manifests in an index), downloads the
last layer, verifies its digest, extracts only `lab/`, checks the manifest id, and stores it in
`~/.norboten/labs/<id>/<version>/`. A lab in a source checkout (or `NORBOTEN_LABS_DIR`) takes
precedence over the cache.

---

## 11. Static validation

`norboten dev lint [path…]` (also `make lint-labs` and the pre-commit hook) checks, without a VM:

- `lab.yaml` parses and satisfies section 2;
- the directory name equals `id`;
- every base image exists and serves the track;
- `check/` files and `checks:` match exactly, in order;
- `hints.yaml` has four non-empty levels for every check, and levels 1–2 name no path the
  solution touches; every `journal:` reference names an existing heading outside a walkthrough,
  and the lab's own journal only from level 3;
- `briefing.md` and `solution/solution.sh` exist; per-image solutions name listed images only;
- every `break/` module defines `apply(ctx)`, every `check/` module defines `check(ctx)`, and both
  import only the standard library, `norboten_runner`, and modules every one of the lab's images
  installs for its labs (`ubuntu-26.04-claude`: `claude_lab` and `fake_anthropic` from
  `/usr/local/lib/norboten`, and PyYAML).
- a rated lab (section 13) sits under `rated/`, sets `rated: true`, has a `collect/` module defining
  `collect(ctx)` for every check and a `check/` module defining `judge(facts, ctx)`; a collector
  never calls `ctx.passed`/`ctx.failed`, a judge imports nothing that reaches the system, and there
  is no `journal.md`. An unrated lab has no `collect/`.

---

## 12. Topics and rated attempts

A lab declares 1–5 `topics`. They are the axes a learner is rated on, the spokes of the profile
radar, and how the catalogue is filtered. The taxonomy is fixed and lives in
`cli/src/norboten/topics.py` — derived from EX200 and EX342, plus the automation subjects this
project adds:

| Group | Topics |
|---|---|
| system | `linux-basics`, `users-permissions`, `storage-lvm`, `boot-systemd` |
| network | `networking`, `firewall-selinux` |
| diagnostics | `kernel-performance`, `logging-journald`, `monitoring` |
| scripting | `bash`, `python` |
| automation | `ansible`, `terraform`, `containers` |
| ai | `ai-services`, `ai-agents`, `claude-code`, `ollama`, `mcp` |

Slugs are permanent: they are stored in ratings and appear in URLs, so renaming one is a migration.

An attempt is **rated** when it runs against the clock. The clock is `time_limit_minutes` when the
lab sets one, otherwise the minutes its difficulty buys:

| difficulty | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| minutes | 5 | 10 | 15 | 20 | 30 |

A rated attempt is one Glicko-2 game per topic the lab declares, against a virtual opponent whose
rating comes from the difficulty (1100, 1300, 1500, 1700, 1900 at deviation 75). Passing inside the
limit wins; failing, or running over, loses. **Only a rated lab (section 13) can be a rated
attempt:** an unrated lab is recorded on the profile and never moves a rating, however it was
started, because its checks and its answer are public.

---

## 13. Rated labs

A rated lab has the shape of any other lab, lives in the private repository (`rated/<track>/<id>/`,
docs/rated-labs.md) and sets `rated: true`. What changes is where each half of a check runs: **the
guest collects observations, the server judges them.** A check is split into two files with the
same stem:

```
<lab-id>/
├── collect/NN_name.py    # runs in the guest: what to look at
└── check/NN_name.py      # runs on the server: what counts as fixed
```

```python
# collect/02_notes_restarts_on_failure.py — observations only
def collect(ctx):
    r = ctx.run(["systemctl", "show", "-p", "Restart", "--value", "notes"])
    return {"restart": r.out.strip(), "code": r.code}
```

```python
# check/02_notes_restarts_on_failure.py — the criterion, never delivered
def judge(facts, ctx):
    if facts["restart"] in ("", "no"):
        return ctx.failed("When notes crashes, nothing brings it back.")
    return ctx.passed("systemd restarts notes when it dies.")
```

**`collect(ctx)`** gets the same `ctx` as a check (section 5) and follows the same rules: read-only,
under 30 seconds, the same imports. It returns a JSON object of at most 64 KiB — command output,
exit codes, file contents, an HTTP status and body. **It returns what it saw, never a verdict:** no
`ctx.passed`/`ctx.failed`, no comparison against the answer, no expected value. A reader of every
`collect/` file learns what is looked at and nothing about what is accepted; a collector that
could only be written by knowing the answer (a hash of the right config, say) is a lab bug. A
collector that raises is recorded as `{"collect_error": "…"}` and its check fails.

**`judge(facts, ctx)`** runs on the server — and in the gate, on the host. `facts` is exactly what
the collector returned. `ctx` carries `phase`, `base` (the image facts: `id`, `init`, `pkg`,
`mac`), `state` (the break scripts' `ctx.state`, collected with the facts) and `passed(message,
evidence="")` / `failed(…)`. A judge is a pure function: standard library only, and no
`subprocess`, `socket`, `os`, file or network access — the linter refuses those imports. Its
message and evidence stay on the server; the learner is told pass or fail per check, and the
objective it belongs to.

### The attempt

```
TUI                         API (holds check/, solution/)            guest
 R ─ POST /rated/attempts ─▶ attempt id, nonce, key, break bundle
   ─────────────────────────────────────────────────────────────────▶ break/ applied, deleted
   … the learner works; no checks, hints, tutor or solution are on this machine …
 c ─ GET …/collect ────────▶ collect bundle
   ─────────────────────────────────────────────────────────────────▶ collect/ runs, record signed
   ◀────────────────────────────────────────────────────────────────── {record, signature}
   ─ POST …/facts ─────────▶ verify, store the pre_reboot record
   reboot; collect again; POST …/facts ─▶ verify boot, judge both passes, rate
```

- **The bundles.** The break bundle holds `lab.yaml`, `break/` and `files/`; the collect bundle
  holds `lab.yaml`, `collect/` and `files/`. The client adds its own `norboten_runner`, injects the
  bundle into `/run/norboten` exactly as for an unrated lab, and deletes it after the run. Neither is
  written to `~/.norboten`; `check/`, `solution/` and `hints.yaml` never leave the server.
- **The record.** `norboten_runner.collect_runner` runs every collector and prints one record:
  `{attempt, nonce, phase, boot_id, collected_at, base, state, facts: {check_id: {…}}}`. It signs
  the record's canonical JSON (sorted keys, no whitespace) with HMAC-SHA256 under the attempt key,
  which it reads on stdin, and prints `{record, signature}`.
- **What the server accepts.** A record whose signature verifies under that attempt's key, whose
  nonce and attempt match, for an attempt that is still open, once per phase. For a
  `reboot_required` lab the `post_reboot` record must carry a different `boot_id` from the
  `pre_reboot` one and a later `collected_at` — that is the reboot proof. A lab without a reboot is
  judged on its one record.
- **The verdict.** Section 5's grading sequence, computed on the server from the judges: a check
  passes only if it passes in every pass; score and `pass_percent` as usual. The clock runs from
  the moment the attempt was issued to the moment the server received the first record, against
  the lab's rated minutes (section 12). The attempt is then closed and rated.
- **One attempt at a time.** Starting a rated attempt closes any open one for the same account as
  a loss, and an attempt not finished within three times its clock (at least an hour) expires as a
  loss. So does giving up (`S`). Otherwise seeing the faults and walking away would cost nothing.
- **What a rated attempt does not have.** No live checks and no quick check (each would be a
  grading oracle), no hints, no tutor and no reference solution, no reset (start again with `R`,
  which closes this attempt), and no public journal (a journal walks the same failure).

What this defends against, and what it does not, is in docs/rated-labs.md: the key and the
collectors are on the learner's own machine, so the signature proves a record belongs to this
attempt and was not replayed from another — not that a determined learner did not forge it.
