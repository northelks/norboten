---
title: Your shell is not the environment
topics: [python, boot-systemd]
minutes: 35
---

The author is telling the truth: the job works on their machine. They `cd /opt/etl`, they `source
.venv/bin/activate`, they run `python report.py`, and a report appears. What they are actually
describing is a job that depends on four things their shell provides and systemd does not — a current
directory, a Python interpreter with the right libraries, the privileges of whoever is typing, and
somebody remembering to type it.

That is the most common failure in automation, and the name "works on my machine" undersells it. The
job is not broken. **The job has undeclared inputs**, and an interactive shell supplies them silently.
systemd starts a process with almost nothing: working directory `/`, a minimal `PATH`, no activated
virtualenv, and exactly the user and permissions the unit says. Everything the job needs has to be
written in the unit — and once it is, the job works everywhere, including after a reboot with nobody
logged in.

## What you should be able to do after this

- Say what activating a virtualenv actually changes, and run a venv's code without activating anything.
- Recognise the three failures of a relative path under systemd, and fix them with
  `WorkingDirectory=` or by making the program independent of its current directory.
- Run a scheduled job as a dedicated account, with ownership of its data and nothing else.
- Choose between `OnBootSec`/`OnUnitActiveSec` and `OnCalendar`, and enable the right unit.
- Reproduce systemd's environment on demand, instead of reading the journal after each timer tick.
- Protect a token the job reads, and name systemd's cleaner alternatives (`StateDirectory=`,
  `LoadCredential=`).

## The mechanism

### What a virtualenv is, and what `activate` does

A virtual environment is a directory containing a Python interpreter link, a `site-packages` directory,
and a `pyvenv.cfg` file:

```console
$ ls /opt/etl/.venv
bin  include  lib  lib64  pyvenv.cfg
$ ls -l /opt/etl/.venv/bin/python /opt/etl/.venv/bin/python3
lrwxrwxrwx 1 root root  7 Sep 13 05:42 /opt/etl/.venv/bin/python -> python3
lrwxrwxrwx 1 root root 16 Sep 13 05:42 /opt/etl/.venv/bin/python3 -> /usr/bin/python3
$ cat /opt/etl/.venv/pyvenv.cfg
home = /usr/bin
include-system-site-packages = false
version = 3.13.5
executable = /usr/bin/python3.13
command = /usr/bin/python3 -m venv /opt/etl/.venv
```

The interpreter is a symlink to the system Python. What makes it *the venv's* Python is `pyvenv.cfg`
next to it: when Python starts, it looks for that file beside (or one directory above) the executable
it was started as, and if it finds one, sets `sys.prefix` to the venv and puts the venv's
`site-packages` on the import path instead of the system's.

So the venv is selected by **which executable you run** — nothing else. `source .venv/bin/activate` is a
convenience for interactive shells, and all it does is:

- prepend `.venv/bin` to `PATH`, so a bare `python` finds the venv's first;
- set `VIRTUAL_ENV`, and change your prompt;
- define a `deactivate` function to undo it.

It does not change anything about Python itself. Which means that in a unit — or a cron job, or a
Dockerfile — you never need to activate anything. Call the venv's interpreter by path:

```ini
ExecStart=/opt/etl/.venv/bin/python /opt/etl/report.py
```

and the job runs with the venv's packages. Compare with the unit as found:

```ini
ExecStart=/usr/bin/python3 /opt/etl/report.py
```

`/usr/bin/python3` has no `pyvenv.cfg` beside it, so it uses the system `site-packages`, where `httpx`
is not installed:

```console
$ /usr/bin/python3 -c 'import httpx'
ModuleNotFoundError: No module named 'httpx'
$ /opt/etl/.venv/bin/python -c 'import httpx, sys; print(httpx.__version__, sys.prefix)'
0.28.1 /opt/etl/.venv
```

The shebang has the same trap in a different place. `#!/usr/bin/env python3` means "the first
`python3` on `PATH`" — the venv's when the author's shell is activated, the system's everywhere else.
So `./report.py` also behaves differently depending on who runs it. Naming the interpreter in
`ExecStart=` makes the shebang irrelevant.

And the fix is not to install the library system-wide. On Ubuntu 23.04 and later, `sudo pip install
httpx` is refused outright:

```
error: externally-managed-environment
× This environment is externally managed
```

That is PEP 668, and it is protecting you: `pip` writing into `/usr/lib/python3` competes with the
package manager for the same files, and the next `apt upgrade` breaks one or the other. Project
dependencies live in the project's venv; system Python belongs to the system.

### The current directory is an input

```python
settings = json.loads(pathlib.Path("config/settings.json").read_text())
```

`config/settings.json` is relative, so it is resolved against the process's **current working
directory** — not the directory the script lives in. The author runs from `/opt/etl`, where it
resolves to `/opt/etl/config/settings.json`. A system unit with no `WorkingDirectory=` starts in `/`,
where it resolves to `/config/settings.json`:

```
FileNotFoundError: [Errno 2] No such file or directory: 'config/settings.json'
```

Two ways to fix it, and they are not equivalent:

```ini
# tell systemd where to start the process
WorkingDirectory=/opt/etl
```

```python
HERE = pathlib.Path(__file__).resolve().parent
settings = json.loads((HERE / "config" / "settings.json").read_text())  # independent of cwd
```

`WorkingDirectory=` is the operational fix, needs no code change, and is what this lab expects. The code
fix is the better engineering: a program that finds its own files relative to itself works from cron,
from a test runner, from another script, and from a colleague's shell in `/tmp`. Where you control the
code, do both — the unit documents where the job lives, and the code no longer cares.

(With `User=` set and no `WorkingDirectory=`, systemd uses `/` for system services — not the user's home.
`WorkingDirectory=~` asks for the home explicitly.)

### Running as the right account

The unit has no `User=`, so the job runs as **root**. That is a finding on its own — a report generator
that talks to an API over the network does not need to be able to rewrite `/etc/shadow` — and it hides
other bugs: root can read the world-readable token, root can write the root-owned output directory, so
nothing complains. Set the account, and the permission model becomes honest:

```ini
[Service]
User=etl
```

and now the data layout has to be right for `etl`:

```console
$ ls -ld /var/lib/etl/reports
drwxr-xr-x 2 root root 4096 Sep 12 09:02 /var/lib/etl/reports
$ sudo chown -R etl:etl /var/lib/etl
```

The shape to aim for is the usual one: the account **owns what it writes** (`/var/lib/etl`), **can read
what it needs** (`/opt/etl`, readable by all is fine for code), and **owns nothing else**. In
particular the code directory should *not* be writable by the service account — a job that can rewrite
its own code is one exploited dependency away from persistence.

systemd can create and own the state directory for you, which is tidier than a `chown` in a runbook:

```ini
[Service]
User=etl
# creates /var/lib/etl, owned by etl, before starting
StateDirectory=etl
```

`StateDirectory=`, `CacheDirectory=`, `LogsDirectory=` and `RuntimeDirectory=` create
`/var/lib/<name>`, `/var/cache/<name>`, `/var/log/<name>` and `/run/<name>` with the right owner, and
they compose with `DynamicUser=yes` — a transient UID allocated per run, for jobs that need no stable
identity at all.

And a little hardening is nearly free for a job like this:

```ini
# no setuid escalation from inside the job
NoNewPrivileges=yes
# the whole filesystem read-only…
ProtectSystem=strict
# …except where the job writes
ReadWritePaths=/var/lib/etl
# its own /tmp
PrivateTmp=yes
```

`systemd-analyze security etl-report.service` scores a unit's exposure and lists what else could be
tightened, which is a good way to learn what the options do. On this machine, with `User=etl` and no
hardening at all, it ends with *Overall exposure level for etl-report.service: 9.2 UNSAFE* — a score
out of 10, where lower is better, and a long table of what each option would buy.

### The token

```console
$ ls -l /etc/etl/token
-rw-r--r-- 1 root root 33 Sep 12 09:02 /etc/etl/token
```

Every account on the machine can read the metrics API token. Once the job runs as `etl`, the file
needs to be readable by `etl` and nobody else:

```console
$ sudo chown etl:etl /etc/etl/token
$ sudo chmod 600 /etc/etl/token
```

Two refinements worth knowing. `0640 root:etl` is equally private and stops the job rewriting its own
token. And systemd's credential mechanism removes the need for the account to read `/etc` at all:

```ini
# the file can then stay 0600 root:root
LoadCredential=token:/etc/etl/token
```

The job reads `$CREDENTIALS_DIRECTORY/token` — a private in-memory copy only this unit can see. (The
ai-02 journal covers where secrets leak and the options in more depth.)

### Timers: monotonic or calendar, and which unit to enable

```ini
[Timer]
OnBootSec=5s
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

This is a **monotonic** timer — relative to events rather than to the wall clock. `OnBootSec=5s` fires
five seconds after boot; `OnUnitActiveSec=5min` fires five minutes after the service was last
*activated*. Together they mean "shortly after boot, then every five minutes", which is exactly the
requirement. The combination matters: `OnUnitActiveSec=` on its own has nothing to count from until the
service has run once, so a timer with only that directive may never fire at all.

The alternative is `OnCalendar=*:0/5` — at :00, :05, :10 of every hour, on the wall clock, with
`Persistent=true` to catch up after downtime. The differences are real:

| | `OnBootSec` + `OnUnitActiveSec` | `OnCalendar=*:0/5` |
|---|---|---|
| anchored to | boot, and the last run | the clock |
| after downtime | resumes from boot | `Persistent=true` runs a missed one once |
| drift | intervals slide if runs are slow | fixed times |
| many machines | naturally staggered | all fire at once (add `RandomizedDelaySec=`) |

For "every five minutes, whenever" the monotonic form is the natural choice; for "at 02:15" it is
calendar.

Whichever form, **the timer is the unit you enable**. The service is `static` — it has no `[Install]`
section — and is started by the timer. Enabling the timer links it into `timers.target`, which is how it
comes back after a reboot:

```console
$ sudo systemctl enable --now etl-report.timer
Created symlink /etc/systemd/system/timers.target.wants/etl-report.timer → …
$ systemctl list-timers etl-report.timer
NEXT                        LEFT     LAST                        PASSED  UNIT
Sat 2026-09-12 12:14:02 UTC 4min 51s Sat 2026-09-12 12:09:02 UTC 8s ago  etl-report.timer
```

`Type=oneshot` on the service is what makes the timer's notion of "active" meaningful: the service is
activating while the job runs and inactive afterwards, so `OnUnitActiveSec` counts from a real run, and
`systemctl show -p Result -p ExecMainStatus` records how the last run ended.

### Reproduce systemd's environment instead of waiting for it

The slow way to debug a timer job is to change something, wait five minutes, and read the journal. The
fast way is to run the service now:

```console
$ sudo systemctl start etl-report.service       # the real unit, with its real environment
$ sudo journalctl -u etl-report.service -n 20 --no-pager
$ systemctl show -p Result -p ExecMainStatus etl-report.service
```

For a *proposed* configuration, before you write it into the unit, `systemd-run` starts a transient unit
with whatever properties you pass:

```console
$ sudo systemd-run --wait --pipe -p User=etl -p WorkingDirectory=/opt/etl \
    /opt/etl/.venv/bin/python /opt/etl/report.py
wrote /var/lib/etl/reports/latest.json: 3 metrics
Finished with result: success
```

`--wait` blocks until it finishes and prints the result, `--pipe` connects its output to your terminal,
and the process runs under systemd's environment, not your shell's. It is the most direct test of "will
this work from a unit", and it answers in seconds.

`sudo -u etl env -i /opt/etl/.venv/bin/python /opt/etl/report.py` is the poorer relative — same account,
empty environment — but it inherits your current directory, which is exactly the variable you are trying
to eliminate.

## A failure, walked through

No report has ever appeared. The author insists the script works.

**1. Is the timer even running?**

```console
$ systemctl list-timers --all etl-report.timer
NEXT LEFT LAST PASSED UNIT ACTIVATES

0 timers listed.
$ systemctl is-enabled etl-report.timer
disabled
```

The timer is not even listed — nothing has ever enabled or started it, so systemd has not loaded it,
and the job has never been run by systemd at all. Before enabling it,
find out whether the job would work — run the service directly:

**2. Run the service now, and read the first failure.**

```console
$ sudo systemctl start etl-report.service
Job for etl-report.service failed because the control process exited with error code.
See "systemctl status etl-report.service" and "journalctl -xeu etl-report.service" for details.
$ sudo journalctl -u etl-report.service -n 4 --no-pager
… python3[976]: ModuleNotFoundError: No module named 'httpx'
… systemd[1]: etl-report.service: Main process exited, code=exited, status=1/FAILURE
… systemd[1]: etl-report.service: Failed with result 'exit-code'.
… systemd[1]: Failed to start etl-report.service - ETL metrics report.
```

(Unlike a `Type=simple` service, a `Type=oneshot` start waits for the job to finish, so `start`
itself reports the failure. And `journalctl` needs `sudo` — an ordinary account cannot read the system
journal.)

The unit runs `/usr/bin/python3`. The library lives in the venv:

```console
$ systemctl cat etl-report.service | grep ExecStart
ExecStart=/usr/bin/python3 /opt/etl/report.py
$ /opt/etl/.venv/bin/python -c 'import httpx; print("ok")'
ok
```

**3. Try the corrected command under systemd's conditions, before touching the unit.**

```console
$ sudo systemd-run --wait --pipe /opt/etl/.venv/bin/python /opt/etl/report.py
Running as unit: run-p1030-i1330.service; invocation ID: …
Traceback (most recent call last):
  …
FileNotFoundError: [Errno 2] No such file or directory: 'config/settings.json'
Finished with result: exit-code
Main processes terminated with: code=exited, status=1/FAILURE
Service runtime: 59ms
```

The next undeclared input: the current directory. The author always runs from `/opt/etl`; systemd starts
in `/`.

```console
$ sudo systemd-run --wait --pipe -p WorkingDirectory=/opt/etl \
    /opt/etl/.venv/bin/python /opt/etl/report.py
Running as unit: run-p1040-i1340.service; invocation ID: 9e5737abcd9d41cc9737fb002d9f1dbb
wrote /var/lib/etl/reports/latest.json: 3 metrics
Finished with result: success
Main processes terminated with: code=exited, status=0/SUCCESS
```

It works — as root, which is the third problem, and the reason nothing else has complained yet.

**4. Run it as the account it should run as.**

```console
$ sudo systemd-run --wait --pipe -p User=etl -p WorkingDirectory=/opt/etl \
    /opt/etl/.venv/bin/python /opt/etl/report.py
PermissionError: [Errno 13] Permission denied: '/var/lib/etl/reports/latest.json'
Finished with result: exit-code
$ ls -ld /var/lib/etl/reports ; ls -l /etc/etl/token
drwxr-xr-x 2 root root 4096 Sep 13 05:42 /var/lib/etl/reports
-rw-r--r-- 1 root root   33 Sep 13 05:42 /etc/etl/token
```

The output directory belongs to root. Note what did *not* fail: reading the token, because it is
world-readable — the security finding, hiding behind a working read. Fix both:

```console
$ sudo chown -R etl:etl /var/lib/etl
$ sudo chown etl:etl /etc/etl/token && sudo chmod 600 /etc/etl/token
$ sudo systemd-run --wait --pipe -p User=etl -p WorkingDirectory=/opt/etl \
    /opt/etl/.venv/bin/python /opt/etl/report.py
wrote /var/lib/etl/reports/latest.json: 3 metrics
Finished with result: success
```

**5. Write what worked into the unit**, as a drop-in, with the empty `ExecStart=` to replace rather
than append (see the rhcsa-02 journal):

```console
$ sudo mkdir -p /etc/systemd/system/etl-report.service.d
$ sudo tee /etc/systemd/system/etl-report.service.d/run.conf >/dev/null <<'UNIT'
[Service]
User=etl
WorkingDirectory=/opt/etl
ExecStart=
ExecStart=/opt/etl/.venv/bin/python /opt/etl/report.py
UNIT
$ sudo systemctl daemon-reload
$ sudo systemctl start etl-report.service
$ systemctl show -p Result -p ExecMainStatus -p User etl-report.service
Result=success
ExecMainStatus=0
User=etl
$ cat /var/lib/etl/reports/latest.json
{"generated_at": "2026-09-13T05:42:57+00:00", "count": 3, "total": 478}
```

**6. Enable the timer — not the service.**

```console
$ sudo systemctl enable etl-report.service
The unit files have no installation config (WantedBy=, RequiredBy=, UpheldBy=,
Also=, or Alias= settings in the [Install] section, and DefaultInstance= for
template units). This means they are not meant to be enabled or disabled using systemctl.
$ sudo systemctl enable --now etl-report.timer
Created symlink '/etc/systemd/system/timers.target.wants/etl-report.timer' → '/etc/systemd/system/etl-report.timer'.
$ systemctl list-timers etl-report.timer
NEXT LEFT LAST                         PASSED UNIT             ACTIVATES
-       - Sun 2026-09-13 05:42:57 UTC 7ms ago etl-report.timer etl-report.service
```

The first command is the wrong turn, shown so you recognise its answer. The second is the fix. Note
what the timer did the moment it started: `OnBootSec=5s` had long since elapsed, so it fired
immediately — `LAST` is 7 ms ago, and `NEXT` stays `-` until that run finishes and
`OnUnitActiveSec=5min` has something to count from.

**7. Reboot, log nothing in, and let the timer prove it.** The requirement is "without anyone logged in",
so the test is a boot followed by patience, not a manual start:

```console
$ sudo reboot
  (wait ~30 seconds)
$ systemctl list-timers etl-report.timer          # LAST: a few seconds after boot
$ systemctl show -p Result -p ExecMainStatus etl-report.service
Result=success
ExecMainStatus=0
$ stat -c '%y' /var/lib/etl/reports/latest.json ; uptime -s    # the report must be the younger
$ stat -c '%a %U' /etc/etl/token
600 etl
```

A report newer than the boot, written by systemd as `etl`, is the proof — which is exactly what the
grader's post-reboot pass checks, and on this machine it passed.

## Common wrong turns

**Putting `source /opt/etl/.venv/bin/activate` in `ExecStart=`.** `ExecStart=` is not a shell: `source`
is a shell builtin, and systemd will look for an executable called `source`. Wrapping it in
`/bin/bash -c 'source … && python report.py'` works and is pointless — activating only changes `PATH`.
Run `/opt/etl/.venv/bin/python` directly.

**`sudo pip install httpx` system-wide.** On Ubuntu 26.04 pip refuses (`externally-managed-environment`),
and `--break-system-packages` is named that way for a reason: it puts pip and apt in charge of the same
files. Project dependencies belong in the project's venv.

**Relying on the shebang.** `#!/usr/bin/env python3` picks whichever `python3` is first on `PATH`, which
is the venv only in an activated shell. Name the interpreter in `ExecStart=`.

**Fixing the relative path by `cd` in a wrapper script.** It works, and it adds a file whose only job is
what `WorkingDirectory=` does in one line. Better still, make the program resolve paths relative to
`__file__`.

**Testing as root.** Root reads the world-readable token and writes the root-owned directory, so every
permission problem stays hidden until the unit gets `User=`. Test with `-p User=etl` from the start.

**`chmod 777 /var/lib/etl/reports`.** It fixes the write, and lets every account on the machine replace
the report that something downstream presumably trusts. `chown` the directory to the account that
writes it.

**Making `/opt/etl` owned by `etl`.** The job needs to *read* its code, not rewrite it. A service
account that can modify its own code gives any compromise of the job a way to persist.

**`chmod 600` on the token without `chown`.** A `0600 root:root` token is private and unreadable by
`etl`: the job now fails with `PermissionError` on the token instead of the report. Own it by the
account (or `0640 root:etl`, or `LoadCredential=`).

**Enabling `etl-report.service`.** It has no `[Install]` section, so `enable` fails with a warning about
a static unit — or, if someone adds `WantedBy=multi-user.target` to make the warning go away, it runs
once at boot and never again. The timer is what you enable.

**A timer with only `OnUnitActiveSec=`.** It counts from the service's last activation, and after a
boot there is none, so the timer may never fire. Pair it with `OnBootSec=` (or `OnActiveSec=`), or use
`OnCalendar=`.

**Waiting five minutes after every change.** `systemctl start etl-report.service` runs the job now with
its real environment, and `systemd-run --wait --pipe -p …` tries a configuration before you commit it
to a file.

**Forgetting `daemon-reload` after writing the drop-in.** The next start uses the old definition and
fails exactly as before, which makes a correct fix look wrong.

**Declaring success after a manual start.** The requirement is an unattended run after a reboot. A
report written by your `systemctl start` proves the unit, not the timer — check that the report is newer
than the boot and that `list-timers` shows a `LAST` you did not cause.

## Cheat sheet

```console
# the venv
/opt/etl/.venv/bin/python -c 'import sys, httpx; print(sys.prefix)'   # the venv is chosen by the EXECUTABLE
cat /opt/etl/.venv/pyvenv.cfg                    # what makes that symlink "the venv's python"
/opt/etl/.venv/bin/pip install -r requirements.txt    # dependencies go here, never into /usr
# activate = PATH + VIRTUAL_ENV + prompt. Not needed in units, cron or containers.

# a unit for a Python job
# [Service]
# Type=oneshot
# User=etl
# WorkingDirectory=/opt/etl                        (default for system units is /)
# ExecStart=/opt/etl/.venv/bin/python /opt/etl/report.py
# StateDirectory=etl                               (creates /var/lib/etl owned by etl)
# LoadCredential=token:/etc/etl/token              (→ $CREDENTIALS_DIRECTORY/token)
# NoNewPrivileges=yes  ProtectSystem=strict  ReadWritePaths=/var/lib/etl  PrivateTmp=yes
systemd-analyze security etl-report.service

# the timer
# [Timer] OnBootSec=5s  OnUnitActiveSec=5min      (monotonic: after boot, then after each run)
#         OnCalendar=*:0/5  Persistent=true        (wall clock; RandomizedDelaySec= on fleets)
# [Install] WantedBy=timers.target
systemctl enable --now etl-report.timer          # the TIMER; the service is static
systemctl list-timers --all etl-report.timer     # NEXT / LAST (a never-started timer is not listed)

# run it the way systemd runs it
systemctl start etl-report.service               # now, with the unit's real environment
systemd-run --wait --pipe -p User=etl -p WorkingDirectory=/opt/etl CMD   # try a config first
sudo journalctl -u etl-report.service -b -n 20 --no-pager
systemctl show -p Result -p ExecMainStatus -p User etl-report.service

# ownership
chown -R etl:etl /var/lib/etl                    # what it writes
chown etl:etl /etc/etl/token ; chmod 600 /etc/etl/token   # what only it reads
# code in /opt/etl: readable, NOT writable by the service account

# proving "unattended"
stat -c '%y' /var/lib/etl/reports/latest.json ; uptime -s    # report newer than the boot
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Nine letters and a refusal* (lab journal `hello`) — How the kernel picks a triad

Manual pages: `man 5 systemd.timer`, `man 5 systemd.exec`.

Documentation:

- https://docs.python.org/3/library/venv.html

## Review

1. What does `source .venv/bin/activate` change, and why does that make it unnecessary in a systemd
   unit?

   > It prepends `.venv/bin` to `PATH`, sets `VIRTUAL_ENV`, changes the prompt and defines `deactivate` —
   > nothing about Python itself. The venv is selected by which interpreter executable is started, via
   > the `pyvenv.cfg` beside it, so `ExecStart=/opt/etl/.venv/bin/python …` gets the venv's packages with
   > no activation.

2. The script's shebang is `#!/usr/bin/env python3`. Why does `./report.py` behave differently for the
   author and for systemd?

   > `env` runs the first `python3` on `PATH`. In the author's activated shell that is the venv's; for
   > systemd, with a minimal `PATH`, it is `/usr/bin/python3`, which lacks the project's libraries. Naming
   > the interpreter explicitly removes the dependency on `PATH`.

3. `Path("config/settings.json")` works from the author's shell and fails under systemd. Give the unit
   fix and the code fix, and say which is better engineering.

   > The unit fix is `WorkingDirectory=/opt/etl`, since a system unit otherwise starts in `/`. The code fix
   > is to resolve relative to the script — `Path(__file__).resolve().parent / "config" / "settings.json"` —
   > which makes the program independent of its current directory wherever it is run from. The code fix
   > is better; doing both is best.

4. Why does running the job as root hide bugs, beyond being a security finding?

   > Root bypasses permission checks, so a world-readable token and a root-owned output directory both
   > "work". The moment the unit gets `User=`, those problems appear. Testing as the real account from
   > the start surfaces them before they become a failed night.

5. Which unit do you enable for a scheduled job, and what goes wrong if you enable the other one?

   > The `.timer`, which is `WantedBy=timers.target`. The service has no `[Install]` section and is
   > `static`; enabling it fails, and adding `WantedBy=multi-user.target` to force it makes the job run
   > once at boot and never again.

6. Why might a timer with only `OnUnitActiveSec=5min` never fire, and what pairs with it?

   > It counts from the service's last activation, and after boot there has been none, so there is
   > nothing to count from. Pair it with `OnBootSec=` (or `OnActiveSec=`) for the first run, or use
   > `OnCalendar=`.

7. How do you test a proposed unit configuration without editing the unit or waiting for the timer?

   > `systemd-run --wait --pipe -p User=etl -p WorkingDirectory=/opt/etl <command>` runs it as a
   > transient unit under systemd's environment, streams the output and reports the result. For the unit
   > as written, `systemctl start <service>` runs it immediately.

8. What does `StateDirectory=etl` do, and why is it preferable to a `chown` step in a runbook?

   > systemd creates `/var/lib/etl` before starting the service, owned by the unit's `User=`, and keeps
   > the ownership correct across restarts. The requirement lives in the unit itself rather than in a
   > manual step someone must remember — and it also works with `DynamicUser=yes`.
