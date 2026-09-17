---
title: The limits nobody set, and the numbers everybody misreads
topics: [kernel-performance]
minutes: 40
covers: >-
  RLIMIT_* inherited from units, shells and pam_limits; /proc/PID/limits; free's available column; the machine's and a cgroup's OOM killer (memory.max, memory.events); load average and D state; sysctl -w, sysctl.d and tuned
---

A service falls over under load with *Too many open files*. Somebody raises the limit in
`/etc/security/limits.conf`, logs in, runs `ulimit -n`, sees the new number, and closes the ticket. The
next busy afternoon it falls over again, at exactly the same point. Nothing they did was wrong, exactly
— they changed a real limit, for a place the service never runs.

Performance problems on a Linux server are mostly this: not exotic kernel behaviour, but limits and
counters that apply somewhere other than where you looked, and numbers — "free memory", "load
average", a sysctl value — whose meaning is narrower than their name. This journal takes the ones that
cause real incidents, and every figure in it was measured on a Rocky Linux 10 lab machine with one
vCPU and 1.4 GiB of RAM.

## What you should be able to do after this

- Find the resource limits a *running process* actually has, and set them for a systemd service in the
  place that applies to it.
- Read `free` and say how much memory the machine can really still give out.
- Recognise an OOM kill, tell a cgroup's limit from the whole machine running out, and read the kernel's
  report.
- Explain what load average counts, and what it means relative to the number of CPUs.
- Make a sysctl change that survives a reboot, on a machine where `tuned` also sets sysctls.
- Know which pressure and memory statistics exist on RHEL by default, and which do not.

## The mechanism

### Limits belong to processes, and are inherited

Every process carries a set of resource limits — open files, processes, locked memory, core size — as a
**soft** value (what is enforced) and a **hard** value (the ceiling the soft value may be raised to
without privilege). They are inherited from the parent at `fork`, which is the whole explanation for
the ticket above: the limit a process has depends on *who started it*.

The only reliable way to know is to ask the process:

```console
$ grep "open files" /proc/$(systemctl show -p MainPID --value fdhog)/limits
Max open files            8192                 8192                 files
```

On the lab machine, a login shell and a systemd service started with the same numbers:

```console
$ ulimit -n ; ulimit -Hn
1024
524288
$ systemctl show -p LimitNOFILE -p LimitNOFILESoft fdhog
LimitNOFILE=524288
LimitNOFILESoft=1024
```

A soft limit of 1024 open files. A small stand-in server that opens one file per "connection" stopped
at the same point in both places:

```
after 1021 open files: [Errno 24] Too many open files: '/dev/null'
```

1021, not 1024, because standard input, output and error are three of them.

### Where each limit is set

Two separate systems set limits, for two separate kinds of process:

- **PAM** (`pam_limits`) applies `/etc/security/limits.conf` and `/etc/security/limits.d/*.conf` when a
  *session* starts — an SSH login, `su -`, `sudo -i`, a console login.
- **systemd** sets the limits of the services it starts, from `LimitNOFILE=`, `LimitNPROC=` and friends
  in the unit (and `DefaultLimitNOFILE=` in `/etc/systemd/system.conf`). Services are not PAM sessions,
  and `limits.conf` never touches them.

Verified on the lab machine, with the service running as `webapp`:

```console
$ echo "webapp soft nofile 8192" | sudo tee /etc/security/limits.d/90-webapp.conf
$ sudo su - webapp -c 'ulimit -n'
8192
$ sudo systemctl restart fdhog            # User=webapp
$ sudo journalctl -u fdhog -n 1
fdhog[3288]: after 1021 open files: [Errno 24] Too many open files: '/dev/null'
```

The account's sessions got 8192; the account's service still stopped at 1021. The limit belongs in the
unit:

```ini
# /etc/systemd/system/fdhog.service.d/limits.conf
[Service]
LimitNOFILE=8192
```

```console
$ sudo systemctl daemon-reload && sudo systemctl restart fdhog
$ sudo journalctl -u fdhog -n 1
fdhog[3371]: held 5000 files fine
$ grep "open files" /proc/$(systemctl show -p MainPID --value fdhog)/limits
Max open files            8192                 8192                 files
```

`LimitNOFILE=8192` sets soft and hard together; `LimitNOFILE=8192:524288` sets them separately. A
restart is required: limits are applied when the process starts, and a running process keeps the ones
it was born with (`prlimit --pid PID --nofile=…` can change them live, which is a repair, not a
configuration).

### `free`: the column that matters is `available`

```
               total        used        free      shared  buff/cache   available
Mem:            1449         328         992           0         197        1121
```

`free` is memory doing nothing at all. Linux does not like idle memory and fills it with page cache —
recently read files — which it gives back the moment a process needs it. So `free` shrinks on a healthy
machine, and `available` is the kernel's estimate of what could be handed out right now without
swapping. Measured: reading a 600 MiB file

```
Mem:            1449         325         395           0         797        1123
```

took `free` from 992 to 395 MiB and left `available` where it was. Deleting the file gave the cache
straight back:

```
Mem:            1449         325         995           0         197        1123
```

A machine "down to 395 MiB free" was, in every sense that matters, exactly as healthy as before. Alert
on `available`, never on `free`. (The lab machine has no swap — `Swap: 0B 0B 0B` — which means there is
nowhere to push idle anonymous memory, and the OOM killer is the next step after `available` reaches
zero.)

### OOM: the machine's, or the cgroup's

When memory cannot be found, the kernel's OOM killer picks a process and kills it with `SIGKILL`. There
are two very different situations that produce it, and the kernel's report says which.

systemd services run in their own cgroup, and `MemoryMax=` caps that cgroup. A stand-in service that
grows a cache by 10 MiB a second, capped at 100 MiB:

```ini
[Service]
ExecStart=/usr/local/bin/memhog
MemoryMax=100M
```

```console
$ systemctl status memhog
× memhog.service
     Active: failed (Result: oom-kill) since Sun 2026-09-13 08:27:08 UTC; 4s ago
   Duration: 9.114s
    Process: 3530 ExecStart=/usr/local/bin/memhog (code=killed, signal=KILL)
$ sudo journalctl -u memhog -b
memhog[3530]: cache 90 MiB
systemd[1]: memhog.service: A process of this unit has been killed by the OOM killer.
systemd[1]: memhog.service: Main process exited, code=killed, status=9/KILL
systemd[1]: memhog.service: Failed with result 'oom-kill'.
systemd[1]: memhog.service: Consumed 45ms CPU time, 100M memory peak.
```

`Result: oom-kill` and `signal=KILL`: the program never had a chance to log anything — its last line is
a normal progress message. The kernel's own account is in the kernel log:

```console
$ sudo journalctl -k -b | grep -i 'out of memory\|oom-kill'
kernel: oom-kill:constraint=CONSTRAINT_MEMCG,…,oom_memcg=/system.slice/memhog.service,
  task_memcg=/system.slice/memhog.service,task=memhog,…
kernel: Memory cgroup out of memory: Killed process 3530 (memhog) total-vm:115040kB,
  anon-rss:101988kB, file-rss:5232kB, shmem-rss:0kB, UID:0 …
```

Read two things. `constraint=CONSTRAINT_MEMCG` and *Memory cgroup out of memory* mean a cgroup limit
was hit — the machine as a whole had plenty (`available` was over a gigabyte). The same service with no
`MemoryMax=`, growing 100 MiB a second, took the whole machine to the edge instead:

```
kernel: oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,global_oom,
  task_memcg=/system.slice/memhog.service,task=memhog,pid=1745,uid=0
kernel: Out of memory: Killed process 1745 (memhog) total-vm:1343852kB, anon-rss:1262068kB, …
```

`CONSTRAINT_NONE`, `global_oom`, *Out of memory*: the machine ran out. Here the killer chose the right
process because it was by far the biggest; it picks by size and `oom_score_adj`, not by who is to
blame, and on a machine with a large, innocent database it can choose that instead. `anon-rss:101988kB` is the resident
anonymous memory at the moment of death — the real size of the leak.

A limit turns "the machine fell over" into "one service was killed and reported why". Pair it with
`Restart=on-failure` and an alert on `Result=oom-kill`, and a slow leak becomes a restart every few hours
and a ticket, instead of an outage.

### Load average counts waiting, not busy

```console
$ cat /proc/loadavg
2.25 0.75 0.27 4/147 1599
$ nproc
1
$ vmstat 1 2 | tail -1
 3  0      0 1038668   6052 196768    0    0     0     0  109  150 100  0  0  0  0  0
```

Load average is an exponentially decaying average, over 1, 5 and 15 minutes, of the number of tasks
that are **running or waiting to run**, plus those in uninterruptible sleep (usually waiting on disk or
NFS). That snapshot was taken 65 seconds after starting three busy loops on a one-CPU machine:
`vmstat`'s first column, `r`, says three tasks are runnable, CPU is 100% user, and the 1-minute load has
climbed to 2.25 on its way towards 3 — it lags, by design.

Two consequences. A load of 3 means something only next to the CPU count: on this machine two tasks are
always waiting; on a 16-core machine it is idle. And load can be high with idle CPUs, when the tasks are
stuck in `D` state on a slow disk — `vmstat`'s `b` column and `wa` counter tell that case apart.

### sysctls: `-w` is for now, files are for later, and tuned is also writing

```console
$ sysctl vm.swappiness
vm.swappiness = 30
```

The kernel's default is 60. On this machine 30 comes from **tuned**, which applies a profile at boot:

```console
$ tuned-adm active
Current active profile: virtual-guest
$ grep -v '^#' /usr/lib/tuned/profiles/virtual-guest/tuned.conf | grep -v '^$'
[main]
summary=Optimize for running inside a virtual guest
include=throughput-performance
[vm]
dirty_bytes = 30%
[sysctl]
vm.swappiness = 30
```

`sysctl -w` changes the running kernel only. Files in `/etc/sysctl.d/` are applied at boot, and
`sysctl --system` applies them now, in order:

```console
$ sudo sysctl -w vm.dirty_ratio=33
$ echo "vm.swappiness = 5" | sudo tee /etc/sysctl.d/90-app.conf
$ sudo sysctl --system
* Applying /etc/sysctl.d/90-app.conf ...
* Applying /etc/sysctl.d/99-sysctl.conf ...
* Applying /etc/sysctl.conf ...
vm.swappiness = 5
```

After a reboot:

```console
$ sysctl vm.swappiness vm.dirty_ratio
vm.swappiness = 5
vm.dirty_ratio = 30
```

The file survived; the `-w` did not — `dirty_ratio` is back to tuned's 30, not the kernel's 20. And the
file won over tuned because tuned's `reapply_sysctl = 1` (in `/etc/tuned/tuned-main.conf`) re-applies
the system's sysctl files after its own profile. On a machine where that has been turned off, the
profile wins, and a correct `sysctl.d` file appears to be ignored. When a value will not stick, ask
`tuned-adm active` before anything else, and change the profile (a custom profile in
`/etc/tuned/<name>/`) rather than fighting it.

### What is not there by default

Pressure stall information (`/proc/pressure/cpu|memory|io`, and `memory.pressure` in each cgroup) is the
best single signal for "is this machine starved" — and on the Rocky 10 lab machine it did not exist:

```console
$ ls /proc/pressure
ls: cannot access '/proc/pressure': No such file or directory
```

The kernel config says why: `CONFIG_PSI=y` and `CONFIG_PSI_DEFAULT_DISABLED=y` — built in, off unless
the kernel command line says `psi=1`.
Before building monitoring around it, check that it is there; before concluding a guide is wrong, check
the boot parameter.

## A failure, walked through

A small service opens a file per request. It passed its tests. Under a load test it logs *Too many open
files* and stops serving. A colleague has already "raised the limit".

**1. Look at what the colleague changed.**

```console
$ cat /etc/security/limits.d/90-webapp.conf
webapp soft nofile 8192
$ sudo su - webapp -c 'ulimit -n'
8192
```

Correct, and for sessions. The service is not a session.

**2. Ask the process, not the shell.**

```console
$ systemctl show -p User -p LimitNOFILE -p LimitNOFILESoft fdhog
User=webapp
LimitNOFILE=524288
LimitNOFILESoft=1024
$ sudo journalctl -u fdhog -n 1
fdhog[3288]: after 1021 open files: [Errno 24] Too many open files: '/dev/null'
```

Soft limit 1024 from systemd; three descriptors already used for stdio; 1021 more and `EMFILE`. The
number in the error log and the number in the unit agree, which is the proof.

**3. Set it where it applies, and restart.**

```console
$ sudo mkdir -p /etc/systemd/system/fdhog.service.d
$ printf '[Service]\nLimitNOFILE=8192\n' | sudo tee /etc/systemd/system/fdhog.service.d/limits.conf
$ sudo systemctl daemon-reload && sudo systemctl restart fdhog
$ sudo journalctl -u fdhog -n 1
fdhog[3371]: held 5000 files fine
$ pid=$(systemctl show -p MainPID --value fdhog)
$ grep "open files" /proc/$pid/limits ; sudo ls /proc/$pid/fd | wc -l
Max open files            8192                 8192                 files
5003
```

5000 held files plus stdio, under a limit of 8192.

**4. Check the next limit before the load test finds it.** Raising one ceiling moves the failure to the
next one. For this service the next is memory: each connection costs something. Cap it, so a runaway
becomes a clean kill rather than a machine-wide OOM:

```ini
[Service]
LimitNOFILE=8192
MemoryMax=300M
Restart=on-failure
```

and confirm what an OOM looks like before production shows you: `systemctl status` says
`Result: oom-kill`, and `journalctl -k` says `Memory cgroup out of memory` with the cgroup's name.

**5. Leave the `limits.d` file or remove it — but know what it is for.** It is correct for people who
log in as `webapp` and run things by hand. It never affected the service.

## Common wrong turns

**Raising `limits.conf` for a service.** PAM applies it to login sessions; systemd services never see
it. Set `LimitNOFILE=` in the unit.

**Checking `ulimit -n` in your shell to verify a service's limit.** Your shell's limits came from your
session. Read `/proc/PID/limits` of the service's main process.

**Changing the unit and not restarting.** Limits are fixed when the process starts. `daemon-reload` plus
`restart`, then read `/proc/PID/limits` again.

**Alerting on `free` memory.** Page cache makes `free` fall on every healthy machine. Measured, reading
one large file cut `free` by 600 MiB and left `available` unchanged. Watch `available`.

**Reading an OOM kill in the application log.** A `SIGKILL` leaves no last words. The evidence is
`Result: oom-kill` in `systemctl status` and the kernel's report in `journalctl -k`.

**Assuming an OOM means the machine ran out.** `CONSTRAINT_MEMCG` / *Memory cgroup out of memory* is a
cgroup limit, often with plenty of memory free elsewhere. Raise the limit or fix the leak — not the
machine.

**Comparing load average without the CPU count.** 2.25 on one CPU is a queue; on sixteen it is idle.
And high load with idle CPUs is tasks waiting on I/O — look at `vmstat`'s `b` and `wa`.

**`sysctl -w` as a fix.** Gone at the next boot; measured, `dirty_ratio` reverted to the tuned profile's
value. Put it in `/etc/sysctl.d/`, apply with `sysctl --system`.

**Fighting tuned with sysctl files.** It works only while tuned re-applies system sysctls
(`reapply_sysctl = 1`). Check `tuned-adm active`; change or create a profile instead.

**Building alerts on `/proc/pressure` without checking it exists.** On RHEL-family kernels PSI is off
unless the command line has `psi=1`.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| "Too many open files" under load, fine in testing | the process's `RLIMIT_NOFILE`, inherited from the unit or the shell | `cat /proc/PID/limits`; `LimitNOFILE=` in the unit |
| a limit set in `limits.conf` has no effect on a service | `pam_limits` applies to logins; units take limits from their own settings | `systemctl show -p LimitNOFILE UNIT` |
| a process is killed with no message in its own log | the OOM killer — the machine's, or its cgroup's `memory.max` | `journalctl -k -g oom`; `memory.events` in the unit's cgroup |
| `free` shows almost no free memory on a healthy machine | page cache: `available`, not `free`, is what can be used | `free -h`, the `available` column |
| load average is high and CPUs are idle | tasks waiting on I/O count towards load | `vmstat 1` (`b`, `wa`); processes in state `D` in `ps -eo stat,comm` |
| a sysctl reverts after reboot, or after a daemon starts | set with `-w` only, or overwritten by a tuned profile | `sysctl NAME`; `/etc/sysctl.d/`; `tuned-adm active` |

## Cheat sheet

```console
# limits
cat /proc/PID/limits                                  # what a process ACTUALLY has
prlimit --pid PID                                     # the same, and --nofile=SOFT:HARD to change it live
systemctl show -p LimitNOFILE -p LimitNOFILESoft UNIT
# [Service] LimitNOFILE=8192   (soft=hard)   LimitNOFILE=8192:524288   (soft:hard)
# sessions: /etc/security/limits.d/*.conf (PAM)   services: the unit (systemd)   never both
ls /proc/PID/fd | wc -l                               # how many it holds now

# memory
free -m                                               # watch "available", not "free"
ps -eo pid,rss,comm --sort=-rss | head                # biggest resident sets
systemctl show -p MemoryPeak -p MemoryCurrent UNIT
# [Service] MemoryMax=300M   → Result: oom-kill instead of a machine-wide OOM
journalctl -k -b | grep -i 'out of memory\|oom-kill'  # CONSTRAINT_MEMCG = a cgroup; CONSTRAINT_NONE = the machine

# CPU and load
cat /proc/loadavg ; nproc                             # load means nothing without the CPU count
vmstat 1 5                                            # r runnable, b blocked, us/sy/id/wa
top -o %CPU ; pidstat 1                               # who

# sysctl
sysctl KEY ; sysctl -w KEY=VALUE                      # now only
echo "KEY = VALUE" > /etc/sysctl.d/90-app.conf ; sysctl --system   # at boot, and now
tuned-adm active ; tuned-adm list                     # tuned sets sysctls too
grep reapply_sysctl /etc/tuned/tuned-main.conf        # 1: sysctl.d files win after the profile

# pressure (if enabled)
ls /proc/pressure || grep -o 'psi=[01]' /proc/cmdline
```

## Exercises

1. Start a program under `ulimit -n 64` that opens files until it fails; read its `/proc/PID/limits`
   while it runs.
2. Put `LimitNOFILE=` in a unit's drop-in and compare `systemctl show` with `/proc/PID/limits` of the
   running service.
3. Run a memory hog in a transient unit with `systemd-run -p MemoryMax=100M`; find the kill in the
   kernel log and in the unit's `memory.events`.
4. Watch `free -h` while reading a large file twice; which columns move?
5. Set a sysctl with `-w`, reboot, and read it; then set it in `/etc/sysctl.d/` and reboot again.

## Sources

- `man 2 setrlimit`, `man 5 limits.conf`, `man 5 systemd.exec` (the `Limit*=` settings).
- `man 5 proc` — `/proc/PID/limits`, `/proc/meminfo`, `/proc/loadavg`.
- `man 5 systemd.resource-control` — `MemoryMax=`, `MemoryHigh=`, `TasksMax=`.
- The kernel's cgroup v2 guide: https://docs.kernel.org/admin-guide/cgroup-v2.html
- The kernel's `vm` sysctl reference: https://docs.kernel.org/admin-guide/sysctl/vm.html

## Review

1. A service fails with *Too many open files* after `webapp soft nofile 8192` was added to
   `/etc/security/limits.d/`, and `su - webapp -c 'ulimit -n'` prints 8192. Why is the service still
   limited, and where does the fix go?

   > `limits.d` is applied by PAM to login sessions; a systemd service is not a session and inherits its
   > limits from systemd. Set `LimitNOFILE=` in the unit (a drop-in), `daemon-reload`, restart, and check
   > `/proc/PID/limits`.

2. With a soft limit of 1024, why did the test program fail after 1021 open files?

   > Standard input, output and error already occupy three descriptors, so only 1021 more fit under 1024.

3. `free -m` shows 395 MiB free and 1123 MiB available on a 1.4 GiB machine. Is it short of memory?

   > No. The gap is page cache, which the kernel reclaims on demand; `available` estimates what can be
   > allocated without swapping. On the lab machine reading a 600 MiB file produced exactly this picture
   > with `available` unchanged.

4. `systemctl status` shows `Result: oom-kill` and the application's log ends with a normal message.
   Where is the evidence of what happened, and how do you tell a cgroup limit from the whole machine
   running out?

   > The process was killed with `SIGKILL`, so it logged nothing. The kernel log (`journalctl -k`) has
   > the OOM report: `constraint=CONSTRAINT_MEMCG` and *Memory cgroup out of memory* name a cgroup that hit
   > its limit (for example `MemoryMax=`); the machine-wide case reports `CONSTRAINT_NONE` and *Out of
   > memory*.

5. A one-CPU machine shows a 1-minute load average of 2.25. What does that mean, and when can load be
   high while the CPUs are idle?

   > On average more than two tasks were runnable or in uninterruptible sleep, on a machine that can run
   > one at a time — a queue. Load also counts tasks blocked in uninterruptible I/O (`D` state), so a slow
   > disk or NFS mount raises load with idle CPUs; `vmstat`'s `b` and `wa` show it.

6. You set `vm.dirty_ratio=33` with `sysctl -w` and it is 30 after a reboot. Where did 30 come from, and
   how do you make a value persistent?

   > From the active tuned profile (virtual-guest sets `dirty_bytes = 30%`); `sysctl -w` only changes the
   > running kernel. Put the value in a file under `/etc/sysctl.d/` and apply with `sysctl --system`.

7. A value in `/etc/sysctl.d/` is correct and still not in effect after boot. What should you check?

   > Whether tuned is applying a profile that sets the same key after the system files — `tuned-adm
   > active`, and `reapply_sysctl` in `/etc/tuned/tuned-main.conf`. With `reapply_sysctl = 1` the system
   > files win; otherwise change or create a tuned profile.

8. A monitoring guide says to alert on `/proc/pressure/memory`. On a RHEL-family server the file does
   not exist. Is the guide wrong?

   > Not necessarily: the kernel supports PSI but RHEL-family kernels leave it disabled unless booted with
   > `psi=1`. Check `/proc/cmdline` and decide whether to enable it before relying on it.
