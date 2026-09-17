# Writing a lab

A lab is a directory. If you can break a machine on purpose and describe how to tell that it is
fixed, you can write one — and CI will tell you the truth about it before a reviewer has to.

Start from `labs/_template/` and read [the specification](../lab-spec/) when a detail
matters. This page is the workflow.

## 1. Pick a failure you have actually seen

The best labs come from an afternoon you lost. A good one has:

- **one story**, not five unrelated faults;
- **symptoms a user would report**, not a topic ("nobody can reach the site", not "SELinux");
- **an honest fix** that a competent admin would make, and that survives a reboot.

Faults that make a lab worse: anything that depends on the wall clock, anything that needs the
internet at runtime, and anything whose only evidence is a file you have to be told about.

**VM or container?** A lab whose fault or fix involves the boot, the kernel, disks, services or the
reboot check is a `vm` lab. A lab entirely about files, users, modes and one program's configuration
can be `runtime: container` on `ubuntu-26.04-container`: it starts in a second and its gate takes
seconds, but it has no reboot pass, no console, and no init system — so no `systemctl` in its break,
check or solution (`linux-05`, `linux-06`).

**A Claude Code lab** is a container lab on `ubuntu-26.04-claude`. Its checks do not call a model: they
import `claude_lab` (installed in the image at `/usr/local/lib/norboten`), give it the model's side of
the conversation as a list of steps — a tool call, or text — and run the learner's job or `claude -p`
against it. The real Claude Code carries out the steps under the machine's settings, hooks, subagents
and MCP servers; the check reads what happened on disk and what Claude Code sent back
(`run.tool_results()`, `run.requests`, `run.denials`). Every step a check scripts should be one a
wrong configuration lets through and a right one refuses — and include one the task genuinely needs,
so locking everything down does not pass (`claude-01` … `claude-06`).

## 2. Copy the template

```sh
cp -r labs/_template labs/linux/linux-07-my-lab
cd labs/linux/linux-07-my-lab
```

```
lab.yaml        the manifest: id, track, difficulty, base images, checks, objectives
briefing.md     what the learner reads — symptoms only, never causes
break/          NN_name.py, each with apply(ctx); idempotent, quiet, root
check/          NN_name.py, each with check(ctx) -> ctx.passed(...) / ctx.failed(...)
hints.yaml      four levels per check; the last one names the problem, never the command
solution/       solution.sh: the reference fix, run as root by CI
files/          anything the scripts copy into the guest (optional)
```

The directory name must equal the `id` in `lab.yaml`, and the `checks:` list must match the files
in `check/` exactly, in order.

## 3. Write the checks first

A check answers one question about the machine and says what it observed:

```python
def check(ctx):
    r = ctx.run(["systemctl", "is-enabled", "--quiet", "notes"])
    if not r.ok:
        return ctx.failed(
            "notes is not set to start at boot.", ctx.run(["systemctl", "status", "notes"]).text
        )
    return ctx.passed("notes starts at boot.")
```

Rules that keep labs honest:

- **Say what was observed, never what to do.** "Nothing is listening on port 8080" — not "run
  `semanage port -a`".
- **Read-only.** The one exception is a probe file named `.norboten-probe-*` that the check removes
  itself, for things you can only prove by doing (can this user actually write there?).
- **Evidence matters.** Attach the command output; the learner can ask for it, and the tutor
  reasons from it.
- **`ctx.facts`** tells you the distribution family (`init`, `pkg`, `mac`), so one check can serve
  Ubuntu and Alpine.

## 4. Write the faults

```python
def apply(ctx):
    ctx.write("/etc/notes/notes.ini", "[notes]\nport = 8080\n", mode=0o600)
```

Break scripts run once, as root, on the clean snapshot, in file order. They must be idempotent,
must leave nothing explaining the fault behind, and may stash values the checks need in
`ctx.state` (a generated UUID, a random port, a secret).

## 5. Write the hint ladder

Four levels per check, and the discipline is the whole point:

1. restate the symptom;
2. name the **kind** of evidence or tool that has not been used;
3. narrow to the component and how to look at it;
4. name the problem — never the command that fixes it.

Levels 1 and 2 may not mention a path the solution touches; the linter enforces that.

Give each level something to read under `refs`: a section of a topic journal or of another lab's
journal (`journal:networking#listening-on-loopback-or-on-everything`), a manual page
(`man 5 systemd.exec`) or official documentation (`https://…`). The learner sees a level's reading
with the hint and opens a journal section with `l`. Your lab's own journal is allowed from level 3,
and no reference may point into a walkthrough — for a lab journal, that section is the fix. The
anchor is the heading as the site names it: lower case, spaces as hyphens, punctuation dropped.

## 6. Write the reference solution

`solution/solution.sh` is a POSIX `sh` script run as root by CI. It must take the broken machine
to a fully passing state, and it must not reboot: the grading reboot does that. `$NORBOTEN_LEARNER`
holds the learner's account name. A lab that supports several base images may add
`solution/<image>.sh`.

## 7. Prove it

```sh
make lint-labs                         # the spec, without a VM
make validate LAB=linux-05-my-lab      # the gate: on every image the lab claims
```

The gate boots a clean VM, applies the faults, asserts that **every check fails**, runs your
solution, then checks, reboots and checks again. A check that passes on the broken machine fails
the gate: it is testing nothing.

While iterating, `norboten dev validate <lab> --keep` leaves the VM up so you can look at it, and
`norboten` (Labs, `Enter`, `s`) plays it as a learner would.

## 8. Send it

One lab per pull request, with the gate green. CI re-runs it on every base image the lab lists.
If your lab needs a package that is not in the golden image, say so in the pull request: adding it
to `images/base/<image>/vars.yml` means rebuilding that image and re-running the gate for every
lab that uses it.

## A rated lab

Everything above holds, with four differences (docs/lab-spec.md §13, docs/rated-labs.md). It lives
in the private repository, `rated/<track>/<id>/`, and sets `rated: true`. Each check is two files:
`collect/NN_name.py` returns what it saw and never decides, and `check/NN_name.py` is
`judge(facts, ctx)`, a pure function the server runs. It has no `journal.md` and no public theory.
And it is committed inside `rated/` first, then as a submodule pointer here. `make validate
LAB=<id>` proves it the same way — the collectors in the VM, the judges on your machine — and
`norboten dev lint rated/<track>/<id>` holds it to the spec.

## Checklist

- [ ] The briefing states symptoms and never causes.
- [ ] Every check fails on the broken machine and passes after the solution — twice, across a reboot.
- [ ] Every check message says what was observed.
- [ ] Hints 1–2 name no path the solution touches; hint 4 names the problem, not the command.
- [ ] Every check's hints carry `refs`, and `make lint-labs` finds every journal anchor.
- [ ] `make lint-labs` and `make validate LAB=…` are green.
- [ ] The lab teaches one thing, and you would not be annoyed to meet it at work.
