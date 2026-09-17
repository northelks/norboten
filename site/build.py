"""Build norboten.org into site/dist.

Everything on the site comes from the repository: the lab catalogue is read from labs/, the
theory topics from quizzes/ and each lab's theory.yaml, and the documentation from docs/*.md.
Nothing is duplicated by hand, so a lab that changes changes the site.

    uv run python site/build.py [--out site/dist]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt
from markupsafe import Markup, escape
from mdit_py_plugins.anchors import anchors_plugin

from norboten.labs.store import all_labs
from norboten.quiz import bank as banks

sys.path.insert(0, str(Path(__file__).resolve().parent))
import graphics  # the site's own module, next to this file

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
GITHUB = "https://github.com/northelks/norboten"
API = os.environ.get("NORBOTEN_SITE_API", "https://api.norboten.org")  # a local stack overrides it
# The donate page's tiles, in euros. The API validates the same amounts (routers/donate.py).
DONATION_TIERS = (5, 10, 15, 20, 25, 50)
DONATION_DEFAULT = 10
DOMAIN = "norboten.org"
SITE_URL = os.environ.get("NORBOTEN_SITE_URL", f"https://{DOMAIN}")  # where install.sh is served
# A GA4 measurement ID (G-…) turns the analytics tag on for this build. Empty — the default,
# and what a self-hosted build gets — ships no script and sets no cookie.
GA_ID = os.environ.get("NORBOTEN_SITE_GA_ID", "")
# The About page's "More about me" button and the Community page's "Join the Discord" button: each
# is hidden while its link is empty.
# A preview may point these anywhere; a fork empties them and the buttons that use them disappear.
PERSONAL_SITE = os.environ.get("NORBOTEN_SITE_PERSONAL_URL", "https://iharpetushkou.com")
# The invite is public by nature; a self-hosted build points it at its own server, or empties it.
DISCORD_INVITE = os.environ.get("NORBOTEN_SITE_DISCORD_INVITE", "https://discord.gg/2zF4UuZaJB")
# The Community page draws the server it describes: the channels as they exist in Discord. Change
# them here and in Discord together, or the page sends people to a channel that is not there.
CHANNELS = (
    (
        "Start here",
        (
            ("announcements", "The bot posts every new lab, journal and bank, and every release."),
            ("general", "Anything Norboten, and introducing yourself if you feel like it."),
        ),
    ),
    (
        "The labs",
        (
            ("stuck", "A lab that will not pass. Symptoms and commands, not finished solutions."),
            ("linux", "The linux and rhcsa tracks: systemd, storage, SELinux, networking, boot."),
            (
                "scripting",
                "The bash and python tracks, and tooling you write for your own machines.",
            ),
            ("devops", "Docker, Terraform and Ansible: the labs where the fault is in the config."),
            ("ai", "The claude, mcp and automation tracks — agents, MCP servers, local models."),
        ),
    ),
    (
        "Beyond the labs",
        (
            ("theory", "The question banks and the journals: what an answer really means."),
            ("writing-labs", "Writing your own lab or bank, and the plugin that drafts one."),
            ("ratings", "The board, streaks, and what your number did this week."),
            ("bugs-and-ideas", "A check that is wrong, a briefing that misleads, the next lab."),
        ),
    ),
)

# Moves whenever the privacy policy says something new (site/templates/privacy.html).
PRIVACY_UPDATED = "17 September 2026"

DOC_TREE = [
    (
        "Getting started",
        [
            ("getting-started", "Install and first lab", "docs/getting-started.md"),
            ("tui-reference", "TUI reference", "docs/tui-reference.md"),
            ("faq", "FAQ", "docs/faq.md"),
        ],
    ),
    (
        "Contributing labs",
        [
            ("writing-a-lab", "Writing a lab", "docs/writing-a-lab.md"),
            ("lab-spec", "Lab specification", "docs/lab-spec.md"),
            ("quiz-spec", "Theory question spec", "docs/quiz-spec.md"),
            ("claude-code-plugin", "The Claude Code plugin", "docs/claude-code-plugin.md"),
        ],
    ),
    (
        "How it is built",
        [
            ("architecture", "Architecture", "docs/architecture.md"),
            ("rated-labs", "Rated and unrated labs", "docs/rated-labs.md"),
            (
                "claude-code-in-norboten",
                "How Norboten uses Claude",
                "docs/claude-code-in-norboten.md",
            ),
            ("mcp", "The MCP server", "docs/mcp.md"),
            ("data-model", "Data model", "docs/data-model.md"),
            ("api-reference", "API reference", "docs/api-reference.md"),
            ("pipelines", "Pipelines", "docs/pipelines.md"),
            ("open-questions", "Open questions", "docs/open-questions.md"),
        ],
    ),
    (
        "Running it yourself",
        [
            ("self-hosting", "Self-hosting and configuration", "docs/self-hosting.md"),
            ("deploy", "Deploying the server", "docs/deploy.md"),
            ("ci-cd", "CI/CD", "docs/ci-cd.md"),
            ("releasing", "Releasing", "docs/releasing.md"),
        ],
    ),
]

HIGHLIGHTS = [
    {
        "title": "A real virtual machine",
        "body": "QEMU through Lima, a real kernel, real LVM, real SELinux. Root recovery from the "
        "bootloader and a fix that has to survive a reboot are impossible in a container, so "
        "Norboten does not pretend otherwise.",
    },
    {
        "title": "Graded by machine state",
        "body": "No answer box. Check scripts run as root inside the guest and report what they "
        'observed — "nothing is listening on port 8090", not "wrong".',
    },
    {
        "title": "The reboot check",
        "body": "Every VM lab is checked, rebooted, and checked again. A fix that works until the "
        "next boot is not a fix, and this is the single detail most practice platforms skip.",
    },
    {
        "title": "A tutor that will not tell you",
        "body": "It sees the same evidence you do, never the solution, and points at the tool you "
        "have not used yet — on your own Claude Code, key or Ollama. You choose when the hints get "
        "more specific.",
    },
    {
        "title": "Proven solvable in CI",
        "body": "Every lab, on every base image it supports, must break every check and then be "
        "fixed by its own reference solution — or it cannot merge.",
    },
    {
        "title": "Yours, offline, and removable",
        "body": "Images and labs are cached locally; no host directory is ever mounted into a lab "
        "VM; everything lives under ~/.norboten and deleting it leaves nothing behind.",
    },
]

FEATURE_GROUPS = [
    {
        "kicker": "Labs and grading",
        "capture": "tui-check",
        "beside": 1,
        "title": "The part that decides whether you learned it",
        "blurb": "A lab is a directory of faults, checks, hints and a reference solution. The "
        "grading is the product.",
        "features": [
            {
                "title": "Checks that observe, not compare",
                "body": "Each check runs in the guest and returns pass/fail with a message written "
                "for someone who just failed, plus raw evidence you can read.",
                "detail": "docs/lab-spec.md §5",
            },
            {
                "title": "Check → reboot → check",
                "body": "Both passes must pass. If the machine never comes back, every check fails "
                "with the serial console tail as evidence.",
            },
            {
                "title": "Partial scores per objective",
                "body": "Weighted checks map to the exam's own objectives, so a score says which "
                "skill is missing, not just how far off you were.",
            },
            {
                "title": "Reset in about ten seconds",
                "body": "A disk snapshot taken before the faults, restored and cold-booted, "
                "with the faults re-applied.",
                "detail": "Alpine 9.8 s · Rocky 9.9 s",
            },
            {
                "title": "A console when there is no network",
                "body": "`k` on a lab attaches to the guest's serial port — the only way into a "
                "machine that stopped in emergency mode, which is where lab 3 starts. `b` presses "
                "reset and lands you in the bootloader.",
            },
            {
                "title": "Timed exam simulation",
                "body": "Ninety minutes, fifteen tasks, a 70% pass line, an unknown root password and "
                "no sudo — recovery from the bootloader, relabel included.",
            },
        ],
    },
    {
        "kicker": "The engine",
        "capture": "tui-system",
        "beside": 2,
        "title": "What runs the machines",
        "blurb": "Pinned, reproducible, and built so that a broken guest cannot break grading.",
        "features": [
            {
                "title": "Golden images, built by Ansible",
                "body": "The distribution's own cloud image plus every package the track needs, a "
                "serial console, a persistent journal and per-command shell history.",
                "detail": "rocky-10 · alpine · ubuntu-26.04 · ubuntu-26.04-automation · ubuntu-26.04-devops",
            },
            {
                "title": "A pinned Lima and QEMU",
                "body": "Norboten downloads and checksums its own Lima into ~/.norboten rather than "
                "using whatever the machine happens to have.",
            },
            {
                "title": "A runner with no dependencies",
                "body": "The code injected into a guest is standard-library Python. Nothing is ever "
                "installed inside a lab VM.",
            },
            {
                "title": "A separate grading account",
                "body": "Checks run as norboten-grader, not as you — so a lab can take your sudo away "
                "(and you can break your own) without breaking the grader.",
            },
            {
                "title": "Offline once cached",
                "body": "Images and labs are content-addressed and cached; Norboten needs the "
                "network only to fetch them and to show the boards; the tutor runs on your own model.",
            },
            {
                "title": "Nothing of yours inside",
                "body": "No host mounts, no port forwarding, no SSH agent forwarding. The VM sees "
                "your public key and nothing else.",
            },
        ],
    },
    {
        "kicker": "Interface",
        "capture": "tui-lab",
        "beside": 1,
        "title": "A terminal that keeps up with you",
        "blurb": "norboten opens one full-screen interface. Everything a learner does is a key in "
        "it, and doctor has already checked the machine by the time the first screen draws.",
        "features": [
            {
                "title": "Eight sections, eight keys",
                "body": "Home, Labs, Theory, Journals, Play, Ratings, You and System along the top, on "
                "`1` to `8` or the arrows, with the account, doctor and the running lab VMs always "
                "in view. `Ctrl+P` lists what the app can do.",
            },
            {
                "title": "Every lab action on a key",
                "body": "`s` starts, `o` opens a shell, `w` watches the checks, `c` checks and reboots, "
                "`h` hints, `t` asks the tutor, `k` and `b` open the consoles — and the VM work "
                "runs in the "
                "background while the screen stays live.",
            },
            {
                "title": "Live check panel",
                "body": "Work in one terminal, watch the checks turn green in another. A change shows "
                "up in about two seconds.",
                "detail": "measured: 2.0 s",
            },
            {
                "title": "Hint ladder, four levels",
                "body": "Symptom, then the kind of evidence, then the component, then the problem — "
                "and never the command. You decide when to go deeper.",
            },
            {
                "title": "Session timer",
                "body": "Counts up, or down for the timed exam simulation, where being over the limit "
                "is a fail.",
            },
            {
                "title": "Theory in the same place",
                "body": "Each lab has a Theory tab; topics have their own trainer with explanations "
                "and references after every answer.",
            },
        ],
    },
    {
        "kicker": "Theory and AI",
        "capture": "tui-quiz",
        "beside": 2,
        "title": "Questions that had to earn their place",
        "blurb": "A wrong question teaches a wrong thing, so the pipeline is stricter than the "
        "writing.",
        "features": [
            {
                "title": "Executable verification",
                "body": "A question about what a snippet prints carries the snippet. It runs in a "
                "container with no network before the question is accepted.",
                "detail": "{verified} of the repo's own questions are executed",
            },
            {
                "title": "Blind cross-model solving",
                "body": "At least two models that never saw the key must answer exactly the key, and "
                "neither may call the question ambiguous.",
            },
            {
                "title": "A critic, then a duplicate check",
                "body": "One model reviews for a second defensible answer or a wrong fact; the "
                "prompt is then compared against every question already in the banks.",
            },
            {
                "title": "Drafted locally, read by a person",
                "body": "Questions are drafted on a Claude subscription, off the server, with who "
                "wrote each, who solved it blind and what the snippet printed. A maintainer reads "
                "every draft before it joins a bank; `g` on Theory drafts practice ones for yourself.",
            },
        ],
    },
    {
        "kicker": "Journals",
        "capture": "tui-journals",
        "beside": 1,
        "title": "The reading, checked against a machine",
        "blurb": "A journal is what a good colleague would explain after the lab: how the thing "
        "works, and how it goes wrong.",
        "features": [
            {
                "title": "Six sections, every time",
                "body": "The mechanism, a failure walked through, the wrong turns people take, a "
                "cheat sheet, and review questions with their answers.",
            },
            {
                "title": "Every walkthrough replayed",
                "body": "Each walkthrough was run on a real lab VM, and the console output in it is "
                "what the machine printed. Where something was not captured, it says so.",
            },
            {
                "title": "In the terminal, on the site, on paper",
                "body": "`4` reads them in the TUI; the site renders them; `e` writes a PDF with a "
                "light page, running headers and page numbers.",
            },
            {
                "title": "The consultant reads them — carefully",
                "body": "Journals are searchable by the site's consultant, except the walkthrough, "
                "which is the fix for that lab's machine.",
            },
        ],
    },
    {
        "kicker": "Play",
        "capture": "tui-play",
        "beside": 1,
        "title": "Watch the work, not a screenshot of it",
        "blurb": "A recording of someone fixing a machine says more than any feature list. So the "
        "terminal is recordable, and the recording is honest.",
        "features": [
            {
                "title": "A real pseudo-terminal",
                "body": "The shell runs in a PTY and we copy bytes both ways. Pipes, editors, "
                "less, tab completion and colour all record correctly, because nothing "
                "interprets them.",
                "detail": "asciicast v2 — asciinema plays it too",
            },
            {
                "title": "Commands and diffs, side by side",
                "body": "What was typed is logged; what it changed is a diff, taken by keeping "
                "the guest's /etc under git for the session. The replay shows both.",
            },
            {
                "title": "Live, with a blinking dot",
                "body": "`P` on a lab publishes the session while it runs. Viewers get server-sent "
                "events and a read-only terminal.",
            },
            {
                "title": "A player written here",
                "body": "A screen buffer, the escape sequences a shell actually emits, and a "
                "clock — one file, no dependency, no framework.",
            },
            {
                "title": "Recording is opt-in twice",
                "body": "`o` records nothing. `p` writes to your own machine. Only `P` publishes, "
                "after asking, and recordings expire after a week.",
            },
            {
                "title": "Theory is never recorded",
                "body": "Answers and scores only. There is no terminal to record and no reason "
                "to keep one.",
            },
        ],
    },
    {
        "kicker": "Ratings and profiles",
        "capture": "tui-you",
        "beside": 1,
        "title": "A number that admits what it does not know",
        "blurb": "Optional, and off the critical path: everything works signed out. What an "
        "account adds is a measurement you can argue with.",
        "features": [
            {
                "title": "Glicko-2, per topic",
                "body": "Fifteen topics from the EX200 and EX342 objectives plus the automation "
                "subjects. Every rating carries its deviation, so a new profile reads 1500 ± 350 "
                "instead of pretending to be precise.",
                "detail": "docs/lab-spec.md §12",
            },
            {
                "title": "The lab is the opponent",
                "body": "Difficulty 1 to 5 plays at 1100 to 1900. Passing inside the clock wins; "
                "failing, or running over, loses. Beating a hard lab is worth what it should be.",
            },
            {
                "title": "The clock is part of the result",
                "body": "5, 10, 15, 20 or 30 minutes by difficulty, unless the lab sets its own. "
                "An unrated lab is recorded and never rated — retry it as often as you like.",
                "detail": "only a rated lab, judged on the server, moves the rating",
            },
            {
                "title": "A profile drawn from the work",
                "body": "A radar of the nineteen topics, a year-long contribution heatmap, and the "
                "history with what each attempt did to the rating — all SVG this repository "
                "generates itself.",
            },
            {
                "title": "Sign-in that holds no secret",
                "body": "GitHub, and nothing else — no password to steal and no email kept, on "
                "the site or in the terminal. The GitHub token is revoked the moment it has said "
                "who you are. A remembered machine keeps Norboten's token at mode 0600 for ninety "
                "days; an unremembered one never writes it down at all.",
            },
            {
                "title": "The server decides what an attempt was worth",
                "body": "Difficulty, topics and the time limit are read from the lab manifest, "
                "never from the request. A client cannot pick an easy opponent.",
            },
        ],
    },
    {
        "kicker": "For lab authors",
        "title": "Writing a lab is a pull request",
        "blurb": "The format is small enough to hold in your head, and the gate tells you the "
        "truth before a reviewer has to.",
        "features": [
            {
                "title": "One directory, six things",
                "body": "A manifest, a briefing that states symptoms only, break scripts, check "
                "scripts, a hint ladder and a reference solution.",
            },
            {
                "title": "Validated without a VM",
                "body": "norboten dev lint checks the manifest, the hint ladder, the objective mapping "
                "and that guest scripts import nothing but the standard library.",
            },
            {
                "title": "Then validated with one",
                "body": "norboten dev validate runs the whole gate locally, on each base image the lab "
                "claims to support.",
            },
            {
                "title": "Shipped as an OCI artifact",
                "body": "Labs are built from images/Dockerfile.lab, pushed to GHCR and signed with "
                "cosign; `u` in the Labs section pulls and verifies one.",
            },
        ],
    },
    {
        "kicker": "Self-hosting",
        "title": "Run the whole thing yourself",
        "blurb": "The server side is one machine and one Docker Compose project, described in code "
        "and rehearsed on a laptop before it touches a server.",
        "features": [
            {
                "title": "One server, not a cloud",
                "body": "One netcup VPS, ordered by hand and bootstrapped by Ansible. No managed "
                "services, no Kubernetes: learners' VMs run on learners' machines, so the server "
                "carries accounts, text and a small model.",
                "detail": "ansible/playbooks/bootstrap.yml · 2 vCPU, 4 GB",
            },
            {
                "title": "Ansible for the host, Compose for the rest",
                "body": "Firewall, unattended upgrades, keys-only SSH, Docker; then Caddy, the API, "
                "PostgreSQL, Redis, Ollama, Prometheus and Grafana as one compose project.",
            },
            {
                "title": "Deploy on push, roll back on its own",
                "body": "A push to main tests against real PostgreSQL and Redis, builds the image "
                "and the site, and runs deploy.sh — which goes back to the previous tag if the "
                "new one does not report ready.",
            },
            {
                "title": "Backups that are restore-tested",
                "body": "The nightly job restores the dump it just took into a scratch database and "
                "counts rows before it keeps it, then copies it off the box with restic.",
            },
            {
                "title": "The whole stack on a laptop",
                "body": "make stack-up runs the production compose project locally with sample "
                "data; make server-rehearsal runs the production playbook against an Ubuntu VM.",
            },
        ],
    },
]

LIFECYCLE = [
    {"n": "01", "key": "u", "title": "Pull", "note": "by digest", "accent": False},
    {"n": "02", "key": "s", "title": "Boot", "note": "cloud-init, grader", "accent": False},
    {"n": "03", "key": "", "title": "Snapshot", "note": "clean, VM stopped", "accent": True},
    {"n": "04", "key": "", "title": "Break", "note": "the faults applied", "accent": False},
    {"n": "05", "key": "o k b h t", "title": "Work", "note": "shell · hints", "accent": False},
    {"n": "06", "key": "c", "title": "Check", "note": "twice, with reboot", "accent": True},
]

GATE = [
    {"title": "Clean VM", "note": "from the golden image", "accent": False},
    {"title": "Apply faults", "note": "the lab's break scripts", "accent": False},
    {"title": "All must fail", "note": "or it tests nothing", "accent": True},
    {"title": "Reference fix", "note": "the lab's own solution", "accent": False},
    {"title": "All must pass", "note": "and after a reboot", "accent": True},
]

PIPELINE = [
    {"title": "Generate", "note": "one model writes it", "reject": ""},
    {"title": "Schema", "note": "the spec, checked", "reject": "rejects malformed"},
    {
        "title": "Solve blind",
        "note": "two other models",
        "reject": "rejects a mismatch",
        "accent": True,
    },
    {"title": "Critic", "note": "a second answer?", "reject": "rejects ambiguity"},
    {
        "title": "Execute",
        "note": "no network",
        "reject": "rejects wrong keys",
        "accent": True,
    },
    {"title": "Dedup", "note": "against the banks", "reject": "rejects repeats"},
]

DECISIONS = [
    {
        "title": "Disk snapshots, not memory snapshots",
        "body": "QEMU can save a running machine's memory, which would make a reset instant. On "
        "Apple Silicon it also breaks the next reboot: after savevm the guest hangs in UEFI at "
        "100% CPU, and starting QEMU with -loadvm aborts outright. Norboten snapshots the disk and "
        "cold-boots instead, and the golden images are tuned to make that fast.",
        "measured": "reset 9.8–9.9 s on all three images",
    },
    {
        "title": "A grading account, separate from yours",
        "body": "The exam simulation takes your sudo away — that is the point of it. Everything "
        "that grades you therefore runs as its own account with its own key, so a lab can remove "
        "your privileges, and you can break your own sudo, without breaking the grader.",
    },
    {
        "title": "Boot speed is a feature",
        "body": "Every second of boot is paid on every reset. The baseline removes what blocks a "
        "lab VM's boot: cloud-init datasource probing, a chrony step that waits for NTP, dhcpcd's "
        "ARP probe, and a ten-second bootloader menu.",
        "measured": "Alpine boot 22 s → 7 s",
    },
    {
        "title": "Poll SSH instead of waiting for Lima",
        "body": "Lima makes one SSH attempt as QEMU starts, and slirp then retransmits its SYN "
        "with exponential backoff while the guest boots — so it reports ready long after the "
        "machine is. Norboten polls with fresh short connections instead.",
        "measured": "Rocky reset 19.7 s → 9.9 s",
    },
    {
        "title": "The quick check can never pass a lab",
        "body": "The quick check (x) is feedback while you work. It reports every check and refuses "
        "to mark the lab passed, because the reboot is the part that proves the fix.",
    },
    {
        "title": "The tutor cannot leak what it never had",
        "body": "The solution is not in the tutor's request model, so no prompt injection can "
        "extract it. A separate guard then compares the reply against the solution and the hint "
        "level, and logs every block. The consultant's replies go through the same guard.",
        "measured": "31 guard tests, adversarial replies included",
    },
    {
        "title": "One server, no Kubernetes",
        "body": "Hosted lab VMs would need /dev/kvm, which a cloud VPS does not offer, and without "
        "them the server carries accounts, text and a small model. One machine and a compose file "
        "cost a few euros a month, can be rehearsed on a laptop, and fail in ways one person can "
        "read.",
    },
    {
        "title": "BM25, not a vector database",
        "body": "The consultant's corpus is a few hundred passages whose useful words are exact "
        "commands and file names. Lexical ranking finds those better than embeddings, needs no "
        "model to index, runs identically in the browser as a fallback, and every score can be "
        "explained.",
    },
    {
        "title": "GitHub is the only way in",
        "body": "No password column, no email and no registration: the first sign-in with a GitHub "
        "account makes the Norboten account, keyed by GitHub's user id. The terminal's device flow "
        "goes through the API, so no GitHub token reaches a learner's machine and none is stored "
        "anywhere. The cost is plain — no GitHub account, no sign-in — and only ratings need one.",
    },
    {
        "title": "A column that holds data is never dropped",
        "body": "The schema is idempotent SQL applied on start, and no migration renames a column or "
        "drops one that holds data. An older API image therefore runs against a newer database, "
        "which is what makes deploy.sh's automatic rollback safe to do without a person. The one "
        "exception is before any account existed: the password and email columns of the earlier "
        "sign-ins went on 2026-09-16.",
    },
]

#: The stack page's table, one group per layer. Versions are what the lockfile, the registry and
#: the compose file pin; a bump there should be a bump here.
STACK = [
    {
        "layer": "The client",
        "rows": [
            {
                "tech": "Python",
                "version": "≥ 3.12",
                "job": "The TUI, the engine, the recorder, the lab tooling.",
                "why": "What administrators already have; the runner can share its models.",
                "where": "cli/",
            },
            {
                "tech": "Textual",
                "version": "8.2",
                "job": "The whole interface: sections, the lab screen, modals, the activity log.",
                "why": "A real layout engine in a terminal, testable headless with its pilot.",
                "where": "cli/src/norboten/tui",
            },
            {
                "tech": "pyte",
                "version": "0.8",
                "job": "Emulates a terminal screen for the in-TUI player and the captures.",
                "why": "A VT100 screen buffer in pure Python.",
                "where": "tui/widgets.py",
            },
            {
                "tech": "Typer",
                "version": "0.27",
                "job": "The hidden dev and image commands for authors and CI.",
                "why": "Commands from type hints; the learner never needs it.",
                "where": "cli/src/norboten/cli.py",
            },
            {
                "tech": "Pydantic",
                "version": "2.13",
                "job": "Lab manifests, question banks, reports — shared with the API.",
                "why": "One schema, validated on both sides and exported as JSON Schema.",
                "where": "cli/src/norboten/models.py",
            },
            {
                "tech": "httpx",
                "version": "0.28",
                "job": "Calls to the API, signing in, streaming uploads.",
                "why": "Timeouts and streaming without ceremony.",
                "where": "tui/data.py, auth.py",
            },
        ],
    },
    {
        "layer": "The machines",
        "rows": [
            {
                "tech": "Lima",
                "version": "2.2.0",
                "job": "Renders and runs one VM per lab; downloaded and checksummed by Norboten.",
                "why": "QEMU with cloud-init and SSH solved, on macOS and Linux alike.",
                "where": "cli/src/norboten/lima",
            },
            {
                "tech": "QEMU",
                "version": "HVF / KVM",
                "job": "Real kernels, real boots, serial consoles, QMP reset, qemu-img snapshots.",
                "why": "A container cannot fail to boot, and failing to boot is a lab.",
                "where": "lima/snapshot.py",
            },
            {
                "tech": "Rocky 10 · Ubuntu 26.04 (+ automation, + devops) · Alpine · containers",
                "version": "by digest",
                "job": "The golden base images the labs run on.",
                "why": "The distributions the exams and jobs use, from their own cloud images.",
                "where": "images/registry.yaml",
            },
            {
                "tech": "Ansible",
                "version": "core",
                "job": "The baseline role that turns a cloud image into a golden image.",
                "why": "The same tool configures the server; readable by the people it teaches.",
                "where": "ansible/roles/lab_baseline",
            },
            {
                "tech": "The runner",
                "version": "stdlib only",
                "job": "Applies faults, runs checks, collects facts inside the guest.",
                "why": "Nothing may be installed in a lab VM.",
                "where": "runner/norboten_runner",
            },
        ],
    },
    {
        "layer": "The server",
        "rows": [
            {
                "tech": "FastAPI + uvicorn",
                "version": "0.141 · 0.52",
                "job": "Auth, attempts, ratings, the consultant, live sessions, metrics.",
                "why": "Async for SSE, Pydantic models shared with the client, OpenAPI for free.",
                "where": "api/src/norboten_api",
            },
            {
                "tech": "PostgreSQL",
                "version": "17",
                "job": "Every durable table.",
                "why": "One database that does arrays, JSON and advisory locks; pgvector if ever needed.",
                "where": "api/…/db.py",
            },
            {
                "tech": "SQLAlchemy + asyncpg",
                "version": "2.0 · 0.31",
                "job": "The async connection pool; queries are plain SQL.",
                "why": "A pool and a driver without an ORM between the SQL and the reader.",
                "where": "api/…/db.py",
            },
            {
                "tech": "Redis",
                "version": "7.4 · redis-py 8.1",
                "job": "Pub/sub for live frames, rate limits, a 30 s cache.",
                "why": "Crosses worker processes; nothing in it needs to survive.",
                "where": "api/…/live.py",
            },
            {
                "tech": "GitHub OAuth · Discord REST",
                "version": "device and web flows · API v10",
                "job": "Who someone is, once; and the weekly digest as a Discord direct message.",
                "why": "No password or email to keep; a bot message needs no gateway connection.",
                "where": "api/…/github.py, discord.py",
            },
            {
                "tech": "Ollama",
                "version": "0.34 · qwen2.5:0.5b",
                "job": "The server's only model, the consultant's; the tutor's last choice on a "
                "learner's machine; and four automation labs' subject.",
                "why": "No key, no bill, nothing leaves the server.",
                "where": "norboten/questions/providers.py",
            },
            {
                "tech": "Claude Code · OpenAI · Gemini",
                "version": "local, optional keys",
                "job": "Drafting theory questions and their blind verification, off the server.",
                "why": "A subscription serves its owner; other vendors make blind solving stronger.",
                "where": "norboten/questions/",
            },
            {
                "tech": "Caddy",
                "version": "2.10",
                "job": "TLS, the static site, the reverse proxy, unbuffered SSE.",
                "why": "Certificates with no cron and no certbot; a config that fits on a screen.",
                "where": "deploy/Caddyfile",
            },
            {
                "tech": "Docker Compose",
                "version": "v2",
                "job": "The whole server as one project, locally and in production.",
                "why": "The same file on a laptop and a server; nothing to operate.",
                "where": "deploy/compose.yaml",
            },
            {
                "tech": "Claude Code",
                "version": "2.1.270",
                "job": "Issue triage, stuck-point summaries, release notes, lab drafts — and the "
                "claude track's subject.",
                "why": "Headless runs with turn caps and tool lists, rehearsed against a scripted API.",
                "where": "automation/jobs",
            },
            {
                "tech": "Prometheus + Grafana",
                "version": "3.5 · 12.1",
                "job": "Request rate and latency by route, host and database health, dashboards.",
                "why": "The standard pair; exporters for the host and PostgreSQL exist already.",
                "where": "deploy/prometheus.yml",
            },
        ],
    },
    {
        "layer": "Data and the site",
        "rows": [
            {
                "tech": "pandas",
                "version": "3.0",
                "job": "Frames from the attempts table for every chart.",
                "why": "Group-bys and cohorts in a few lines.",
                "where": "api/…/analytics",
            },
            {
                "tech": "scikit-learn",
                "version": "1.9",
                "job": "TF-IDF relations between labs, banks, journals; k-means on ratings.",
                "why": "Deterministic and explainable, no service to run.",
                "where": "analytics/relations.py",
            },
            {
                "tech": "networkx · matplotlib",
                "version": "3.6 · 3.11",
                "job": "The relation graph; every chart, rendered to SVG in the site's palette.",
                "why": "Static SVG needs no JavaScript and prints.",
                "where": "analytics/figures.py",
            },
            {
                "tech": "Jinja · markdown-it · Pygments",
                "version": "3.1 · 4.2 · 2.21",
                "job": "The static site: pages, docs, journals, highlighted code.",
                "why": "A site is files; nothing to run but Caddy.",
                "where": "site/build.py",
            },
            {
                "tech": "JavaScript, no framework",
                "version": "—",
                "job": "The terminal player, live viewer, profile, consultant fallback.",
                "why": "A screen buffer and a clock are one file each.",
                "where": "site/static",
            },
        ],
    },
    {
        "layer": "Delivery",
        "rows": [
            {
                "tech": "GitHub Actions",
                "version": "—",
                "job": "Tests, the solvability gate, question verification, publish, deploy.",
                "why": "Where the pull requests are.",
                "where": ".github/workflows",
            },
            {
                "tech": "GHCR · OCI · cosign",
                "version": "—",
                "job": "The API image, golden images, labs as signed artifacts.",
                "why": "Content-addressed: a client gets exactly what CI published, or nothing.",
                "where": "images/Dockerfile.lab",
            },
            {
                "tech": "Ansible",
                "version": "core",
                "job": "Hardening, Docker, the compose project, timers, secrets from the vault.",
                "why": "Idempotent, agentless, and rehearsable against a local VM.",
                "where": "ansible/playbooks/server.yml",
            },
            {
                "tech": "restic",
                "version": "optional",
                "job": "Off-box copies of the nightly, restore-checked dumps.",
                "why": "Encrypted, deduplicated, any S3-compatible target.",
                "where": "deploy/backup.sh",
            },
            {
                "tech": "uv · ruff · pytest",
                "version": "—",
                "job": "The workspace, the lockfile, lint and format, about 480 tests.",
                "why": "One fast tool per job.",
                "where": "pyproject.toml",
            },
        ],
    },
]


#: Fence names the journals use, mapped to Pygments lexers; anything else stays plain text.
LEXERS = {"console": "console", "sh": "bash", "bash": "bash", "shell": "bash", "ini": "ini",
          "yaml": "yaml", "python": "python", "nginx": "nginx", "hcl": "terraform",
          "json": "json", "jinja": "jinja", "diff": "diff"}  # fmt: skip


def highlight(code: str, lang: str, _attrs) -> str:
    """Syntax colour for a fenced block, as classes the site's stylesheet colours."""
    from pygments import highlight as pyg
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound

    name = LEXERS.get((lang or "").strip().lower())
    if not name:
        return ""  # markdown-it escapes and wraps it itself
    try:
        lexer = get_lexer_by_name(name, stripnl=False)
    except ClassNotFound:
        return ""
    body = pyg(code, lexer, HtmlFormatter(nowrap=True, classprefix="hl-"))
    return f'<pre class="hl"><code class="language-{lang}">{body}</code></pre>\n'


def markdown() -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": True, "typographer": True, "highlight": highlight},
    )
    md.enable(["table", "strikethrough"])
    return md.use(anchors_plugin, max_level=3, permalink=False)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def headings(html: str) -> list[dict]:
    out = []
    for level, anchor, text in re.findall(r'<h([23]) id="([^"]+)"[^>]*>(.*?)</h[23]>', html, re.S):
        out.append({"level": f"h{level}", "id": anchor, "text": re.sub(r"<[^>]+>", "", text)})
    return out


#: Keys with a name rather than a letter. Anything else of one character is a key too.
_NAMED_KEYS = frozenset(
    {"Enter", "Esc", "Tab", "Space", "Ctrl", "Shift", "Alt", "↑", "↓", "←", "→"}
)


def keycaps(text: str) -> Markup:
    """`c` in the copy is a key on the keyboard, so it is drawn as one; longer spans stay code.

    The TUI is keys all the way down, and a bare letter in a sentence ("P publishes the session")
    disappears into the sentence. One filter, so every page draws them the same way.
    """

    def one(match: re.Match[str]) -> str:
        inner = match.group(1)
        tag = "kbd" if len(inner) == 1 or inner in _NAMED_KEYS else "code"
        return f"<{tag}>{escape(inner)}</{tag}>"

    return Markup(re.sub(r"`([^`]+)`", one, escape(text)))


#: "9.8 s", "105 MB": the number and its unit, kept together by a narrow no-break space.
_UNIT = re.compile(r"(\d)[ \u00a0](s|ms|min|h|MB|MiB|GB|GiB|KiB|%)(?=[\s.,;:)<·—–-]|$)")
_KEEP = re.compile(r"(<(pre|code|script|style|textarea)\b.*?</\2>)", re.S)


def tight_units(html: str) -> str:
    out, last = [], 0
    for block in _KEEP.finditer(html):  # code keeps its own spacing
        out.append(_UNIT.sub("\\1\u202f\\2", html[last : block.start()]))
        out.append(block.group(0))
        last = block.end()
    out.append(_UNIT.sub("\\1\u202f\\2", html[last:]))
    return "".join(out)


@dataclass
class Build:
    out: Path
    env: Environment
    md: MarkdownIt

    def write(self, path: str, html: str) -> None:
        html = tight_units(html)
        target = self.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html)

    def render(self, template: str, path: str, **ctx) -> None:
        depth = path.count("/")
        canonical = f"{SITE_URL}/{path.removesuffix('index.html')}"
        self.write(
            path,
            self.env.get_template(template).render(root="../" * depth, canonical=canonical, **ctx),
        )


def git_dates() -> dict[str, str]:
    """When each tracked file last changed, straight from the history.

    The sitemap's lastmod is then a fact about the content and not the build clock: rebuilding
    the site without changing a page leaves that page's date where it was.
    """
    try:
        log = subprocess.run(
            ["git", "log", "--format=%x00%cs", "--name-only"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    dates: dict[str, str] = {}
    when = ""
    for line in log.splitlines():
        if line.startswith("\x00"):
            when = line[1:]
        elif line and when:
            dates.setdefault(line, when)  # the log runs newest first
    return dates


def last_changed(dates: dict[str, str], source: Path | None) -> str:
    """The newest change at a path — a file, or everything under a lab's directory."""
    if source is None:
        return ""
    rel = str(source.relative_to(ROOT))
    if rel in dates:
        return dates[rel]
    under = [d for path, d in dates.items() if path.startswith(f"{rel}/")]
    return max(under) if under else ""


def flag(country: str) -> str:
    """An ISO 3166-1 alpha-2 code as regional indicator symbols — no flag images to ship."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper())


def attempt_entry(attempt, titles: dict[str, str], deltas: dict[float, float]) -> dict:
    """One attempt, as both the recent table and a day of the heatmap show it."""
    return {
        "lab_id": attempt.lab_id,
        "score": attempt.score_percent,
        "when": datetime.fromtimestamp(attempt.started_at, UTC).strftime("%d %b %Y"),
        "title": titles.get(attempt.lab_id, attempt.lab_id),
        "kind": attempt.kind,
        "passed": attempt.passed,
        "rated": attempt.rated,
        "duration": f"{attempt.duration_seconds // 60}m {attempt.duration_seconds % 60:02d}s",
        "delta": deltas.get(attempt.started_at, 0),
    }


def collect_players(labs: list[dict], limit: int = 100) -> list[dict]:
    """The sample population, replayed through the real rating code. Empty if it is not generated.

    Nothing here is real usage; the pages say so. It exists because a leaderboard with two rows
    and an empty heatmap tells a visitor nothing about what the thing does.
    """
    from norboten_api import accounts as acc
    from norboten_api import seed

    try:
        payload = seed.read()
    except FileNotFoundError:
        return []

    titles = {lab["id"]: lab["title"] for lab in labs}
    titles |= {b.topic: f"Theory: {b.bank.title}" for b in banks.topic_banks()}
    attempts: dict[str, list] = {}
    for raw in payload["attempts"]:
        attempt = acc.Attempt.model_validate(raw)
        attempts.setdefault(attempt.user_id, []).append(attempt)

    players = []
    for raw in payload["users"]:
        user = acc.User.model_validate(raw)
        history = sorted(attempts.get(user.user_id, []), key=lambda a: a.started_at)
        ratings: dict[str, acc.TopicRating] = {}
        deltas: dict[float, float] = {}
        for attempt in history:
            after = acc.rate(attempt, ratings)
            deltas[attempt.started_at] = round(
                sum(acc.deltas(ratings, after).values()) / len(after or [1])
            )
            ratings |= after
        overall = acc.overall(ratings)
        spokes = acc.radar(ratings)
        played = sorted((s for s in spokes if s["games"]), key=lambda s: -s["rating"])
        recent = sorted(history, key=lambda a: a.started_at, reverse=True)[:20]

        by_day: dict[str, list] = {}
        for a in history:
            by_day.setdefault(a.day.isoformat(), []).append(attempt_entry(a, titles, deltas))
        # one heatmap per calendar year that has any work in it, newest first
        years = []
        for year in sorted({a.day.year for a in history}, reverse=True):
            last = date(year, 12, 31)
            span = (last - date(year, 1, 1)).days + 1
            year_map = acc.contributions(history, days=span, today=last)
            years.append(
                {
                    "year": year,
                    "total": year_map["total"],
                    "best_day": year_map["best_day"],
                    "heatmap": graphics.heatmap(year_map),
                }
            )
        players.append(
            {
                "nick": user.nick,
                "country": user.country,
                "flag": flag(user.country),
                "avatar": graphics.identicon(user.avatar_seed, 40),
                "avatar_big": graphics.identicon(user.avatar_seed, 96),
                "rating": round(overall.r),
                "rd": round(overall.rd),
                "provisional": overall.provisional,
                "conservative": overall.conservative,
                "attempts": len(history),
                "passed": sum(1 for a in history if a.passed),
                "joined": datetime.fromtimestamp(user.created_at, UTC).strftime("%b %Y"),
                "best_topics": [s["title"] for s in played[:3]],
                "spokes": [
                    {"title": s["title"], "rating": round(s["rating"]), "games": s["games"]}
                    for s in played[:8]
                ],
                "radar": graphics.radar(spokes),
                "contributions": acc.contributions(history),
                "days": by_day,
                "years": years,
                "history": [attempt_entry(a, titles, deltas) for a in recent],
            }
        )
    players.sort(key=lambda p: -p["conservative"])
    for player in players:
        player["heatmap"] = graphics.heatmap(player["contributions"])
    return players[:limit]


CAPTURES = [
    ("tui-home", "Home", "Doctor runs as it opens. The labs you left half-done come first."),
    (
        "tui-labs",
        "The catalogue",
        "Every lab with your status and whether it is rated, its briefing beside the list, and "
        "`f` to narrow it to one track.",
    ),
    (
        "tui-lab",
        "A lab",
        "Every action on a key: start, shell, live checks, check + reboot, hints, the tutor, the consoles.",
    ),
    (
        "tui-theory",
        "Theory",
        "Every bank with your accuracy on it. `r` times a run; a rated bank is graded on the server.",
    ),
    ("tui-quiz", "A question", "The answer, and why, after every question — right or wrong."),
    (
        "tui-journals",
        "Journals",
        "The reading for each lab and topic, rendered in the terminal. `e` makes a PDF.",
    ),
    (
        "tui-play",
        "Play",
        "Recorded sessions through a real terminal emulator, with ±3-command skips.",
    ),
    (
        "tui-ratings",
        "Ratings",
        "The boards, overall and per topic, from the server. Sample accounts shown.",
    ),
    (
        "tui-you",
        "You",
        "A year of work, then by topic, then attempts — a sample account's profile.",
    ),
    ("tui-system", "System", "Doctor in full with the fix for each finding, and the base images."),
]


def collect_captures() -> list[dict]:
    """Real screenshots of the TUI, rendered to SVG by Textual itself (site/capture.py)."""
    out = []
    for slug, title, blurb in CAPTURES:
        if (SITE / "static" / "captures" / f"{slug}.svg").is_file():
            out.append({"slug": slug, "title": title, "blurb": blurb})
    return out


def collect_journals(build: Build, labs: list[dict]) -> list[dict]:
    """Every journal in the checkout, rendered. The site is their primary form; the PDF is the
    other one (`norboten journal <id> --pdf`)."""
    from norboten import journal as journals
    from norboten import topics as taxonomy

    titles = {lab["id"]: lab["title"] for lab in labs}
    out = []
    for j in journals.all_journals():
        html = build.md.render(j.body)
        opening = re.sub(r"<[^>]+>", "", html).strip().split("\n\n")[0]
        bodies = re.split(r"^## .+$", j.body, flags=re.M)[1:]
        sections = [
            {"title": h["text"], "id": h["id"], "words": len(text.split())}
            for h, text in zip(
                [h for h in headings(html) if h["level"] == "h2"], bodies, strict=True
            )
        ]
        out.append(
            {
                "id": j.id,
                "kind": j.kind,
                "title": j.title,
                "minutes": j.minutes,
                "words": j.words,
                "topics": j.topics,
                "topic_titles": [taxonomy.get(t).title for t in j.topics],
                "review_count": len(j.review),
                "lab": j.id if j.kind == "lab" else "",
                "lab_title": titles.get(j.id, ""),
                "opening": " ".join(opening.split())[:220],
                "covers": j.covers,
                "html": html,
                "sections": sections,
                "map": graphics.journal_map(sections),
                "card_map": graphics.journal_map(sections, width=560, links=False, labels=False),
            }
        )
    return out


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r")

#: The Play page's wall: four long sessions, each in its own terminal colours.
WALL_THEMES = ("green", "amber", "ice", "violet")
WALL_MIN_COMMANDS = 60


def _seconds(value: float) -> str:
    if value < 60:
        return f"{value:.1f} s"
    return f"{int(value) // 60}m {int(value) % 60:02d}s"


def command_rows(data: dict) -> list[dict]:
    """Each command with what it did: how long until the next prompt, how many lines it printed,
    and which files changed after it — instead of a column of dashes."""
    events = data.get("events", [])
    commands = data.get("commands", [])
    duration = float(data.get("duration") or (events[-1][0] if events else 0))
    changed: dict[str, set] = {}
    for change in data.get("changes", []):
        changed.setdefault(change.get("command", ""), set()).add(change.get("path", ""))
    rows = []
    for n, c in enumerate(commands):
        start = c["at"]
        end = commands[n + 1]["at"] if n + 1 < len(commands) else duration
        text = "".join(e[2] for e in events if e[1] == "o" and start <= e[0] < end)
        lines = [line for line in _ANSI.sub("", text).split("\n") if line.strip()]
        # the first line is the command's own echo, the last the next prompt
        printed = max(0, len(lines) - 2)
        rows.append(
            {
                "at": f"{int(start) // 60}:{int(start) % 60:02d}",
                "text": c["text"],
                "took": _seconds(max(0.0, end - start)),
                "lines": printed,
                "changed": sorted(changed.get(c["text"], ())),
            }
        )
    return rows


def recorded_at(timestamp: float | None, duration: float) -> str:
    """When the session ran, from the recording's own header — start and end, in UTC."""
    if not timestamp:
        return ""
    start = datetime.fromtimestamp(float(timestamp), UTC)
    end = datetime.fromtimestamp(float(timestamp) + duration, UTC)
    return f"{start:%d %b %Y · %H:%M} → {end:%H:%M} UTC"


def collect_streams() -> list[dict]:
    """Recorded sessions shipped with the site: site/streams/<slug>.json.

    Each file is an asciicast recording plus the command log that went with it, written by
    `norboten dev record` from site/streams/<slug>.script on a real VM. The long ones make up the
    Play page's wall of four; the rest are listed below it with their commands.
    """
    out = []
    for path in sorted((SITE / "streams").glob("*.json")):
        data = json.loads(path.read_text())
        header = data.get("header", {})
        rows = command_rows(data)
        out.append(
            {
                "slug": path.stem,
                "title": data.get("title") or path.stem,
                "blurb": data.get("blurb", ""),
                "lab": data.get("lab_id", ""),
                "image": data.get("image", ""),
                "cols": header.get("width", 100),
                "rows": header.get("height", 28),
                "duration": _seconds(float(data.get("duration", 0))),
                "when": recorded_at(header.get("timestamp"), float(data.get("duration", 0))),
                "commands": rows,
                "files_changed": len({f for r in rows for f in r["changed"]}),
                "wall": len(rows) >= WALL_MIN_COMMANDS,
            }
        )
    for theme, stream in zip(WALL_THEMES, [s for s in out if s["wall"]], strict=False):
        stream["theme"] = theme
    return out


def collect_labs() -> list[dict]:
    out = []
    for lab in all_labs():
        m = lab.manifest
        out.append(
            {
                "id": m.id,
                "short_id": m.short_id,
                "title": m.title,
                "track": m.track.value,
                "difficulty": m.difficulty,
                "dots": graphics.difficulty(m.difficulty),
                "minutes": m.estimated_minutes,
                "images": m.base_images,
                "objectives": m.objectives,
                "first_objective": m.objectives[0],
                "checks": [
                    {"id": c.id, "objective": m.objectives[c.objective - 1]} for c in m.checks
                ],
                "time_limit": m.time_limit_minutes,
                "runtime": m.runtime,
                "reboot_required": m.reboot_required,
                "pass_percent": m.pass_percent,
                "briefing": lab.briefing,
                "repo_path": str(lab.path.relative_to(ROOT)),
                # the public build only ever sees labs/; rated labs live in the private submodule
                "rated": False,
                "reading": reading(lab),
            }
        )
    return out


def reading(lab) -> list[dict]:
    """What the lab's hints point at, once each: topic journals, other labs' journals, man pages
    and documentation. The lab's own journal has its own button, so it is left out here."""
    from norboten import journal

    journals = {j.id: j for j in journal.all_journals()}
    seen: list[str] = []
    for ladder in lab.hints.checks.values():
        seen += [r for r in ladder.refs_upto(4) if r not in seen]
    out = []
    for raw in seen:
        ref = journal.parse_ref(raw)
        if ref.kind == "journal":
            found = journals.get(ref.target)
            if found is None or found.id == lab.manifest.id:
                continue
            heading = (journal.heading_for(found, ref.anchor) or ref.anchor).replace("`", "")
            out.append(
                {
                    "label": f"{found.title.split(' — ')[0]} › {heading}",
                    "href": f"journals/{found.id}/#{ref.anchor}",
                }
            )
        elif ref.kind == "man":
            out.append({"label": f"man {ref.target}", "href": ""})
        else:
            out.append({"label": ref.target, "href": ref.target, "external": True})
    return out


def question_card(q) -> dict:
    """One question as the site draws it: the choices, which of them are right, and why.

    Everything here is already public in `quizzes/` and in each lab's `theory.yaml` — these are
    the unrated banks. A rated bank is never rendered into a page (docs/rated-labs.md).
    """
    return {
        "id": q.id,
        "type": q.type,
        "prompt": q.prompt,
        "code": q.code,
        "code_lang": q.code_lang,
        "choices": [{"id": c.id, "text": c.text} for c in q.choices],
        "answer": list(q.answer),
        "answer_text": ", ".join(q.choice_text(a) for a in q.answer),
        "explanation": " ".join(q.explanation.split()),
        "references": " · ".join(q.references),
        "verified": q.verify is not None,
    }


def collect_topics() -> tuple[list[dict], dict[str, dict], dict | None]:
    topics, per_lab, sample = [], {}, None
    for b in banks.all_banks():
        verified = sum(1 for q in b.bank.questions if q.verify)
        entry = {
            "topic": b.topic,
            "title": b.bank.title,
            "description": b.bank.description,
            "count": len(b.bank.questions),
            "verified": verified,
        }
        if b.lab_id:
            per_lab[b.lab_id] = {
                "count": len(b.bank.questions),
                "questions": [question_card(q) for q in b.bank.questions[:3]],
            }
        else:
            topics.append(entry)
            if sample is None and b.topic == "bash":
                sample = question_card(next(q for q in b.bank.questions if q.code))
    return topics, per_lab, sample


def relation_layout(width: int = 940, height: int = 700, pad: int = 46) -> tuple[list, list]:
    """The relation graph, laid out once here so the page can draw it and point at it.

    networkx does the layout with the same seed the analytics job uses, so the picture a reader
    explores is the picture the nightly chart draws.
    """
    import networkx as nx

    from norboten_api.analytics.relations import graph

    g = graph()
    pos = nx.spring_layout(g, seed=11, k=0.55, iterations=200, weight="weight")
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]

    def place(point) -> tuple[float, float]:
        x = pad + (point[0] - min(xs)) / (max(xs) - min(xs) or 1) * (width - 2 * pad)
        y = pad + (max(ys) - point[1]) / (max(ys) - min(ys) or 1) * (height - 2 * pad)
        return x, y

    points = {node: place(p) for node, p in pos.items()}
    nodes = [
        {
            "id": node,
            "label": data["label"],
            "kind": data["kind"],
            "degree": g.degree(node),
            "x": points[node][0],
            "y": points[node][1],
        }
        for node, data in g.nodes(data=True)
    ]
    edges = [
        {
            "a": a,
            "b": b,
            "kind": kind,
            "x1": points[a][0],
            "y1": points[a][1],
            "x2": points[b][0],
            "y2": points[b][1],
        }
        for a, b, kind in g.edges(data="kind")
    ]
    return nodes, edges


def write_analytics(build: Build, common: dict) -> None:
    """The Analytics page, drawn from the sample population. On the server the nightly job
    (`python -m norboten_api.analytics --database-url …`) overwrites the charts and facts.json."""
    from norboten_api import seed
    from norboten_api.analytics import from_seed, render_all

    path = seed.default_path()
    if not path.exists():
        return
    svgs, facts = render_all(from_seed(path))
    out = build.out / "analytics"
    out.mkdir(parents=True, exist_ok=True)
    for name, svg in svgs.items():
        (out / f"{name}.svg").write_text(svg)
    (out / "facts.json").write_text(json.dumps(facts, indent=2))

    def lookup(key: str) -> str:
        group, _, name = key.partition(".")
        return str(facts.get(group, {}).get(name, "—"))

    build.env.globals["facts_lookup"] = lookup
    nodes, edges = relation_layout()
    build.render(
        "analytics.html",
        "analytics/index.html",
        nav="analytics",
        page_title="Analytics",
        page_description="Pass rates, time to solve, ratings, theory, cohorts and relations.",
        facts=facts,
        relations=graphics.relation_map(nodes, edges),
        relation_kinds=sorted({n["kind"] for n in nodes}),
        **common,
    )


def write_ask_index(out: Path) -> None:
    """The consultant's own passages, for the widget to rank in the browser when the API is down.

    Built by the same function the API retrieves from, so the exclusions are the same ones: no
    solution file, no hint ladder, no journal walkthrough.
    """
    from norboten_api import retrieval
    from norboten_api.routers.chat import FAQ_GROUPS

    passages = [
        {"id": p.id, "title": p.title, "url": p.url, "kind": p.kind, "text": p.text[:2400]}
        for p in retrieval.build_corpus()
    ]
    faq = [{"title": title, "chips": chips} for title, chips in FAQ_GROUPS]
    synonyms = [sorted(group) for group in retrieval.SYNONYMS]
    (out / "ask-index.json").write_text(
        json.dumps({"passages": passages, "faq": faq, "synonyms": synonyms}, separators=(",", ":"))
    )


#: what a link may start with and still not point at a file of ours
ELSEWHERE = ("http://", "https://", "//", "mailto:", "data:", "javascript:", "#")


def broken_links(out: Path) -> list[str]:
    """Every relative link in the built site, resolved against the page that carries it.

    A page is addressed as a directory — `/journals/`, never `/journals/index.html` — so its own
    file keeps the name and the address loses it. The two only agree while every link points at a
    directory that really holds an index.html, and a missing trailing slash or a page that was
    never written is invisible until somebody clicks it. This is what the build refuses to pass.
    """
    faults = []
    for page in sorted(out.rglob("*.html")):
        where = page.relative_to(out)
        for link in re.findall(r'(?:href|src)="([^"]*)"', page.read_text()):
            if not link or link.startswith(ELSEWHERE):
                continue
            path = link.split("#")[0].split("?")[0]
            if not path:
                continue
            if path.endswith("index.html"):
                faults.append(f"{where}: {link} — link to the directory, not to index.html")
                continue
            # 404.html is served at whatever address was asked for, so its links are absolute
            base = out if path.startswith("/") else page.parent
            target = (base / path.lstrip("/")).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                faults.append(f"{where}: {link} — no such page")
    return faults


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=SITE / "dist")
    args = ap.parse_args()

    out = args.out
    # Empty the directory instead of deleting it: deploy/install-server.py builds the site in a
    # container with the server's site directory bind-mounted as --out, and a mount point cannot
    # be removed ("Device or resource busy").
    if out.exists():
        for entry in out.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    out.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(SITE / "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["keys"] = keycaps
    build = Build(out=out, env=env, md=markdown())

    labs = collect_labs()
    topics, lab_theory, sample = collect_topics()
    question_count = sum(t["count"] for t in topics) + sum(t["count"] for t in lab_theory.values())
    verified_all = sum(1 for b in banks.all_banks() for q in b.bank.questions if q.verify)

    track_meta = {
        "intro": (
            "Start here",
            "One lab that runs on every base image — the whole path, in five minutes.",
        ),
        "linux": (
            "Linux",
            "General troubleshooting and shell work on lighter images: Ubuntu 26.04 and Alpine.",
        ),
        "rhcsa": (
            "RHCSA",
            "Five labs on Rocky Linux 10, grounded in the current EX200 objectives, "
            "ending in a timed exam simulation.",
        ),
        "bash": (
            "Bash",
            "Two deploy-day scripts, graded by running them against the grader's own directories: "
            "error handling, quoting, atomic switches, safe deletion.",
        ),
        "python": (
            "Python",
            "A sync job that lied about its failures and a tool only root could run: exit "
            "status, timeouts, atomic writes, virtual environments.",
        ),
        "automation": (
            "Automation & AI",
            "A Python job, an AI gateway, an agent that never stopped, and Ollama four ways — "
            "deployed, exposed, starved of context and memory, and secured.",
        ),
        "claude": (
            "Claude Code",
            "Headless Claude Code as a machine runs it: permission rules, hooks, subagents, MCP "
            "servers and CI jobs that stay inside a budget.",
        ),
        "mcp": (
            "MCP",
            "Model Context Protocol servers as Claude Code meets them: what a server exposes, tool "
            "results that give orders, tokens for someone else, a chatty stdio server, a proxy that "
            "holds the stream, and scopes that disagree.",
        ),
        "ansible": (
            "Ansible",
            "A playbook that never converges and a deploy stuck at a vault prompt: idempotence, "
            "variable precedence, Vault without a keyboard.",
        ),
        "docker": (
            "Docker",
            "A queue that lost its jobs at every reboot and a Compose stack that could not find its "
            "API: volumes, published ports, networks, restart policies.",
        ),
        "terraform": (
            "Terraform",
            "A rename that would regenerate a secret and a site removed from the middle of a list: "
            "moved blocks, drift, for_each, state hygiene.",
        ),
    }
    tracks = []
    for track_id, (title, blurb) in track_meta.items():
        in_track = [lab for lab in labs if lab["track"] == track_id]
        if in_track:
            tracks.append(
                {
                    "id": track_id,
                    "kicker": f"{len(in_track)} lab{'s' * (len(in_track) != 1)}",
                    "title": title,
                    "blurb": blurb,
                    "labs": in_track,
                    "images": sorted({i for lab in in_track for i in lab["images"]}),
                }
            )

    common = {
        "any_rated": any(lab["rated"] for lab in labs),
        "api": API,
        "github": GITHUB,
        "site_url": SITE_URL,
        "ga_id": GA_ID,
        "labs": labs,
        "topics": topics,
        "question_count": question_count,
    }

    from norboten import journal as journal_mod

    all_journals = journal_mod.all_journals()
    captures = collect_captures()
    build.render(
        "home.html",
        "index.html",
        nav="home",
        tracks=tracks,
        highlights=HIGHLIGHTS,
        sample=sample,
        lab_bank_count=len(lab_theory),
        verified_count=sum(t["verified"] for t in topics),
        journals_count=len(all_journals),
        journal_words=f"{sum(j.words for j in all_journals):,}",
        home_captures=[c for c in captures if c["slug"] in ("tui-home", "tui-play", "tui-you")],
        **common,
    )
    build.render(
        "features.html",
        "features/index.html",
        nav="features",
        page_title="Features",
        groups=[
            {
                **g,
                "features": [
                    {**f, "detail": f.get("detail", "").replace("{verified}", str(verified_all))}
                    for f in g["features"]
                ],
            }
            for g in FEATURE_GROUPS
        ],
        captures=captures,
        **common,
    )
    build.render(
        "labs.html",
        "labs/index.html",
        nav="labs",
        page_title="Labs",
        tracks=tracks,
        sample=sample,
        **common,
    )

    def laid_out(steps: list[dict], start: int, step: int) -> list[dict]:
        """Diagrams are inline SVG, so the boxes get their x here rather than in the template."""
        return [{**s, "x": start + i * step} for i, s in enumerate(steps)]

    build.render(
        "how-it-works.html",
        "how-it-works/index.html",
        nav="how",
        page_title="How it works",
        lifecycle=laid_out(LIFECYCLE, 16, 164),
        gate=laid_out(GATE, 16, 196),
        pipeline=laid_out(PIPELINE, 16, 167),
        plugin_details=(SITE / "captures" / "plugin-details.txt").read_text().split("\n", 1),
        decisions=DECISIONS,
        stack=STACK,
        **common,
    )
    from norboten import __version__

    build.render(
        "install.html",
        "install/index.html",
        nav="install",
        page_title="Install",
        version=__version__,
        **common,
    )
    build.render(
        "about.html",
        "about/index.html",
        nav="about",
        page_title="About",
        page_description="Who makes Norboten, and why it exists.",
        personal_site=PERSONAL_SITE,
        **common,
    )
    build.render(
        "community.html",
        "community/index.html",
        nav="community",
        page_title="Community",
        page_description="The Norboten Discord: new labs as they land, channels by topic, and the "
        "author.",
        discord_invite=DISCORD_INVITE,
        channel_groups=[
            {
                "name": name,
                "channels": [{"name": channel, "about": about} for channel, about in channels],
            }
            for name, channels in CHANNELS
        ],
        **common,
    )
    build.render(
        "privacy.html",
        "privacy/index.html",
        nav="privacy",
        page_title="Privacy policy",
        page_description="What Norboten keeps about you, where, and for how long.",
        privacy_updated=PRIVACY_UPDATED,
        domain=DOMAIN,
        **common,
    )
    build.render(
        "donate.html",
        "donate/index.html",
        nav="donate",
        page_title="Donate",
        page_description="Norboten is free to run locally; €10 helps keep the hosted side up.",
        tiers=DONATION_TIERS,
        default_tier=DONATION_DEFAULT,
        **common,
    )
    build.render(
        "donate-thanks.html",
        "donate/thanks/index.html",
        nav="donate",
        page_title="Thank you",
        page_description="The donation went through. This is where Stripe sends you back.",
        **common,
    )

    for page, path, title in (
        ("account", "account/index.html", "Account"),
        ("authorize", "authorize/index.html", "Connect an AI client"),
    ):
        build.render(
            "account.html",
            path,
            nav="account",
            page=page,
            page_title=title,
            page_description="Sign in to Norboten with GitHub, choose a nick, and link Discord.",
            **common,
        )

    journals = collect_journals(build, labs)
    with_journals = {j["id"] for j in journals}
    for lab in labs:
        lab["journal"] = lab["id"] in with_journals
    if journals:
        build.render(
            "journals.html",
            "journals/index.html",
            nav="journals",
            page_title="Journals",
            page_description="Study documents for the labs: the mechanism, a failure walked "
            "through, and the wrong turns.",
            journals=journals,
            **common,
        )
        from norboten import journal as journal_mod
        from norboten import journal_pdf

        by_id = {j.id: j for j in journal_mod.all_journals()}
        for j in journals:
            # the print views: the same document the TUI exports as a PDF, for the browser's own
            # print dialog, and the cheat sheet on its own
            source = by_id[j["id"]]
            build.write(
                f"journals/{j['id']}/print.html",
                journal_pdf.to_html(source, script=journal_pdf.PRINT_ON_OPEN),
            )
            if source.kind != "note":  # a note has no commands to keep beside the keyboard
                build.write(
                    f"journals/{j['id']}/cheat-sheet.html",
                    journal_pdf.to_html(source, cheat_sheet=True, script=journal_pdf.PRINT_ON_OPEN),
                )
            build.render(
                "journal.html",
                f"journals/{j['id']}/index.html",
                nav="journals",
                page_title=j["title"],
                page_description=j["opening"][:160],
                j=j,
                **common,
            )

    streams = collect_streams()
    build.render(
        "live.html",
        "live/index.html",
        nav="live",
        page_title="Play",
        page_description="Watch a learner fix a broken Linux machine, live or replayed.",
        streams=streams,
        **common,
    )

    write_analytics(build, common)

    players = collect_players(labs)
    recording_for = {s["lab"]: s["slug"] for s in streams}
    for player in players:
        for attempt in player["history"]:
            attempt["recording"] = recording_for.get(attempt["lab_id"], "")
        for day in player["days"].values():
            for attempt in day:
                attempt["recording"] = recording_for.get(attempt["lab_id"], "")
    if players:
        ratings = [p["rating"] for p in players]
        build.render(
            "players.html",
            "players/index.html",
            nav="players",
            page_title="Ratings",
            page_description="Per-topic Glicko-2 ratings, earned on timed attempts.",
            players=players,
            board_topics=sorted({t for p in players for t in p["best_topics"]}),
            board_min=min(ratings) // 10 * 10,
            board_max=-(-max(ratings) // 10) * 10,
            **common,
        )
        for player in players:
            build.render(
                "profile.html",
                f"players/{player['nick']}/index.html",
                nav="players",
                page_title=player["nick"],
                page_description=f"{player['nick']} — sample profile.",
                p=player | {"avatar": player["avatar_big"]},
                **common,
            )

    for lab in labs:
        detail = dict(lab)
        # the briefing opens with the lab's own title; the page already carries it as its h1
        detail["briefing_html"] = re.sub(
            r"\A\s*<h1[^>]*>.*?</h1>", "", build.md.render(lab["briefing"]), flags=re.S
        )
        detail["theory"] = lab_theory.get(lab["id"])
        build.render(
            "lab.html",
            f"labs/{lab['id']}/index.html",
            nav="labs",
            page_title=lab["title"],
            page_description=lab["first_objective"],
            lab=detail,
            **common,
        )

    tree = [
        {"title": group, "pages": [{"slug": s, "title": t} for s, t, _ in items]}
        for group, items in DOC_TREE
    ]
    search_index = []
    for _group, items in DOC_TREE:
        for slug, title, source in items:
            path = ROOT / source
            if not path.is_file():
                continue
            html = build.md.render(path.read_text())
            build.render(
                "docs.html",
                f"docs/{slug}/index.html",
                nav="docs",
                page_title=title,
                tree=tree,
                current=slug,
                content=html,
                toc=headings(html),
                **common,
            )
            search_index.append(
                {
                    "title": title,
                    "url": f"../../docs/{slug}/",
                    "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))[:12000],
                }
            )
    first = DOC_TREE[0][1][0][0]
    build.write(
        "docs/index.html",
        f'<!doctype html><meta http-equiv="refresh" content="0; url=./{first}/">',
    )
    (out / "search-index.json").write_text(json.dumps(search_index))
    write_ask_index(out)

    shutil.copytree(SITE / "static", out, dirs_exist_ok=True)

    recordings = sorted((SITE / "streams").glob("*.json"))  # the canned sessions the player reads
    if recordings:
        (out / "streams").mkdir(parents=True, exist_ok=True)
        for recording in recordings:
            shutil.copy2(recording, out / "streams" / recording.name)
    (out / "CNAME").write_text(f"{DOMAIN}\n")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: https://{DOMAIN}/sitemap.xml\n"
    )
    # docs/index.html is a redirect to the first page, not a page of its own
    pages = sorted(
        str(p.relative_to(out)) for p in out.rglob("index.html") if p != out / "docs" / "index.html"
    )
    # Every page the repository can date is dated from the history of what it was built from.
    dates = git_dates()
    sources: dict[str, Path] = {
        f"labs/{lab['id']}/index.html": ROOT / lab["repo_path"] for lab in labs
    }
    sources |= {f"journals/{j.id}/index.html": j.path for j in all_journals}
    sources |= {
        f"docs/{slug}/index.html": ROOT / source
        for _, group in DOC_TREE
        for slug, _, source in group
    }
    fallback = max(dates.values(), default=datetime.now(UTC).date().isoformat())
    urls = "".join(
        f"<url><loc>https://{DOMAIN}/{p.removesuffix('index.html')}</loc>"
        f"<lastmod>{last_changed(dates, sources.get(p)) or fallback}</lastmod></url>"
        for p in pages
    )
    (out / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )
    (out / "404.html").write_text(
        build.env.get_template("base.html")
        .render(root="/", page_title="Not found", **common)
        .replace("{% block body %}{% endblock %}", "")
    )
    if faults := broken_links(out):
        for fault in faults:
            print(f"broken link: {fault}", file=sys.stderr)
        return 1
    print(f"{len(pages)} pages -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
