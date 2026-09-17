---
title: The log lines that were never written down
topics: [logging-journald]
minutes: 35
covers: >-
  stdout and stderr into the journal; per-unit rate limits (RateLimitIntervalSec/Burst); rsyslog's second copy; Storage=, SystemMaxUse=, vacuuming; journalctl by unit, boot, field and priority
---

After an incident, the logs are the only witness, and everyone assumes the witness saw everything.
It did not. A logging pipeline makes decisions of its own: it drops messages from a service that logs
too fast, it files a program's error output under "info", it keeps a second copy somewhere else with a
different set of rules, and it deletes old entries to make room. None of that is a failure of the logging
system. All of it is invisible unless you know where to look — and the time to learn it is before the
incident, not while reading a log with a hole in the middle.

Every number below was produced on a Rocky Linux 10 lab machine, where systemd-journald collects
everything and rsyslog copies it on to `/var/log/messages`, as on any RHEL-family server.

## What you should be able to do after this

- Say how a service's output reaches the journal, and which priority it gets on the way.
- Recognise journald's rate limiting, find the message that reports it, and set a per-service limit.
- Explain why `/var/log/messages` and the journal can disagree about the same service.
- Query the journal precisely: by unit, by identifier, by priority, by invocation, by boot.
- Know where the journal stores data, how big it may grow, and how to see and change that.

## The mechanism

### Everything a service prints becomes a journal entry

A systemd service's standard output and standard error are connected to journald by default
(`StandardOutput=journal`). Each line becomes an entry with structured fields — the message, the unit,
the PID, the syslog identifier, a **priority**. A program can also send to the journal through syslog
(`logger`, `syslog(3)`) or the journal API; those entries are attributed to the unit the process runs in
as well.

A tiny script run as `prio.service`, writing four ways:

```sh
echo plain stdout
echo to stderr >&2
echo "<3>tagged error"
logger -p user.warning -t chatty2 warned via logger
```

and what the journal recorded, as `PRIORITY  _SYSTEMD_UNIT  SYSLOG_IDENTIFIER | MESSAGE`:

```
6 prio.service prio    | plain stdout
6 prio.service prio    | to stderr
3 prio.service prio    | tagged error
4 prio.service chatty2 | warned via logger
```

Three things to take from that.

**Standard error is not an error.** Both streams are logged at priority 6, `info`. A program that writes
its failures to stderr — which is correct practice — does not produce `err` entries, and a filter on
priority will not find them:

```console
$ sudo journalctl -u prio -b -p err -o cat
tagged error
```

**Priority can be set per line** by prefixing it `<N>` (0 emerg … 3 err, 4 warning, 6 info, 7 debug):
`<3>tagged error` arrived as priority 3 with the prefix removed. That is `SyslogLevelPrefix=`, on by
default, and it is how a service written for systemd marks its errors without a logging library.

**`-u` means the unit, `-t` means the identifier.** The `logger` line has identifier `chatty2`, but it
ran inside `prio.service`, so `journalctl -u prio` shows it and `journalctl -t chatty2` shows it too. A
query by `-t` for a program's name misses everything that program printed to stdout (identifier
`prio`); a query by `-u` catches everything the unit's processes produced.

### journald rate-limits per service

journald protects itself from a service that floods it: by default, more than 10,000 messages in 30
seconds from one service and the rest of that interval is dropped. The documented detail that matters
is that the burst is **multiplied by a factor derived from free disk space**, so the real limit depends
on the machine.

A stand-in batch job printing 100,000 tagged lines as fast as it could:

```console
$ sudo systemctl start chatty
$ sudo journalctl -b -o cat | grep -c '^runA order'
35000
```

35,000 kept — `runA order 0` through `runA order 34999`, the default 10,000 scaled by 3.5 on this
machine's free space — and 65,000 gone. The only
record of it is a message journald writes *after* the interval, when the service next logs:

```
systemd-journald[594]: Suppressed 65000 messages from chatty.service
```

Note what the surviving lines are: the **first** 35,000. A job that logs its progress and then, at the
end, its one error, has its error dropped. An earlier run of 200,000 lines, started while the previous
run's window was still open, kept 15,000 and reported `Suppressed 185000 messages` — the limit is per
service *per interval*, shared by consecutive runs.

A unit can set its own limit:

```ini
[Service]
LogRateLimitIntervalSec=30s
LogRateLimitBurst=1000
```

With that, the same job (5,000 lines) kept 3,500 — the per-unit burst of 1,000 scaled by the same factor
of 3.5. `LogRateLimitBurst=0` turns the limit off for that unit, which is reasonable for a service whose
full output you need and whose volume you trust, and a bad idea for anything that can loop.

### rsyslog keeps a second copy, with its own limit

On RHEL-family systems rsyslog reads the journal through its `imjournal` module and writes the classic
files, `/var/log/messages` among them:

```
module(load="imjournal"             # provides access to the systemd journal
       UsePid="system"
       FileCreateMode="0644"
       StateFile="imjournal.state")
```

`imjournal` has a rate limit of its own (documented default: 20,000 messages per 600 seconds), and when
it applies, rsyslog says so in the journal:

```
rsyslogd[1167]: imjournal from <lima-nb-hello:chatty>: begin to drop messages due to rate-limiting
```

After the runs above, the two logs disagreed flatly:

```console
$ sudo grep -c 'order .* processed' /var/log/messages
19941
$ sudo grep -c 'runA order' /var/log/messages
0
```

`/var/log/messages` held about 20,000 lines from the first runs and **none** from the later one, which
the journal had 35,000 lines of — rsyslog's ten-minute window was already spent. So "grep the messages
file" and "query the journal" are two different witnesses with two different blind spots, and a
colleague who says the log shows nothing may be reading the other one. (Ubuntu's cloud image keeps
both too: rsyslog writes `/var/log/syslog` from the journal. A container has neither, and there a
program's own log file is the only witness.)

### Where the journal lives, and how big it gets

```console
$ sudo journalctl -u systemd-journald -b | grep 'System Journal'
systemd-journald[594]: System Journal (/var/log/journal/a92…/) is 16M, max 1.4G, 1.4G free.
$ sudo journalctl --disk-usage
Archived and active journals take up 48M in the file system.
```

With persistent storage (see the rhcsa-05 journal for `Storage=`), entries go to `/var/log/journal/`;
before that directory is usable, and with volatile storage, to `/run/log/journal/`. journald reports its
limits at start: here at most 1.4 GiB — by default 10% of the filesystem, capped at 4 GiB — and it removes
the oldest archived files to stay under `SystemMaxUse=`. So the journal is never "full"; it quietly gets
*shorter*. `journalctl --list-boots` shows how far back it goes, and `--vacuum-size=`, `--vacuum-time=`
trim it on demand.

The effective configuration is the main file plus drop-ins, in order, and `systemd-analyze` prints the
merged result:

```console
$ systemd-analyze cat-config systemd/journald.conf | grep -v '^#' | grep -v '^$'
[Journal]
Audit=
[Journal]
Storage=persistent
```

### Asking precise questions

```console
$ sudo journalctl -u chatty -b                        # this unit, this boot
$ sudo journalctl _SYSTEMD_INVOCATION_ID=$(systemctl show -p InvocationID --value chatty)   # this run
$ sudo journalctl -b -p warning                        # priority 4 and more severe
$ sudo journalctl -t chatty2                           # by syslog identifier
$ sudo journalctl -u prio -o json | head -1            # every field of an entry
$ sudo journalctl -k -b                                # the kernel's messages
$ sudo journalctl --since '10 min ago' -u shop         # a time window
```

`-o json` (or `-o verbose`) is the answer to "why did my filter not match": it shows the fields an entry
really has. And `InvocationID` only exists while the unit is loaded with a current run — for a finished
oneshot, `systemctl show -p InvocationID` can come back empty, and the query above matches nothing. Use a
time window for runs that have ended.

Reading the system journal needs privilege: an ordinary account sees only its own entries unless it is
in `adm`, `systemd-journal` or `wheel` (see the linux-02 journal).

## A failure, walked through

A nightly import processed 100,000 records and failed at the end. The on-call engineer greps
`/var/log/messages` and finds nothing from the import at all. The journal shows progress lines and then
simply stops, well before the end. Nobody can see the error.

**1. Count what the journal has, and look for the report of what it does not.**

```console
$ sudo journalctl -b -o cat | grep -c '^runA order'
35000
$ sudo journalctl -b | grep Suppressed
systemd-journald[594]: Suppressed 65000 messages from chatty.service
```

The journal kept the first 35,000 lines and dropped 65,000, and it says so — once, afterwards, in a line
from `systemd-journald`, not from the job. The error was among the dropped lines.

**2. Explain the other log.**

```console
$ sudo grep -c 'runA order' /var/log/messages
0
$ sudo journalctl -b -t rsyslogd | grep rate
rsyslogd[1167]: imjournal from <lima-nb-hello:chatty>: begin to drop messages due to rate-limiting
```

rsyslog had its own window already used up by an earlier run, and dropped every line of this one.

**3. Check whether the error could have been found by priority.** The job writes errors to stderr:

```console
$ sudo journalctl -u prio -b -p err -o cat
tagged error
```

Only a line with an explicit `<3>` prefix is an `err`. Plain stderr is `info`, so `journalctl -p err`
would not have found the job's failure even if it had been kept.

**4. Fix the service, not the logging system.** A job that prints a line per record is logging data, not
events. Make the progress summary periodic (every 10,000 records), write the failure with a priority,
and give the unit a limit that matches what it legitimately produces:

```ini
[Service]
LogRateLimitIntervalSec=30s
LogRateLimitBurst=5000
```

```python
print(f"<3>import failed at record {i}: {err}", flush=True)
```

**5. Verify the limit and the priority.** Run the job at its real volume, count the lines, confirm no
`Suppressed` report follows the next run, and query `-p err`: the failure is now the one thing a priority
filter finds.

**6. Decide which log is authoritative.** On this machine the journal kept more than
`/var/log/messages` and carries the structured fields; make it the source for investigations and for
forwarding, and treat the rsyslog copy as a convenience with its own limits.

## Common wrong turns

**Assuming the log has every line.** journald and rsyslog both drop floods, silently in the moment. Look
for `Suppressed N messages from UNIT` and `imjournal … drop messages due to rate-limiting`.

**Looking for the error at the end of a truncated log.** Rate limiting keeps the *first* messages of an
interval, so the end — where failures usually are — is what goes.

**Filtering on `-p err` to find a service's failures.** stdout and stderr are both `info` (6). Only
explicit priorities — a `<3>` prefix, syslog with a level — produce `err`.

**Querying by `-t PROGRAM` for a service's output.** The identifier of stdout lines is the executable
name, and child programs using `logger` have their own. `-u UNIT` catches all of it.

**Treating `/var/log/messages` and the journal as the same log.** They are filled by different code with
different limits; after a flood they disagreed by tens of thousands of lines.

**Turning rate limiting off globally.** `RateLimitBurst=0` in `journald.conf` lets one looping service
fill the disk and push out every other service's history. Set a limit per unit instead.

**Expecting the journal to report "disk full".** It deletes its oldest files to stay under
`SystemMaxUse=`. Check `--list-boots` and `--disk-usage` to see how far back the evidence really goes.

**Querying by `InvocationID` after the run has finished.** For a finished oneshot the property may be
empty and the query matches nothing. Use a time window.

**Reading the journal without privilege.** An ordinary account sees only its own entries, and the
empty result looks like "nothing was logged".

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| a service's messages stop mid-burst; journald logs "Suppressed N messages" | the per-unit rate limit | `journalctl -u systemd-journald`; `RateLimitIntervalSec=`, `RateLimitBurst=` |
| last boot's logs are missing | the journal is volatile (`Storage=volatile`, or `auto` with no `/var/log/journal`) | `journalctl --list-boots`; `ls /var/log/journal` |
| `/var/log/journal` grows until the disk fills | no size limit, or one larger than the filesystem allows | `journalctl --disk-usage`; `SystemMaxUse=` |
| `/var/log/messages` or `/var/log/syslog` has lines the journal lacks, or the other way round | rsyslog and journald have separate limits and filters | both, side by side, for the same minute |
| a unit's output is absent from the journal | it logs to a file of its own, or its stdout goes elsewhere (`StandardOutput=`) | `systemctl show -p StandardOutput UNIT`; the program's configuration |
| messages from a script have no unit | it was run by hand or by cron, not as a unit | `journalctl -t IDENTIFIER`; `_SYSTEMD_UNIT=` in `-o verbose` |

## Cheat sheet

```console
# querying
journalctl -u UNIT -b                      # unit, this boot (includes logger lines from its processes)
journalctl -t IDENTIFIER                   # by syslog identifier
journalctl -p err -b                       # priority 3 and worse: 0 emerg 1 alert 2 crit 3 err 4 warning 5 notice 6 info 7 debug
journalctl --since '10 min ago' --until now
journalctl _SYSTEMD_INVOCATION_ID=ID       # one run (while the unit still has one)
journalctl -k -b ; journalctl -b -1        # kernel ; previous boot
journalctl -u UNIT -o json | head -1       # the real fields — why a filter does not match
journalctl -o cat                          # messages only

# rate limiting
journalctl -b | grep Suppressed            # "Suppressed N messages from UNIT" — after the interval
# journald.conf  RateLimitIntervalSec=30s RateLimitBurst=10000   (burst scaled by free disk space)
# unit           LogRateLimitIntervalSec= LogRateLimitBurst=     (0 = off for that unit)
journalctl -t rsyslogd | grep rate         # rsyslog imjournal drops, a separate limit

# priorities from a service
# stdout and stderr → 6 (info);  echo "<3>message" → 3 (err);  logger -p user.warning → 4

# storage
journalctl --disk-usage ; journalctl --list-boots
journalctl -u systemd-journald -b | grep 'System Journal'     # current size, max, free
journalctl --vacuum-size=500M ; journalctl --vacuum-time=2weeks
systemd-analyze cat-config systemd/journald.conf               # merged configuration
```

## Exercises

1. Write a unit that prints 2,000 lines in a second; read the journal for it and for journald itself.
   How many lines were kept, and where does journald say so?
2. Compare `journalctl --list-boots` with `Storage=volatile` and with `Storage=persistent` across a
   reboot of a lab machine.
3. Set `SystemMaxUse=` in a drop-in under `/etc/systemd/journald.conf.d/`, restart journald, and check
   `journalctl --disk-usage` and `journalctl --vacuum-size=` together.
4. Find every field journald stored for one message with `journalctl -o verbose -n1 -u UNIT`, then
   select by one of them (`_PID=`, `_COMM=`, `PRIORITY=`).
5. Log with `logger -t mytest hello` and find the line in the journal and in rsyslog's file. Which
   fields does each keep?

## Sources

- `man 5 journald.conf` — storage, size limits, rate limits, forwarding.
- `man 1 journalctl` — selecting by unit, boot, priority, field, time.
- `man 5 systemd.exec` — `StandardOutput=`, `StandardError=`, `LogRateLimitIntervalSec=` per unit.
- systemd's manual online: https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html
- rsyslog's documentation: https://www.rsyslog.com/doc/

## Review

1. A service writes its errors to stderr. Why does `journalctl -u SERVICE -p err` show none of them, and
   how can the service mark a line as an error?

   > Standard output and standard error are both logged at priority 6 (`info`). A line prefixed `<3>` is
   > logged at priority 3 (`err`) with the prefix removed, as is a syslog message sent with an error
   > level.

2. A job logs 100,000 lines in a burst and the journal keeps 35,000. Which lines survive, and where is
   the evidence that the others were dropped?

   > The first ones in the rate-limit interval; later lines — including a final error — are dropped. After
   > the interval, when the service logs again, journald writes *Suppressed N messages from UNIT*.

3. The documented default is 10,000 messages per 30 seconds. Why did the lab machine keep 35,000?

   > The effective burst is multiplied by a factor derived from the journal's available disk space; on this
   > machine the factor was 3.5. A per-unit `LogRateLimitBurst=1000` was scaled the same way, keeping
   > 3,500.

4. The journal has thousands of lines from a service and `/var/log/messages` has none from the same run.
   How can both be right?

   > rsyslog fills `/var/log/messages` by reading the journal through `imjournal`, which has its own rate
   > limit and window. If that window was used up by an earlier flood, rsyslog drops the whole run and
   > logs *imjournal … begin to drop messages due to rate-limiting*, while the journal applied its own,
   > different limit.

5. A program run by `backup.service` calls `logger -t backup-tool`. Does `journalctl -u backup` show those
   lines? Does `journalctl -t backup` show the service's stdout?

   > `-u backup` shows them, because entries are attributed to the unit the process runs in. `-t backup`
   > shows only entries whose identifier is `backup`; stdout lines carry the executable's name and the
   > logger lines carry `backup-tool`, so it may show neither.

6. Why is `RateLimitBurst=0` in `journald.conf` a worse fix than `LogRateLimitBurst=` in one unit?

   > Globally unlimited, one looping service can fill the journal's space and cause its oldest files — every
   > other service's history — to be deleted. A per-unit limit raises the ceiling only for the service
   > whose volume you trust.

7. What happens when the journal reaches `SystemMaxUse=`, and how do you know how much history you still
   have?

   > journald deletes the oldest archived journal files to stay under the limit, without any error. Check
   > `journalctl --list-boots`, `journalctl --disk-usage`, and the *System Journal … max … free* line
   > journald logs at start.
