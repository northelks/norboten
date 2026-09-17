---
title: Enabled, masked, wanted — and none of them the same thing
topics: [boot-systemd]
minutes: 40
---

An admin starts the inventory API by hand and it works. The machine reboots and the API is gone,
and now `systemctl start` fails too. Somewhere in the middle of that story is the sentence that
explains the whole lab: **the hand-start worked because a human had already done, once, what
nothing does at boot.**

There are four separate faults on this machine, and they are all the same *kind* of fault — a unit
whose definition does not say what its author thought it said. A drop-in that points at a program
that does not exist. A unit that was masked "temporarily" last month. A dependency that orders two
services without ever asking for the second one. A default target that was changed and never
changed back. None of them is subtle once you know which question to ask systemd; all of them are
invisible if you only read the file you expect to be reading.

## What you should be able to do after this

- Say precisely what `enabled`, `active`, `static` and `masked` each mean, and which of them
  `systemctl start` changes.
- Find a unit's *effective* definition — vendor file plus every drop-in — instead of the file you
  assumed was in charge.
- Write a drop-in that adds a directive, and one that replaces a list-valued directive, and know
  why the second needs an empty assignment first.
- Tell an ordering dependency from a requirement dependency, and pick between `Wants=`,
  `Requires=` and `BindsTo=` on purpose.
- Read `systemctl status` and `journalctl -u … -b` well enough to know why a start failed without
  retrying it.
- Change what the machine boots into, and explain why that is different from changing what it is
  running now.

## The mechanism

### Where units come from, and who wins

The same unit name can be defined in several places, and the search path has a strict order —
first match wins, later directories override earlier ones:

```
/etc/systemd/system/     ← the administrator's. Highest priority. Yours.
/run/systemd/system/     ← runtime, generated; gone at reboot
/usr/lib/systemd/system/ ← the vendor's, shipped by packages. Never edit these.
```

Three ways to change a vendor unit, in increasing order of violence:

1. **A drop-in**: `/etc/systemd/system/<unit>.d/<name>.conf`, holding only the directives you want
   to change. The vendor file is still read; your fragment is merged on top. This survives package
   updates and leaves a record of exactly what you changed.
2. **A full override**: copy the unit into `/etc/systemd/system/` and edit it. Now the vendor file
   is ignored completely — including any improvements it gains later.
3. **A mask**: `/etc/systemd/system/<unit>` as a symlink to `/dev/null`. The unit becomes
   unstartable, by anything, including as a dependency of something else.

Because of all this, never answer the question "what does this unit do?" by reading a file. Ask:

```console
$ systemctl cat inventory-api
# /usr/lib/systemd/system/inventory-api.service
[Unit]
Description=Inventory API
After=network.target config-sync.service
…
# /etc/systemd/system/inventory-api.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/local/bin/inventory-api.py
```

`systemctl cat` prints the vendor file *and every drop-in*, each with the path it came from, in
merge order. `systemd-delta` lists every unit on the system that is overridden or extended, which
is the first command to run on a machine you have inherited. And when you want the merged, resolved
value of one directive rather than the files it came from:

```console
$ systemctl show -p ExecStart --value inventory-api
$ systemctl show -p Wants -p Requires -p After inventory-api
```

`show` is systemd's own view — after merging, after generators, after resolution. It is the ground
truth, and it is what a grader should ask.

### Drop-ins and the empty assignment

Most directives are single-valued: a later assignment replaces an earlier one. Some are
**list-valued** — `ExecStart=`, `After=`, `Wants=`, `Environment=`, `ExecStartPre=` — and there a
later assignment *appends*. To replace a list you must first clear it, by assigning nothing:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/inventory-api.py
```

That is what the break in this lab does, and it is worth recognising because it is also the correct
idiom when you genuinely want to change a command line. The empty line resets the list; the second
line becomes its only member. Remove the empty line and you have declared two `ExecStart=` lines —
which for a `Type=simple` service is a hard error (*"Service has more than one ExecStart= setting,
which is only allowed for Type=oneshot services"*), and the unit will not load at all.

A drop-in also needs its section header. Directives are addressed by section — `Wants=` belongs
under `[Unit]`, `ExecStart=` under `[Service]` — and a fragment that omits the header is not a
subtle mistake, it is a parse error. And after touching any unit file, anywhere:

```console
$ sudo systemctl daemon-reload
```

Until you do, systemd is still running the previous definition, and you are debugging a file the
system has not read.

### Four states, and only one of them means "running"

```console
$ systemctl is-active  inventory-api     # running right now?      active / inactive / failed
$ systemctl is-enabled inventory-api     # will it start at boot?  enabled / disabled / masked / static
$ systemctl is-failed  inventory-api
```

These are independent axes, and conflating them is the most common systemd mistake there is.

**`active`** is now. `systemctl start` and `stop` move a unit along this axis and change nothing
about the next boot.

**`enabled`** is the next boot, and it is nothing more than a symlink. `enable` reads the unit's
`[Install]` section — here `WantedBy=multi-user.target` — and creates:

```console
$ sudo systemctl enable inventory-api
Created symlink /etc/systemd/system/multi-user.target.wants/inventory-api.service →
  /usr/lib/systemd/system/inventory-api.service.
```

That is the entire mechanism: when `multi-user.target` is reached, everything symlinked into its
`.wants` directory is pulled in. A unit with no `[Install]` section cannot be enabled, and
`is-enabled` reports it **`static`** — it exists only to be pulled in by something else, which is
normal for helpers. `enable --now` does both axes in one command, and `disable --now` undoes both.

**`masked`** is a veto. `systemctl mask` links the unit name to `/dev/null` in
`/etc/systemd/system/`, so the highest-priority entry in the search path is "nothing". The unit
cannot be started by hand, by a dependency, or at boot:

```console
$ sudo systemctl start cups
Failed to start cups.service: Unit cups.service is masked.
```

Masking exists because disabling is not always enough — a disabled unit can still be started as
someone else's dependency, or by a socket, or by a timer. It is the right tool for "this must not
run on this machine", and the wrong tool for "not right now", because nobody remembers. Which is
exactly the story in the briefing.

```console
$ systemctl list-unit-files --state=masked      # the question to ask of an inherited machine
$ sudo systemctl unmask config-sync.service     # removes the symlink; does NOT enable anything
```

`unmask` and `enable` are different operations. Unmasking a unit lifts the veto and leaves it
disabled. And note the asymmetry in the other direction: `disable` does not clear a mask, so
reaching for `disable` when the state is `masked` changes nothing and looks like the command
failed.

### Ordering is not causation

This is the heart of the lab. The API's vendor unit says:

```ini
After=network.target config-sync.service
```

and that is *all* it says about config-sync. `After=` is purely an **ordering** statement: it
means "if both of these units are in the same transaction, start me after it finishes". It does not
request config-sync. It does not start config-sync. If nothing else pulls config-sync into the
boot, `After=` is satisfied trivially — there is nothing to wait for — and the API starts with no
config at all.

Requirement dependencies are what actually pull a unit in:

| directive | pulls it in | if it fails | if it stops later |
|---|---|---|---|
| `Wants=` | yes | we start anyway | we keep running |
| `Requires=` | yes | we are not started | we are stopped too |
| `BindsTo=` | yes | we are not started | we stop, even on a clean exit |
| `After=` | **no** | — | — |

And the crucial detail: **none of these imply ordering**. `Requires=` without `After=` starts both
units *in parallel*, which for a config-preparing helper is a race you will lose on a fast machine
and win on a slow one — the worst possible failure mode. The pair you almost always want is:

```ini
[Unit]
Wants=config-sync.service
After=config-sync.service
```

`Wants=` + `After=` says "bring it along, and let it finish first, but do not take me down if it
breaks". `Requires=` + `After=` is the stricter version: correct when the dependency is genuinely
essential — and here the API cannot start without its config, so `Requires=` is defensible. The
trade-off is honest: with `Requires=`, a transient failure in a helper takes your service down with
it, and `Restart=on-failure` will not save you, because the dependency is what failed. Prefer
`Wants=` unless you want that coupling.

There is a second way to express the same thing, from the other side: the helper can declare
`WantedBy=inventory-api.service` in its own `[Install]` section, and enabling it creates the
symlink. Same result, opposite file. Use whichever file you are allowed to change — which is why a
drop-in on the API is usually the answer.

### `Type=oneshot`, and why `/run` is empty at boot

config-sync is a script that copies a file and exits:

```ini
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/config-sync
```

`Type=simple`, the default, means "the process I start *is* the service" — systemd considers the
unit started the moment it forks and finished when the process exits. For a script that does a job
and exits, that produces a unit that is instantly `inactive (dead)`, which makes it look as though
it never ran. `Type=oneshot` waits for the process to exit before considering the unit started,
which is what lets `After=` be meaningful. `RemainAfterExit=yes` then keeps the unit `active
(exited)` afterwards, so `is-active` answers truthfully: *this ran, in this boot*.

And that last phrase is the trap. The script writes to `/run/inventory/config.json`, and `/run` is
a **tmpfs** — a filesystem in memory, empty on every boot, by design. An admin who runs
config-sync by hand leaves the file there, and every manual start of the API works for the rest of
that uptime. The next reboot clears it. `/run` for runtime state that should not survive, `/var`
for state that should: if you are tempted to fix this lab by creating the config by hand, you are
about to reproduce exactly the bug you were called about.

### Targets: what the machine boots into

A target is a unit that groups other units — no process of its own, just dependencies and a
synchronisation point. The boot one is a symlink:

```console
$ systemctl get-default
graphical.target
$ ls -l /etc/systemd/system/default.target
lrwxrwxrwx. 1 root root 40 Sep 13 04:43 /etc/systemd/system/default.target -> /usr/lib/systemd/system/graphical.target
$ sudo systemctl set-default multi-user.target
```

`multi-user.target` is the familiar server state: network up, logins, services. `graphical.target`
pulls in multi-user and adds a display manager — so on a server with no desktop installed it is
usually harmless, which is why a wrong default target can sit unnoticed for a month. Do not assume
harmless, though: it changes which `.wants` directories are consulted, and a unit that is
`WantedBy=multi-user.target` is still reached, while one wanted only by graphical is not reached
under multi-user.

Two neighbours worth separating: `systemctl isolate <target>` switches the *running* system to a
target now and does not touch the default; `set-default` changes the *next* boot and does not touch
what is running. `systemctl list-units --type=target` shows what is active now, and
`systemctl list-dependencies multi-user.target` shows what that state actually consists of.

### Asking why a start failed

In order, and none of them is `start` again:

```console
$ systemctl status inventory-api        # the summary, with the last lines of the log
$ sudo journalctl -u inventory-api -b   # everything this unit logged this boot
$ sudo journalctl -xb -p err            # this boot's errors, with explanatory texts
$ systemctl cat inventory-api           # what the definition actually is
```

The `status` header repays careful reading:

```
× inventory-api.service - Inventory API
     Loaded: loaded (/usr/lib/systemd/system/inventory-api.service; disabled; preset: disabled)
    Drop-In: /etc/systemd/system/inventory-api.service.d
             └─override.conf
     Active: failed (Result: exit-code) since …
    Process: 1643 ExecStart=/usr/local/bin/inventory-api.py (code=exited, status=203/EXEC)
```

`disabled` on the `Loaded:` line answers the boot question. The `Drop-In:` block is the thing
people skim past, and it is the whole answer here. And the exit code is a diagnosis in itself:
`203/EXEC` means systemd could not execute the program — missing file, missing execute bit, or a
bad interpreter on the `#!` line. `200/CHDIR` is a bad `WorkingDirectory=`, `226/NAMESPACE` a
sandboxing directive the system cannot satisfy, and a plain `status=1` means your program ran and
decided to fail, which moves the investigation into the program's own logs.

One more piece of systemd's behaviour to recognise, because it looks like a new fault:

```
inventory-api.service: Start request repeated too quickly.
Failed to start inventory-api.service - Inventory API.
```

`Restart=on-failure` plus a program that fails immediately hits the start rate limit — by default
5 attempts in 10 seconds — and then systemd refuses to try until you clear the counter with
`systemctl reset-failed inventory-api`. Nothing is broken beyond the original fault; the rate limit
is a symptom, not a cause.

## A failure, walked through

`curl localhost:8081/health` refuses the connection.

**1. Ask the unit about itself.**

```console
$ systemctl status inventory-api
○ inventory-api.service - Inventory API
     Loaded: loaded (/usr/lib/systemd/system/inventory-api.service; disabled; preset: disabled)
    Drop-In: /etc/systemd/system/inventory-api.service.d
             └─override.conf
     Active: inactive (dead)
```

Two facts before touching anything: it is **disabled**, which is why the boot did not start it, and
there is a **drop-in**, which means the file in `/usr/lib` is not the whole definition.

**2. Try the start the admin tried, and read the failure rather than repeating it.**

```console
$ sudo systemctl start inventory-api
$ echo $?
0
$ sleep 3 ; systemctl status inventory-api
× inventory-api.service - Inventory API
     Loaded: loaded (/usr/lib/systemd/system/inventory-api.service; disabled; preset: disabled)
    Drop-In: /etc/systemd/system/inventory-api.service.d
             └─override.conf
     Active: failed (Result: exit-code) since Sun 2026-09-13 04:42:29 UTC; 8s ago
    Process: 1643 ExecStart=/usr/local/bin/inventory-api.py (code=exited, status=203/EXEC)
```

Notice the first two lines. `systemctl start` printed nothing and returned 0: for a service with the
default `Type=simple`, the start job succeeds the moment the process is forked, and the failure
arrives a few milliseconds later. A silent `start` is not evidence of anything — always look again.

`203/EXEC`, and a path ending in `.py` that the vendor unit never mentioned. The journal shows
something else as well:

```console
$ sudo journalctl -u inventory-api -b --no-pager | tail -4
… inventory-api.service: Scheduled restart job, restart counter is at 5.
… inventory-api.service: Start request repeated too quickly.
… inventory-api.service: Failed with result 'exit-code'.
… Failed to start inventory-api.service - Inventory API.
```

`Restart=on-failure` retried five times in under two seconds and hit the rate limiter. That is a
symptom, not a second fault. (`sudo`, because an ordinary account cannot read the system journal at
all — without it `journalctl` says *No journal files were opened due to insufficient permissions*.)

**3. Read the effective definition.**

```console
$ systemctl cat inventory-api
# /usr/lib/systemd/system/inventory-api.service
[Unit]
Description=Inventory API
After=network.target config-sync.service

[Service]
ExecStart=/usr/local/bin/inventory-api
Restart=on-failure

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/inventory-api.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/local/bin/inventory-api.py

$ ls -l /usr/local/bin/inventory-api*
-rwxr-xr-x. 1 root root 746 Sep 13 04:42 /usr/local/bin/inventory-api
```

The override resets `ExecStart` and points it at a file that does not exist. The vendor unit was
right all along. Delete the drop-in — it has no other content worth keeping — and reload:

```console
$ sudo rm /etc/systemd/system/inventory-api.service.d/override.conf
$ sudo systemctl daemon-reload
```

**4. Start again — and it works.** This is the dangerous moment:

```console
$ sudo systemctl start inventory-api
$ systemctl is-active inventory-api
active
$ curl -s localhost:8081/health
{"status": "ok", "items": 3}
```

The API needs `/run/inventory/config.json`, and it is there. But who made it?

```console
$ ls -l /run/inventory/
-rw-r--r--. 1 root root 40 Sep 13 04:43 config.json
$ systemctl is-active config-sync ; systemctl is-enabled config-sync
inactive
masked
$ findmnt -no FSTYPE /run
tmpfs
```

The helper that should create it is masked and has not run. The file was left by somebody running
`/usr/local/bin/config-sync` by hand — and `/run` is a tmpfs. This is exactly the briefing's "it works
when an admin starts it, until the next reboot", reproduced. Stopping here fails the lab.

**5. Prove it, by rebooting before you believe it.**

```console
$ sudo reboot
$ ls /run/inventory
ls: cannot access '/run/inventory': No such file or directory
$ sudo systemctl start inventory-api ; sleep 3 ; systemctl is-active inventory-api
failed
$ sudo journalctl -u inventory-api -b --no-pager | tail -5
… inventory-api[1376]:     with open(CONFIG) as f:  # fails at boot unless config-sync ran first
… inventory-api[1376]:          ^^^^^^^^^^^^
… inventory-api[1376]: FileNotFoundError: [Errno 2] No such file or directory: '/run/inventory/config.json'
… systemd[1]: inventory-api.service: Main process exited, code=exited, status=1/FAILURE
… systemd[1]: inventory-api.service: Failed with result 'exit-code'.
```

Now the program runs and fails on its own terms, which is progress: `status=1` with a traceback rather
than `203/EXEC`. Something was supposed to have created that file at boot.

**6. Ask about the helper, and about everything else that is masked.**

```console
$ systemctl list-unit-files --state=masked
UNIT FILE           STATE  PRESET
config-sync.service masked disabled

$ systemctl status config-sync
○ config-sync.service
     Loaded: masked (Reason: Unit config-sync.service is masked.)
     Active: inactive (dead)
```

There is the "temporarily disabled" from the briefing, a month old and still in force.

```console
$ sudo systemctl unmask config-sync.service
Removed '/etc/systemd/system/config-sync.service'.
$ systemctl is-enabled config-sync
static
```

`static`: it has no `[Install]` section, so it cannot be enabled on its own — something has to pull it
in. Which leads to the real design fault.

**7. Ask what will pull it in at the next boot.**

```console
$ systemctl show -p Wants -p Requires -p After inventory-api
Requires=sysinit.target system.slice
Wants=
After=network.target system.slice config-sync.service systemd-journald.socket sysinit.target basic.target
```

`After=config-sync.service` and `Wants=` empty. The API will wait for a unit that nobody starts,
which takes no time at all, and then fail on the missing file. The dependency has to be added, and
a drop-in is the way to add it without editing a vendor file:

```console
$ sudo mkdir -p /etc/systemd/system/inventory-api.service.d
$ printf '[Unit]\nWants=config-sync.service\n' | \
    sudo tee /etc/systemd/system/inventory-api.service.d/deps.conf
$ sudo systemctl daemon-reload
$ systemctl show -p Wants --value inventory-api
config-sync.service
```

The `After=` from the vendor file is still in force, so the ordering is right; the drop-in supplies
the missing half.

**8. Make the boot do it.** Enabled, running, and the default target the runbook asks for:

```console
$ sudo systemctl reset-failed inventory-api
$ sudo systemctl enable --now inventory-api
Created symlink '/etc/systemd/system/multi-user.target.wants/inventory-api.service' → '/usr/lib/systemd/system/inventory-api.service'.
$ systemctl get-default
graphical.target
$ sudo systemctl set-default multi-user.target
Removed '/etc/systemd/system/default.target'.
Created symlink '/etc/systemd/system/default.target' → '/usr/lib/systemd/system/multi-user.target'.
$ curl -s localhost:8081/health
{"status": "ok", "items": 3}
```

Starting the API now also starts config-sync, because of the `Wants=` — which is what recreated the
file in `/run` this time, rather than a human.

**9. Prove it with the only test that counts — again.** Every fix is now a file on disk, so a reboot
should change nothing, and it is the only way to know that `/run` gets repopulated by the helper:

```console
$ sudo reboot
$ systemctl get-default; systemctl is-active config-sync inventory-api
multi-user.target
active
active
$ curl -s localhost:8081/health
{"status": "ok", "items": 3}
```

## Common wrong turns

**Creating `/run/inventory/config.json` by hand.** The API starts, `/health` answers, everything
looks fixed — and `/run` is a tmpfs, so the next boot is back where you started. This is not a
hypothetical wrong turn; it is the one the previous admin took, and it is why the lab exists.

**Editing `/usr/lib/systemd/system/inventory-api.service`.** It works until the package is updated,
and it hides your change from `systemd-delta` and from the next person. Drop-ins in
`/etc/systemd/system/<unit>.d/` are the supported mechanism, and they document themselves in
`systemctl cat`.

**Reading the vendor file and concluding the unit is fine.** It *is* fine. The drop-in is what is
broken, and the only commands that show you both are `systemctl cat` and `systemctl show`. The
`Drop-In:` line in `status` is the hint people skim.

**Removing the `ExecStart=` reset line but keeping the override.** Two `ExecStart=` lines on a
`Type=simple` service is a load error, so now the unit does not exist at all and the error message
changes to something that looks unrelated.

**`systemctl disable config-sync` when it was masked.** Disable does not clear a mask; the state
stays `masked` and the command appears to have done nothing. `unmask` is a different operation —
and conversely, unmasking does not enable, so a unit can be unmasked and still not start at boot.

**Adding `Requires=` without `After=`, or thinking `After=` requests anything.** Requirement and
ordering are orthogonal. `Requires=` alone starts both units in parallel and the API wins the race
on a fast machine; `After=` alone — the state this lab ships in — waits for something nobody
starts. You need one of each.

**Trusting a silent `systemctl start`.** For a `Type=simple` service `start` returns 0 as soon as the
process is forked; the failure appears in `status` a moment later. Look again, every time.

**`systemctl start` and calling it done.** Start is now; enable is next boot. `enable --now` is the
pair. Half of the reboot-persistence failures in this area are exactly this.

**Forgetting `daemon-reload`.** You fix a unit file, start it, and get the old error verbatim,
which makes you doubt the fix. systemd is still running the definition it parsed earlier.

**Fighting the rate limiter.** After a few fast failures, *Start request repeated too quickly* is all
the journal says, and it looks like a second fault. `systemctl reset-failed <unit>`, then fix the real
cause.

**`systemctl isolate multi-user.target` instead of `set-default`.** Isolate changes the running
system and leaves the default alone; the check reads `get-default`, and so does the next boot.

**Writing a drop-in with no section header.** `Wants=config-sync.service` on its own in a
`.conf` file is not a directive, it is a parse error — and `daemon-reload` will say so, quietly, in
the journal.

## Cheat sheet

```console
# what is this unit, really
systemctl cat UNIT                     # vendor file + every drop-in, with paths
systemctl show UNIT                    # every resolved property
systemctl show -p ExecStart --value UNIT
systemctl show -p Wants -p Requires -p After UNIT
systemd-delta                          # everything overridden or extended on this machine

# state, on both axes
systemctl is-active UNIT               # now
systemctl is-enabled UNIT              # next boot: enabled/disabled/masked/static
systemctl status UNIT                  # both, plus the last log lines and the Drop-In: block
systemctl list-unit-files --state=masked
systemctl list-units --failed

# changing state
systemctl start|stop|restart UNIT      # now
systemctl enable|disable UNIT          # next boot (a symlink from [Install])
systemctl enable --now UNIT            # both
systemctl mask|unmask UNIT             # veto / lift the veto (unmask does not enable)
systemctl reset-failed UNIT            # clear the failure and the start-rate counter

# editing
systemctl edit UNIT                    # create/edit a drop-in, then reload automatically
systemctl edit --full UNIT             # copy the vendor unit into /etc and edit that
mkdir -p /etc/systemd/system/UNIT.d && vi /etc/systemd/system/UNIT.d/deps.conf
systemctl daemon-reload                # after ANY unit file change

# dependencies (in [Unit])
Wants=other.service                    # pull it in; do not care if it fails
Requires=other.service                 # pull it in; fail with it
After=other.service                    # ordering only — pulls in NOTHING
# the usual correct pair: Wants= + After=

# targets
systemctl get-default
systemctl set-default multi-user.target        # next boot
systemctl isolate multi-user.target           # now
systemctl list-dependencies multi-user.target

# logs (as root, or as a member of adm / systemd-journal — otherwise journalctl shows nothing)
journalctl -u UNIT -b                  # this unit, this boot
journalctl -u UNIT -f                  # follow
journalctl -xb -p err                  # this boot's errors, explained
journalctl --since '10 min ago'
journalctl -b -1                       # the previous boot
systemd-analyze blame                  # what made the boot slow
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The log lines that were never written down* (topic journal `logging-journald`) — Asking precise questions

Manual pages: `man 1 systemctl`, `man 7 systemd.special`, `man 5 systemd.unit`.

## Review

1. A service is `enabled` but `inactive`, and another is `active` but `disabled`. Describe the
   machine's behaviour on the next reboot for each.

   > The enabled/inactive one starts at boot and is not running now. The active/disabled one is
   > running now and will not come back — `start` and `enable` move independent axes, and
   > `enable --now` is how you set both.

2. `systemctl start config-sync` reports *Unit config-sync.service is masked*. What exists on disk,
   and why is `systemctl disable` not the fix?

   > A symlink `/etc/systemd/system/config-sync.service → /dev/null`. Because `/etc` outranks
   > `/usr/lib` in the unit search path, the unit resolves to nothing and cannot be started by
   > anything. `disable` only removes `.wants` symlinks; you need `unmask` — which lifts the veto
   > and still leaves the unit disabled.

3. A unit declares `After=config-sync.service` and nothing else about it. At boot, what does systemd
   do with config-sync?

   > Nothing. `After=` is ordering only: it says *if* both units are in this transaction, run me
   > second. Nothing requests config-sync, so the ordering is satisfied trivially and the service
   > starts without its config. It needs `Wants=` (or `Requires=`) as well.

4. Why is `Requires=` without `After=` frequently worse than either directive alone?

   > Requirement and ordering are independent, so `Requires=` alone starts both units in parallel.
   > The dependency is pulled in but may not have finished, which is a race — passing on a slow
   > machine and failing on a fast one, or the reverse. Pair the requirement with `After=`.

5. A drop-in contains `ExecStart=` followed by `ExecStart=/usr/local/bin/app.py`. What does the
   empty line do, and what happens if you delete it?

   > `ExecStart=` is list-valued, so a plain assignment appends. The empty assignment clears the
   > list first, making the next line its only member. Delete it and the unit has two `ExecStart=`
   > entries, which is an error for anything but `Type=oneshot` — the unit then fails to load at
   > all.

6. A helper service prepares a file under `/run` and someone fixes a broken machine by creating that
   file by hand. Why does this pass every test until the next boot?

   > `/run` is a tmpfs — memory, emptied at every boot by design. The hand-made file lasts for the
   > current uptime, so manual starts succeed, and disappears at reboot. State that must survive a
   > reboot belongs under `/var`; state that must not belongs in `/run`, prepared by a unit.

7. `systemctl status` shows `status=203/EXEC`. What class of problem is that, and what would
   `status=1` tell you instead?

   > 203/EXEC means systemd could not execute the program at all: the path does not exist, the
   > execute bit is missing, or the `#!` interpreter is wrong. `status=1` means the program was
   > executed and chose to exit non-zero, which moves the investigation from the unit file to the
   > program's own output in `journalctl -u`.

8. What is the difference between `systemctl isolate multi-user.target` and `systemctl set-default
   multi-user.target`, and which one a reboot test will notice?

   > `isolate` changes the currently running system and leaves the boot default alone; `set-default`
   > repoints the `default.target` symlink and changes nothing about the running system. Only
   > `set-default` survives a reboot, and only it changes what `systemctl get-default` reports.
