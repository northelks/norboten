# FAQ

One answer for every question the site's consultant offers, grouped the same way. Each answer points
at the document that goes deeper.

## The idea

### What makes this different from a browser-based Linux course?

A course in a browser gives you a shell in a container and asks questions about it. Norboten boots a
real virtual machine on your own computer, breaks it the way production machines break — a volume
that fills up, a service that will not stay up, a bootloader you must edit — and grades the machine,
not your answer: checks inspect its state, then it reboots and they inspect it again. Everything runs
offline once downloaded, and every lab is a directory of scripts you can read and extend.

### Is this a quiz app?

No. A lab is passed when the machine behaves, judged by scripts that run inside it, after a reboot.
The theory questions are a separate practice mode and never affect a lab's result.

### Why a virtual machine instead of a container?

Why not just Docker? Because the interesting failures are not container-shaped: a mount that stops
the boot, a root password you have to recover from the bootloader, an SELinux relabel, a service that
must come back after a reboot. A container cannot reboot, and that is the one thing a lab about a
system checks.

Eight labs are the exception, and run in a container on purpose. Two Linux labs — a shared folder that
locks its team out and a log that never rotates — are about users, groups, modes and one program's
configuration, with no boot in them. The six Claude Code labs are about how Claude Code is configured,
and run the real Claude Code against a scripted model. They start in about a second and need Docker
or Podman instead of QEMU.

### Why is everything so dark?

Norboten is a terminal program first: its interface is a full-screen TUI, green on near-black, and
the site uses the same palette so that its screenshots, recordings and the live terminal player look
like the thing you will actually use. Journals exported as PDFs are the exception — paper gets a
light page.

### What is a journal, and how is it different from the docs?

The docs describe Norboten: how labs are specified, how the gate works, how to run a server. A
journal teaches the subject a lab is about — the mechanism, one failure walked through on a real
machine, the wrong turns people take, a cheat sheet and review questions. Every lab has one, and seven
topic journals cover subjects end to end. Read them with `4` in the TUI, on the site, or as a PDF.

## Labs and grading

### How is a lab graded?

Each lab has check scripts. On `c` they are copied into the VM and run as a separate grading account;
the machine reboots; they run again. A check passes only if it passed both times, the score is the
weight of passing checks over the total, and the lab is passed at its pass line (100% for most labs,
70% for the exam simulation). See [Lab specification](../lab-spec/), section 5.

### What is the reboot check, and why does it matter?

After the first pass the grader reboots the VM and waits for it, then runs every check again. A fix
that only lives in memory — a service started but not enabled, a mount made by hand but not in
`/etc/fstab`, a kernel setting written to `/proc` — passes before the reboot and fails after it.
Persistence is what production needs, so it is what the grade measures. `x` runs the checks without
the reboot for quick feedback, and can never pass a lab.

### How do I reset a lab I have broken beyond repair?

Press `r` on the lab's screen to start over from the broken state. The VM's disks are rolled back to
the snapshot taken before the faults, the machine cold-boots, and the faults are applied again — about
ten seconds. Your attempt's history is kept.

### How long does the first lab take?

`hello` is designed for five minutes. Starting it the first time downloads Norboten's pinned Lima and
the smallest base image (Alpine, about 105 MB), boots, snapshots and breaks the machine: roughly 25–35
seconds on a laptop after the download. Later starts and resets are faster.

### What is inside a lab directory?

`lab.yaml` (the manifest: title, track, topics, difficulty, base images, objectives and checks),
`briefing.md` (symptoms only), `break/` (scripts that apply the faults), `check/` (scripts that
decide what fixed means), `hints.yaml` (four levels per check), `solution/solution.sh` (the reference
fix, used by CI), and usually `journal.md` and `theory.yaml`. See
[Writing a lab](../writing-a-lab/).

### How does the solvability gate work?

For every lab and every base image it supports, CI starts a clean VM, applies the faults and requires
every check to fail — a check that passes on a broken machine tests nothing. Then it runs the
reference solution and requires every check to pass, before and after a reboot. Labs whose learners
meet the fault only after a reboot get a second phase: faults, that reboot, and every check must still
fail. See [Lab specification](../lab-spec/), section 9.

### What stops a lab from being unsolvable?

The gate: a lab cannot merge unless its own reference solution passes every check on every image it
lists, including after a reboot. When a base image or the runner changes, CI re-runs the gate for
every lab.

### Can I break the grading by breaking the machine?

Mostly no: checks run as a separate `norboten-grader` account with its own key, so a lab can remove
your `sudo` (the exam simulation does) and you can misconfigure your own without stopping the grader.
Delete that account and grading stops — but you will have to mean it.

### Why is the first boot slower than the reset?

The first boot runs cloud-init to create your account and take the clean snapshot. A reset is a disk
rollback and a cold boot of an image that has already been through that: about ten seconds.

## The tutor and hints

### Will the tutor tell me the answer if I ask nicely?

No. The tutor (`t` on a lab) is never given the reference solution — the request it receives has no
field for it — and a separate guard compares every reply against the solution and your hint level
before it is shown. It answers from the machine's evidence: check results and facts gathered from the
VM. Prompt tricks cannot extract what it never had.

It runs on your machine, on your own model: Claude Code if you have it (on your subscription), an
Anthropic, OpenAI or Gemini key you have exported, or a local Ollama — `m` on System picks one. With
none of them, `t` shows the lab's own hint instead. After you pass or surrender, `m` on the lab asks
the same model to review the attempt: that review is the one place the solution is read.

### How do hints work?

Every check has four hint levels, and `h` on the selected check shows the next one. Level 1 restates
the symptom, level 2 names the kind of evidence to look at, level 3 narrows to the component, level 4
names the problem. No level gives the command that fixes it. You choose when to go deeper; the tutor
cannot raise your level.

## Your machine

### What is left on my machine if I delete Norboten?

Everything Norboten writes is in `~/.norboten`: the pinned Lima, base images, lab VMs, sessions,
recordings and the sign-in token. `norboten uninstall` deletes the lab VMs and containers, that
directory and the program; what remains is uv, which the installer may have added, and the line uv
put on your shell's `PATH`.

### What does it do to my machine?

Downloads a pinned Lima and golden images into `~/.norboten`, and runs virtual machines. No host
directory is mounted into a lab VM, no ports are forwarded, and no SSH agent is passed through.

### Can a lab VM see my files?

No. Lab VMs are created with no shared directories, no port forwarding and no SSH agent forwarding.
The VM receives your public SSH key and nothing else from the host.

### How much disk does this need?

The base images are 105 MB (Alpine) to 1.1 GB (the automation image), and a running lab keeps its own
disk and a snapshot, so plan on about twice the image's size per lab you have started, plus the image.
A few GB is comfortable for the Linux and RHCSA tracks; the automation and devops images need more.
`8` (System) shows what is downloaded and how much space it uses.

### Does it work on Apple Silicon?

Yes — M1, M2, M3 and later Macs. QEMU runs the arm64 images with Hypervisor.framework, so labs run
at native speed. Intel Macs and x86-64 Linux use the x86-64 images.

### Does it work on Windows?

Not directly: Lima's Windows support lacks the disk snapshots and serial console the labs rely on.
Run it inside a WSL2 distribution with nested virtualization enabled, where it behaves like Linux.

### Do I need to be online?

To install and to download a base image and a lab, yes. After that, no — labs work without internet,
on a plane or behind a strict firewall, because every package a lab needs is baked into its image, so
labs, theory, journals and local recordings work offline, and so does the tutor on a local Ollama.
Ratings, boards and live sessions need a server, and the TUI says so when there is none.

### Which base images are there, and how big are they?

The labs run on these Linux distributions, each packaged as a golden image: `alpine` (Alpine 3.23,
about 105 MB), `rocky-10` (Rocky Linux 10, about 835 MB), and three on Ubuntu 26.04 LTS:
`ubuntu-26.04` (about 663 MB), `ubuntu-26.04-devops` (Docker, Terraform, Ansible and Python
tooling, about 932 MB) and `ubuntu-26.04-automation` (Ollama with two small models, PostgreSQL,
nginx, about 1.1 GB). Each is the distribution's own cloud image
with a baseline applied by Ansible, pinned by digest. The container labs
build their images locally on first use: `ubuntu-26.04-container`, and `ubuntu-26.04-claude` with Claude Code
2.1.270.

## Tracks and the exam

### What is in the RHCSA track?

Five labs on Rocky Linux 10 following the EX200 objectives: users, groups and permissions; systemd
and the boot; storage and LVM; SELinux, firewalld and networking; and a timed exam simulation.

### Is the exam simulation timed like the real exam?

It is timed: 90 minutes for fifteen tasks, a 70% pass line, an unknown root password to recover first
and no `sudo` for your account. Running over the limit fails a rated attempt. The real exam's length
and task list are set by Red Hat and change between versions; the simulation keeps its style and its
pass line, not its exact content.

### How close is this to the real EX200?

The RHCSA labs follow the published EX200 objectives, quoted verbatim in each lab's manifest, on Rocky
Linux 10, which is binary-compatible with RHEL 10. The tasks are original, not exam content, and the
project is not affiliated with Red Hat.

### Is the RHCSA track affiliated with Red Hat?

No. It is built on Rocky Linux and follows the published EX200 objectives. No Red Hat content is
redistributed.

### What is the automation track about?

Running automation and AI services in production on Ubuntu 26.04: a Python job under systemd, an AI
gateway that leaked its key, an agent job that never stopped, and Ollama four ways — behind nginx for
streamed answers, open to the whole network, a custom model that forgets its rules, and a model too big
for the memory it was given. Separate `bash`, `python`, `ansible`, `docker` and `terraform` tracks have
two labs each on the devops image.

### What is the Claude Code track about?

Claude Code as a machine runs it — in scripts, cron jobs and CI. Six labs, each from a real failure: a
headless job that deleted files and read a token, hooks that never fire, a subagent nobody can call, an
MCP server that never connects, a GitHub Actions job that spends without limit, and settings levels that
disagree. They run in a container with the real Claude Code and a scripted model, so they need no
account, no token and no network, and every check grades what Claude Code actually did.

### What is the MCP track about?

MCP servers as Claude Code meets them, one boundary per lab: a file server that shares more than the
folder it is for, a web page whose hidden text tells the model to run a command, a remote server that
takes a token issued for another service, a stdio server whose log corrupts the protocol, an nginx that
holds a server's event stream back and then cuts it, and a stale server definition in another scope that
answers instead of the team's. Same container and scripted model as the Claude Code track; the servers
are real processes, and Claude Code starts and calls them for real. The `mcp` topic journal and theory
bank go with it.

### What does Ollama do in Norboten?

Two things. On the server it runs a small local model that answers the consultant, so questions about
the docs cost nothing per answer and never leave the machine. In the automation track it is the
subject: the labs deploy it, expose it safely, build custom models with Modelfiles and size its memory,
with `qwen2.5:0.5b` and the `all-minilm` embedding model baked into the image.

## Theory questions

### How are theory questions verified?

Every question carries a reference and an explanation. A question about what a snippet prints carries
the snippet: CI runs it in a container with no network, and its output must equal the answer key.
A question a model generated is checked further: at least two other models that never saw the key
must answer it identically, it must survive a critic, and a maintainer reads it before it goes into
a bank. See
[Theory question spec](../quiz-spec/).

### What does 'verified by two models' mean?

For a drafted question, the writer's answer key is hidden, and at least two different models
solve the question from scratch. If any of them answers differently or calls the question ambiguous,
the question is rejected. It is a filter for questions with a second defensible answer, not a claim
that models are always right — which is why executable questions are also run.

### Can I flag a question that is wrong?

The questions in the repository's banks are files: open an issue or a pull request against the bank,
where the explanation and reference can be checked. Questions you drafted yourself with `g` live in
`~/.norboten/quizzes/`; edit or delete them there.

## Ratings and profiles

### How do ratings work?

Each of the nineteen topics has its own Glicko-2 rating. A rated lab attempt is a game in every topic
the lab declares, against a virtual opponent whose strength comes from the lab's difficulty (1100 for
difficulty 1 up to 1900 for difficulty 5). Passing within the time limit wins; failing or running over
loses. A rated theory run is one game at the mean difficulty of the questions answered.

### What is Glicko-2, and why use it?

A rating system from chess that tracks, besides the rating, how uncertain it is (the rating deviation)
and how volatile a player's results are. It suits Norboten because people attempt labs rarely and
unevenly: a new profile is honestly uncertain and a few results move it a lot, while an established
one moves slowly.

### Why does my rating have a ± on it?

The number after ± is the rating deviation: how far the true value may plausibly be from the shown
one. Every topic starts at 1500 ± 350 and the deviation shrinks as you complete rated attempts in it.
A rating is shown as provisional while the deviation is above 125.

### What makes an attempt rated?

Being a rated lab. The catalogue marks them; they come from the server, need a sign-in, and the
server issues the attempt, starts its clock, and judges the machine's state when you check — the
difficulty, topics and time limit come from the lab, never from your request. An unrated lab is never
rated, however it is started: its checks and its answer are public, so a reported pass would prove
nothing. A rated theory run is a run on a rated bank, which the Theory section marks the same way.

### How long do I get for a lab?

The lab's own `time_limit_minutes` if it sets one (the exam simulation: 90), otherwise by difficulty:
5, 10, 15, 20 or 30 minutes for difficulty 1 to 5. The limit only matters for rated attempts and for
labs that set their own.

Going over time does not stop the machine; you can keep working and check again. But a grade that
comes after the limit is not a pass — the report says it was over time — and for a rated attempt it
counts as a loss in your rating, however many checks passed.

### Does an unrated lab affect my rating?

No. Attempts on unrated labs are recorded in your history but never rated: they are for practice, so
retry as often as you like, and read the solution whenever you want.

### What are the nineteen topics?

`linux-basics`, `users-permissions`, `storage-lvm`, `boot-systemd`, `networking`, `firewall-selinux`,
`kernel-performance`, `logging-journald`, `monitoring`, `bash`, `python`, `ansible`, `terraform`,
`containers`, `ai-services`, `ai-agents`, `claude-code`, `ollama` and `mcp` — derived from the EX200 and EX342
objectives plus the automation and AI subjects.

### How is the radar chart calculated?

One spoke per topic. A topic you have rated attempts in is drawn at its rating, clamped to 1000–2200
and scaled between the centre and the rim; topics you have never attempted sit at the centre, so an
empty spoke means "no evidence", not "bad".

### What is on the contributions heatmap?

A year of activity: one square per day, one column per week, shaded by how many graded lab attempts
and theory runs you completed that day. Hovering a day lists what you did.

## Account and privacy

### Do I need an account?

No. Labs, theory, journals and recordings work without one. An account adds a rating per topic, a
public profile and a place on the boards. There is nothing to create: sign in with GitHub on the
site, or with `a` in the TUI, and the first sign-in makes the account.

### How does signing in work?

With GitHub, and nothing else — no password and no email. On the site, **Sign in with GitHub** takes
you to GitHub and back. In the terminal, `a` shows a short code; open `github.com/login/device` in any
browser, on any device, and type it — so a headless machine signs in the same way. GitHub tells
Norboten your GitHub user id and login, once; the GitHub token that carried them is revoked straight
away and stored nowhere, and no GitHub token ever reaches your terminal. Tick "remember" and you stay
signed in for ninety days; leave it off and it is twelve hours, in that browser tab or that run of
norboten only.

### I have no GitHub account

Then you cannot sign in, for now: GitHub is the only way in. An account is free on GitHub, and
nothing but the rating needs one — every lab, question bank and journal works signed out.

### What does GitHub see, and what does my profile show?

GitHub sees that you signed in to Norboten, and when — nothing Norboten holds. Norboten asks for no
GitHub permissions, only who you are. Your public profile shows your nick and links to your GitHub
account (`github.com/<login>`); if you rename yourself on GitHub, the link follows at your next
sign-in.

### Can I change my nick, or my country?

The country, any time; the nick, no — it is chosen once, when you make your profile. The form opens
with a suggestion for each: your GitHub login for the nick, and for the country a guess from your
address, looked up in an offline table on Norboten's own server (DB-IP Lite, CC BY 4.0) — your address
goes to no other company, and the guess is not saved unless you keep it.

### Where are my tokens stored?

A remembered terminal keeps its token in `~/.norboten/credentials.json`, mode 0600, for 90 days; an
unremembered one keeps it in memory for 12 hours and writes nothing. The site keeps a remembered
token in `localStorage` for 90 days, and otherwise in `sessionStorage`, gone with the tab. The server stores only a SHA-256 hash of each token, so
revoking one — from your account page, or by signing out — deletes a row.

### What does the server know about me?

Your GitHub user id and login, your nick and country, your tokens (hashed), your Discord user id
if you linked Discord, and — only when you are
signed in — graded lab attempts and rated theory runs with their scores, durations and rating changes.
Live sessions you start with `P` are stored for a week. Your local recordings are never sent. [Data model](../data-model/) lists every table.

### Where does my data go?

Nowhere, unless you sign in or stream. Signed in, graded attempts and rated theory runs are sent to the
server. `P` on a lab streams your terminal publicly, after asking. Recordings on the server are deleted
after a week.

### Is telemetry on by default?

No. The TUI sends no telemetry. The API has an opt-in endpoint for anonymous "which check people get
stuck on" reports, which a server operator can turn off entirely, and nothing in the TUI sends to it
unless that option is added and chosen.

## Recording and live sessions

### What is recorded when I record a session with p?

Press `p` on a lab and its shell is recorded and saved in `~/.norboten/plays/`: everything that
crossed the terminal (asciicast v2, which `asciinema play` also reads), the commands you typed with
their times, and a diff of every file change in the VM's watched directories, attributed to the
command that made it. Nothing leaves your machine. `P` saves the same and also streams it live to the
site, after asking; `o` opens a shell without recording.

### Who can watch my live session?

Anyone: other people can see your terminal as you type. `P` streams the session to the site's Live
page, where it is public while it runs and replayable for a week; the TUI asks before it starts. There
is no private streaming mode.

### Can I be told when something happens?

Two things, both off until you ask. On [your account](../../account/), link Discord and
turn on the **weekly digest**: a direct message from the Norboten bot on Sunday evening about your
own week — what you attempted, what your ratings did, and the topic the numbers know least about —
and nothing in a week you did nothing. The bot can only message you if you share a server with it,
so tick "join the Norboten server" when you link (it is off by default) or be in it already, and
allow direct messages from its members; if Discord refuses the message, your account page says so.
A server's operator can also announce live sessions and new labs to a Telegram chat — a chat you
join, not an alert about you. Nobody is subscribed to
anything by default.

### How long are recordings kept?

Recordings you make with `p` stay in `~/.norboten/plays/` until you delete them. Sessions streamed with
`P` are deleted from the server seven days after they started.

### Are the file diffs taken inside the VM?

Yes. While a session records, the guest keeps its watched directories (such as `/etc`) under a git
repository in `/var/lib/norboten/watch`, with the work tree pointing at the real directory so no `.git`
appears there, and takes a diff after each command. Nothing from your host is involved.

## Journals

### Can I read a journal on paper?

Yes. On the site, **Save as PDF** on a journal opens its print view — a light page laid out for A4 —
and your browser's print dialog saves it as a PDF. In the TUI, `e` on a journal (`4`) exports the same
document with running headers and page numbers into `~/.norboten/journals/`; that needs the `pdf`
extra, which uses WeasyPrint: `curl -fsSL https://norboten.org/install.sh | NORBOTEN_EXTRAS=pdf sh`.

### Is there a one-page cheat sheet?

One per journal: the commands for that subject, in one place. **Cheat sheet** on a journal's page opens
it on its own, ready to print — for LVM it is the storage journal's, for `journalctl` the logging
one's. Ask the chat for "a cheat sheet for …" and it links the right one.

## Running and contributing

### Can I write my own lab?

Yes — that is the point of the format. A lab is a directory of scripts, a hint ladder and a reference
solution; `norboten dev lint` checks it without a VM and `norboten dev validate` runs the gate. CI
proves it is solvable before it merges. See [Writing a lab](../writing-a-lab/).

### What does the hosted side cost to run?

One small server rented by the month — a netcup VPS with 2 vCPU and 4 GB — runs the API,
PostgreSQL, Redis, a small local model for the consultant, and monitoring. No hosted model is billed:
the server uses its own Ollama, and theory questions are drafted by the maintainer on a Claude
subscription, then published in the repository. Learners' VMs run on learners' machines, so the
server does not grow with them.

### Can I self-host all of it?

Yes, on your own server or a laptop. `make stack-up` starts the whole backend — the same Docker
Compose project production runs — on a laptop, and [Deploying the server](../deploy/) takes
it to an Ubuntu machine with TLS, backups and deploy-on-push. The TUI uses it with `NORBOTEN_API=…`.
See [Self-hosting](../self-hosting/).

### How do I report a lab that stopped working?

Open an issue in the GitHub repository with the lab id, the base image and what `c` reported (the
TUI keeps the last report in `~/.norboten/sessions/<lab>.last.json`). A lab that stops working is
usually an upstream change, and CI re-runs the gate for every lab whenever an image changes.
