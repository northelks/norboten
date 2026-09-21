# Open questions

Things the build plan does not settle, with the decision taken so work could continue. Each entry
is **Open** (needs the maintainer) or **Decided** (a working answer, revisit if wrong).

---

### Q1 — How does a learner reach a VM that has no SSH? · Decided

Lab 3 boots into emergency mode and Lab 5 needs `rd.break` at the bootloader. Lima reaches guests
over SSH, which is not up in either state.

**Decision:** the lab console (`k`, and `b` for the bootloader) attaches to the guest's serial console (QEMU chardev socket that
Lima creates per instance). Golden images put GRUB and the kernel on the serial console and set a
known root password (`norboten`) so the emergency shell's `sulogin` accepts it — on RHEL-family
systems a locked root account refuses the emergency shell entirely, which would make Lab 3
unsolvable. Lab 5 then changes the root password as one of its faults.

### Q2 — VZ or QEMU on macOS? · Decided

Lima defaults to Apple's Virtualization.framework (`vmType: vz`) on macOS. Norboten needs qcow2 disks
it can snapshot with `qemu-img` (a lab reset, < 15 s) and the serial console sockets Lima
creates only for QEMU.

**Decision:** `vmType: qemu` on every host. Doctor requires QEMU and prints the install
command (`brew install qemu`, `apt install qemu-system`, …). Lima itself is downloaded and pinned by
the CLI, QEMU is not — it is a system package with kernel-module dependencies on Linux.

### Q3 — Windows · Open

Lima on Windows uses the WSL2 driver, which has no snapshots and no serial console, so doctor reports
Windows as unsupported for local labs. Running Norboten inside a WSL2 distribution with nested KVM
may work and should be tested before claiming support. There is no hosted fallback (see Q5).

### Q4 — What the hosted side costs · Decided (2026-09-13)

The first plan put the server side on AWS with an EKS cluster for hosted labs; the EKS control
plane alone cost more than a $30 budget. **Decision:** no cloud provider services at all. One
server — a netcup VPS, or any Ubuntu machine — runs the whole
Docker Compose project: Caddy, the API, PostgreSQL, Redis, Ollama, Prometheus and Grafana (n8n was
removed in P15, 2026-09-14). The
server calls no hosted model (decided 2026-09-15), so there is no other running cost.

### Q5 — Hosted lab mode · Dropped (2026-09-13)

Hosted mode would have run a learner's lab VM on the server. A cloud VPS does not expose `/dev/kvm`,
so QEMU there would run without acceleration — unusably slow for a reboot check — and Kubernetes
added an operator's worth of machinery for one feature. **Decision:** labs run only on the learner's
machine. Hosted labs remain possible on a bare-metal server with KVM, and are not built.

### Q6 — "Also the runtime for the two labs that do not need a kernel" · Decided (2026-09-14)

Section 4 of the plan says Docker is the runtime for two kernel-free labs; none existed and
`runtime: container` was a field nothing implemented. Now both exist:
`linux-05-shared-folder-locks-people-out` (groups, modes, setgid, umask, default ACLs) and
`linux-06-log-that-never-rotates` (logrotate's refusals, `su`, `create` versus `copytruncate`). They
run on `ubuntu-26.04-container`, an image of `kind: container` built locally from a Dockerfile, through
`norboten.containers.Container`, which gives the engine, the grader and the gate the same interface a
Lima VM does. Neither has a reboot check, because neither has a boot: the persistence a VM lab proves
by rebooting is, here, a property of files. Each starts in about a second, resets in under one, and
passes the gate in 2–3 s; in CI the gate needs Docker, not KVM.

### Q7 — Redis and Packer · Decided (2026-09-13)

**Redis is load-bearing now**: server-sent events for live sessions subscribe to Redis pub/sub
instead of polling the database, rate limits count
there, and the leaderboard is cached there — all state that must be shared between API workers and
may be lost without harm (docs/data-model.md). **Packer is not used**: the golden image builder boots
the upstream image with Lima (already a dependency), runs the Ansible baseline and exports the disk
with `qemu-img`; Packer's QEMU builder would duplicate that path.

### Q8 — Section references in the plan are off by one · Decided (2026-09-14)

Section 4 of the plan pointed to "section 6" for the agents (they are in 7) and "section 7" for n8n
(it is 8); the solvability gate is Phase 6 in section 11, not "section 8". All three now point where
they should; the other references in the plan (base images and theory questions in 6, the gate
per base in 11, the site in 12) were checked and were already right.

### Q9 — Podman in EX200 for RHEL 10 · Decided

Checked on 2026-09-11 against the official EX200 page (redhat.com/en/services/training/
ex200-red-hat-certified-system-administrator-rhcsa-exam): the exam is based on RHEL 10 and lists
**no container or Podman objectives**. New in the RHEL 10 list: Flatpak repositories and packages.
No Podman lab. RHCSA lab `objectives:` quote the official wording verbatim.

### Q10 — GHCR owner · Decided (provisional)

Images and labs publish to `ghcr.io/northelks/…`. Change `images/registry.yaml` and the publish
workflows together if the project moves to an organisation.

### Q11 — The `intro` track · Decided

The plan binds `rhcsa` to Rocky and `linux` to Ubuntu/Alpine, but `hello` must run on all three
images. The spec adds a third track, `intro`, served by every image and used only by `hello`.

### Q12 — `min_memory` per image · Decided (2026-09-14)

`images/registry.yaml` carried first estimates. `images/memory.py` now measures them: every lab runs
through the solvability gate while a sampler in the guest records MemTotal, MemAvailable and swap
once a second, labelled by gate step, collected before each reboot and before the VM is deleted,
with the kernel's out-of-memory count; `--memory image=size` gives a lab less, which is how a smaller
value is proven.

| Image | min_memory | Peak used (lab, step) | Also passes at | Below that |
|---|---|---|---|---|
| alpine | 256 MiB | 52 MiB (linux-01, boot) | 224 MiB | 192 MiB hangs in UEFI; 128 MiB kernel panic |
| ubuntu-26.04 † | 512 MiB | 106 MiB (linux-02, after the reboot) | 384 MiB | — |
| ubuntu-26.04-devops † | 1 GiB | 324 MiB (docker-01, broken state) | 768 MiB | — |
| ubuntu-26.04-automation † | 3 GiB | 1061 MiB (ollama-02, broken state; re-measured 2026-09-15 after n8n left, 7 labs) | not re-probed; 2 GiB passed with n8n | — |
| rocky-10 | 1536 MiB | 425 MiB (rhcsa-04, the solution) | not probed: the RHCSA labs pin 1536 MiB | — |

All 29 lab × image pairs passed at the registry's values with no swap and no OOM kill. **The
estimates stay**: each keeps at least twice the reference solution's peak, and a learner does more
than the solution does — editors, `man`, a Compose stack of their own, a second model loaded in
Ollama. Lowering them would buy a few hundred megabytes on the host at the price of labs that fail
for a reason the lab is not about. One-second sampling can miss a short spike, which is why the
"also passes at" column, and not the peak, is the evidence for headroom.

† Measured on the image each one replaced when the images moved to Ubuntu 26.04 (2026-09-15); the
values stay until `images/memory.py` has measured the Ubuntu images.

### Q13 — Memory snapshots are broken on Apple Silicon · Decided

Measured on QEMU 11.0.1 with HVF (macOS, M-series): after `savevm` — which is what
`limactl snapshot create` does on a running VM — the next guest reboot hangs in UEFI at 100% CPU,
and starting QEMU with `-loadvm` aborts (`cpu_pre_load: assertion failed`). A plain pause/resume
does not trigger it.

**Decision:** snapshots are disk-only (`qemu-img snapshot`, VM stopped) and a lab reset is
a cold boot from the restored disk. Golden images are tuned to make that fast — GRUB timeout 1 s,
cloud-init limited to NoCloud, and on Alpine no blocking `chronyd initstepslew` (15 s) or dhcpcd
ARP probe (5 s). Measured reset: Alpine 9.8 s, Rocky 9.9 s. Revisit memory snapshots on KVM
hosts, where they may work, once there is a Linux test machine.

### Q14 — The gate and `boot_after_break` · Decided

For a lab whose broken boot never reaches the network (Lab 3's emergency mode), the reference
solution cannot run over SSH after the extra boot. The gate therefore applies the faults and runs
the solution **without** the post-break boot; the grading reboot that follows still proves the fix
survives a boot. The learner-facing broken boot is exercised by hand when a lab is reviewed —
which missed two faults; Q18 closed that gap with a second gate phase.

### Q15 — Upstream mirrors are slow · Decided

`dl.rockylinux.org` delivered ~0.4 MB/s and stalled a Lima download mid-file. The golden image
builder downloads upstream images itself — resumable, retried, digest-verified — into
`~/.norboten/cache/upstream/` and hands Lima a local path.

### Q16 — A vector database · Decided (2026-09-13)

The plan listed pgvector for retrieval and question dedup. Nothing in the stack needed embeddings:
the consultant ranks with BM25 (exact technical terms beat similarity here), question dedup is
textual (difflib against the topic's accepted prompts), and relations between labs, topics,
question banks and journals are computed with TF-IDF, cosine similarity and a networkx graph —
deterministic, explainable, no model. **Decision:** no vector database. pgvector in the same
PostgreSQL stays the next step if semantic similarity ever earns its place; the image would change
from `postgres:17-alpine` to `pgvector/pgvector:pg17` and nothing else.

### Q17 — Which models verify a drafted question · Decided (2026-09-15)

Questions are drafted locally, never on the server. By default the writer is `claude-code/opus` and
the blind solvers `claude-code/sonnet` and `claude-code/haiku`, on the drafter's own Claude Code
subscription. The pipeline requires at least two verifiers that are **not** the writer, so one
vendor still gets independent solves (a different model, a fresh context, no key in the prompt);
exported OpenAI or Gemini keys add another family, the stronger check. The vendor is inferred from
the id prefix.

### Q18 — Faults that do not survive the boot after the break · Decided (2026-09-14)

The consequence of Q14, found by replaying every journal on a real machine (2026-09-13): a fault
that holds right after the break scripts run but not after one more boot passes the gate and is
already gone for the learner. Two labs shipped that way. In rhcsa-03 the held, deleted spool file
died with its process at the boot (fixed: the spooler takes its spool again in a new boot until it
has been restarted). In rhcsa-05 the `Storage=volatile` drop-in was named `50-…` and lost to the
golden image's `90-norboten.conf`, and the deleted `/var/log/journal` is recreated by
systemd-tmpfiles at boot (fixed: `99-retention.conf`).

**Decision:** a second gate phase for `boot_after_break` labs (docs/lab-spec.md §9, steps 5–6). After
the normal gate passes, a fresh VM gets the faults, boots once more exactly as a learner's does, and
every check must still fail. The checks run over SSH when the broken machine has a network. When the
boot stops at a maintenance prompt they run over a serial port: before that boot the gate enables
systemd's `debug-shell.service` on a serial port the guest does not use — Lima's PCI serial port on
aarch64, its virtio console on x86_64, which has no PCI one (found by writing a marker to each guest
tty and seeing which one reaches that port's log) — which gives a root shell in emergency mode
without any password — rhcsa-05 changes the root password, so sulogin with the image's password is
only the fallback. The runner and the checks cross in acknowledged base64 chunks
(`cli/src/norboten/lima/serial_shell.py`).

Verified on rocky-10: rhcsa-03 and rhcsa-05 both stop at the maintenance prompt and pass the phase;
a copy of rhcsa-05 with the old `50-retention.conf` passes every earlier step of the gate and fails
this phase on exactly `12_journal_persistent`. One check needed a declared exemption:
rhcsa-03's `05_held_space_released` cannot fail in emergency mode, where the spooler is not running;
it is marked `maintenance_pass: true` with the reason, and the exemption lapses if a boot ever reaches
the network.

### Q19 — Should the consultant add an embedding rerank? · Decided (2026-09-15)

Retrieval was measured on two held-out sets of learner-style questions. The first set scores 15/16 in
the top three passages, but the corpus has since been edited with it in mind. The second set, which
nothing was tuned for, scores 6/16: BM25 finds a question's exact terms (`lvextend`, `fstab`) and
misses the same question in other words. An embedding model would help with rewording — `all-minilm`
through Ollama gave 0.621 to "disk full" against "no space left on device", which share no words, and
0.228 to an unrelated phrase — at the cost of a second model on the server, an index to rebuild with
the content, and rankings that are harder to explain. **Decision (the maintainer):** keep BM25 alone,
as Q16 and the architecture describe. The 6/16 is a known limit, the test keeps its floor under it,
and the consultant's widget still falls back to the same passages in the browser. Revisit with a
third held-out set if learners' real questions show the misses matter.
