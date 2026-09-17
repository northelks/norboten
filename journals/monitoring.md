---
title: Active, green, and not working
topics: [monitoring]
minutes: 35
covers: >-
  checks as exit statuses with deadlines (timeout, 124); is-active versus a real request; OnFailure= alerts; WatchdogSec= and sd_notify; NRestarts and crash loops a sampler misses; where the probe runs
---

Every monitoring failure that matters has the same shape: the check said the service was fine, and a
user said it was not. Nobody writes a check intending it to lie. It lies because it measures something
adjacent to what matters — that a process exists, that a command exited 0, that a unit was `active` the
moment someone looked — and the service found a way to fail that the adjacent thing does not see.

This journal builds a small web service with a `/health` endpoint on a Rocky Linux 10 lab machine and
breaks it in the ways real services break: an error it reports politely, a hang, a crash loop, a hang
in one thread while another stays cheerful. For each, it records what the obvious check said. Most of
them said "fine".

## What you should be able to do after this

- Write an HTTP health check whose exit status reflects the answer, and that cannot hang.
- Say what `systemctl is-active` does and does not tell you about a service.
- Use `OnFailure=` to raise an alert when a unit fails, and know which failures never reach it.
- Use the systemd watchdog to turn a hang into a restart, and put the watchdog ping where it proves
  something.
- Recognise a crash loop that looks healthy to a sampling check, and measure restarts instead.
- Design the check of last resort: the one that notices when the checks themselves have stopped.

## The mechanism

### A check is an exit status

Every scheduler, monitoring agent and systemd timer consumes a check the same way: exit status `0` is
healthy, anything else is not. So the first question about any check is what makes it exit non-zero. For
the most common one — fetching a URL with `curl` — the answer is surprising. The service here answers
`/health` with `500 database unreachable` while its database is down:

```console
$ curl -s localhost:8088/health ; echo "exit=$?"
database unreachable
exit=0
```

`curl` succeeded: it connected, sent a request and received a response. The status code is data, not
failure. `-f` (`--fail`) makes an HTTP error an error:

```console
$ curl -sf localhost:8088/health ; echo "exit=$?"
exit=22
```

Exit 22 is curl's "HTTP page not retrieved": the response was 400 or above. A check without `-f` alerts
on nothing but a refused connection.

### A check must have a deadline

Stop the service's process — `kill -STOP`, the cheapest way to simulate a deadlock — and ask again:

```console
$ curl -s -m 3 localhost:8088/health ; echo "exit=$?"
exit=28
$ timeout 10 curl -s localhost:8088/health ; echo "exit=$?"
exit=124
```

With `-m 3`, curl gives up after three seconds with exit 28 (operation timed out). Without it, curl
waited until `timeout` killed it at ten seconds (124). A check with no deadline does not fail when the
service hangs; it hangs with it, and a monitoring agent waiting on it reports nothing — which a dashboard
draws as "no change". Every check needs a timeout shorter than its interval.

### `is-active` is about the process, not the service

```console
$ sudo kill -STOP $(systemctl show -p MainPID --value shop)
$ systemctl is-active shop
active
```

A stopped process, a server that answers nobody, and systemd reports `active` — correctly. `active` means
systemd started the unit and its main process has not exited. It says nothing about whether the process
does its job. The same was true of the polite 500: `systemctl is-active shop` said `active` the whole
time the database was down. `is-active` is a useful check for "did it crash and stay down"; it is not a
health check.

### `OnFailure=`: an alert when a unit fails

```ini
# /etc/systemd/system/alert@.service
[Unit]
Description=alert for %i

[Service]
Type=oneshot
ExecStart=/usr/bin/logger -t ALERT "unit %i entered failed state"
```

```ini
# in shop.service
[Unit]
OnFailure=alert@%n.service
```

When `shop.service` enters the failed state, systemd starts `alert@shop.service.service` — a template
instance whose `%i` is the failing unit's name. In a real deployment `ExecStart` sends a message to a
chat channel or an alerting API; `logger` stands in. Killing the process shows it working:

```console
$ sudo kill -9 $(systemctl show -p MainPID --value shop)
$ systemctl is-active shop
failed
$ sudo journalctl -t ALERT --since -1min
ALERT[2099]: unit shop.service entered failed state
```

And the stopped process shows its limit. Before the kill, the process had been frozen for twelve
seconds — service unusable — and the alert log said:

```console
$ sudo journalctl -t ALERT --since -1min
-- No entries --
```

`OnFailure=` reacts to a state change. A hang is not a state change. With `Restart=on-failure` in the unit
it still fires on every failure (the journal says *Triggering OnFailure= dependencies* before the
restart), so a service that crashes and restarts still reaches the alert.

### The watchdog: make a hang a failure

systemd can require a service to prove it is alive. With `Type=notify` and `WatchdogSec=`, the service
must send `WATCHDOG=1` to the socket named in `$NOTIFY_SOCKET` more often than the interval; if it
stops, systemd kills it, marks the unit failed, and `Restart=` and `OnFailure=` take over:

```ini
[Unit]
OnFailure=alert@%n.service

[Service]
Type=notify
ExecStart=/usr/local/bin/shop
WatchdogSec=5
Restart=on-failure
```

(The service sends `READY=1` when it is ready, which is what `Type=notify` waits for, and pings at half
the interval systemd passes it in `$WATCHDOG_USEC`. A shell script can do the same with `systemd-notify`,
with one trap measured on the lab machine: a service running as a non-root `User=` whose script called
`systemd-notify --ready` hit *start operation timed out* — the message comes from a child process, and
systemd accepts notifications only from the main process unless the unit says `NotifyAccess=all`.
With that line added, the same unit started at once. Run as root, it worked either way.) Freeze the process again:

```console
$ sudo kill -STOP $(systemctl show -p MainPID --value shop)
$ sudo journalctl -u shop --since -12s
systemd[1]: shop.service: Watchdog timeout (limit 5s)!
systemd[1]: shop.service: Main process exited, code=dumped, status=6/ABRT
systemd[1]: shop.service: Failed with result 'watchdog'.
systemd[1]: shop.service: Triggering OnFailure= dependencies.
systemd[1]: shop.service: Scheduled restart job, restart counter is at 1.
systemd[1]: Started shop.service - shop.
$ systemctl show -p NRestarts shop
NRestarts=1
$ curl -s -m 3 localhost:8088/health
ok
```

Five seconds without a ping, `SIGABRT` (so a core dump shows where it was stuck), `Result: watchdog`, an
alert, a restart, and the service answering again.

### Where the ping comes from decides what it proves

The watchdog proves only that *whatever sends the ping* is alive. In this service the ping comes from its
own thread. Make the request handler block forever — the realistic version: a request waiting on a lock
or a dead database connection — and leave that thread alone:

```console
$ sudo touch /run/shop-stuck                 # the handler now waits forever
$ curl -s -m 3 localhost:8088/health ; echo "curl exit=$?"
curl exit=28
$ sleep 15 ; systemctl is-active shop ; systemctl show -p NRestarts shop
active
NRestarts=0
```

Fifteen seconds of a service that answers nobody, three times the watchdog interval, and no restart: the
ping thread was fine. A watchdog ping belongs in the code path whose progress matters — after a request
completes, at the top of the main loop, after a successful query — not on a timer of its own. A ping from
an independent thread is a very elaborate `is-active`.

### A crash loop looks healthy to a sampling check

A service that crashes two seconds after starting, with `Restart=always` and `RestartSec=1`, sampled with
`systemctl is-active` every 1.3 seconds:

```
active active activating active activating active active activating active activating
NRestarts=4
```

Six "active" answers out of ten, and four restarts in thirteen seconds. A check that runs once a minute
and asks "is it active" is right most of the time — and a service that does nothing but crash is exactly
what it will miss. The honest measure is the restart counter:

```console
$ systemctl show -p NRestarts flappy
NRestarts=4
```

Alert when `NRestarts` increases between two checks, or when `Result` is not `success`, and a crash loop
becomes an alert instead of an intermittent green.

### The check that watches the checks

Every mechanism above fails silently in one way: if the check stops running, nothing complains. A timer
that was disabled during maintenance, an agent that crashed, a cron entry removed with a config change —
the dashboard shows the last good value, forever.

The defence inverts the logic: a **dead man's switch**. The check, on each successful run, pings an
external service ("I am alive"); that service alerts when the pings *stop*. It catches a dead check, a
dead machine and a dead network in one rule, which no check running on the machine itself can do. And
checks run from outside the machine — a request from another host through the real firewall and proxy —
see failures an on-host check never will, because they take the user's path.

## A failure, walked through

The shop's monitoring is a timer that runs every minute:

```bash
curl -s localhost:8088/health && systemctl is-active --quiet shop
```

It has not alerted in a month. Customers report checkout failures twice this week.

**1. Read the check as an exit status.** Put the service into the state the customers describe — the
database is down — and run the check exactly as the timer does:

```console
$ sudo touch /run/shop-db-down
$ curl -s localhost:8088/health && systemctl is-active --quiet shop ; echo "exit=$?"
database unreachable
exit=0
```

The check passes while the service returns 500. `curl` without `-f` succeeds on any HTTP response, and
`is-active` only says the process exists.

**2. Fix the HTTP half, and give it a deadline.**

```console
$ curl -sf -m 3 localhost:8088/health > /dev/null ; echo "exit=$?"
exit=22
$ sudo rm /run/shop-db-down
$ curl -sf -m 3 localhost:8088/health > /dev/null ; echo "exit=$?"
exit=0
```

**3. Try the other failure the check was blind to: a hang.**

```console
$ sudo kill -STOP $(systemctl show -p MainPID --value shop)
$ curl -sf -m 3 localhost:8088/health > /dev/null ; echo "exit=$?"
exit=28
$ systemctl is-active shop
active
```

The fixed check now fails, correctly. But a check every minute only *reports* the hang; nothing ends it.
And the original `curl` with no `-m` would simply have waited — the timer's run would never finish, and a
timer does not start a new run while the previous one is still going: on the lab machine a check that
slept 20 seconds, on a timer due every 4, ran exactly once in 18 seconds.

**4. Make the unit end a hang itself.** `Type=notify`, `WatchdogSec=5`, `Restart=on-failure` and
`OnFailure=alert@%n.service`, as above. Frozen again, the journal shows *Watchdog timeout (limit 5s)!*,
`Result 'watchdog'`, the alert, and a restart; `curl` answers `ok` a moment later.

**5. Check where the ping comes from.** A blocked request handler with a healthy ping thread left the
service `active` and unrestarted for fifteen seconds while every request timed out. Move the ping into
the request path (or into a loop that exercises it), so a stuck handler stops the pings.

**6. Watch restarts, not just state.** With the watchdog restarting it, a service that hangs every few
minutes will look `active` at almost every sample. Alert on `NRestarts` growing, and on the `ALERT` events
`OnFailure=` produces.

**7. Watch the watcher.** Make the minute check ping a dead man's switch on success, so that a disabled
timer or a dead machine produces an alert instead of a quiet dashboard.

## Common wrong turns

**`curl -s URL` as a health check.** Exit 0 on a 500. Use `-f`, and consider checking the body for a
known string.

**A check with no timeout.** It hangs with the service it is checking, and silence looks like health.
`curl -m`, `timeout`, and an interval longer than the deadline.

**`systemctl is-active` as the health check.** It reports that the main process has not exited. A
frozen process, a server returning errors and a crash loop at the moment of sampling are all `active`.

**Expecting `OnFailure=` to catch a hang.** It fires on entering the failed state. A hang never gets
there without a watchdog.

**A watchdog pinged from its own thread.** It proves that thread is alive. Ping from the work.

**Sampling state to detect a crash loop.** `active` six times out of ten while restarting every three
seconds. Measure `NRestarts`, or `Result`.

**Restarting without alerting.** `Restart=` hides failures from users and from you. Pair it with
`OnFailure=` (it still fires before each restart) or an alert on the restart counter.

**Only checking from the machine itself.** The firewall, the proxy, DNS and the network are not on that
path. Run at least one check from outside, the way a user arrives.

**No check of the checks.** A disabled timer and a dead agent are indistinguishable from a quiet week.
A dead man's switch is the only kind of alert that fires on silence.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| the check is green while users see errors | it tests the process (`is-active`), not the service's answer | run the check's command yourself; compare with a request a user makes |
| the monitoring job hangs and nothing is reported | a check with no deadline waits on a stalled dependency | `timeout 10 CHECK; echo $?` — 124 means it timed out |
| a crashing service shows as running at every sample | `Restart=` brings it back faster than the sampling interval | `systemctl show -p NRestarts UNIT`; `journalctl -u UNIT` for starts |
| a unit failed and nobody was told | no `OnFailure=`, or the alert unit itself fails | `systemctl list-dependencies --reverse`; the alert unit's journal |
| a hung process is never restarted | nothing turns a hang into a failure | `WatchdogSec=` in the unit, and the program's `sd_notify` pings |
| the check runs from the same host it checks | it proves the process answers loopback, not that the network path works | where the check runs, and which address it uses |

## Cheat sheet

```console
# HTTP checks that tell the truth
curl -sf -m 3 URL > /dev/null ; echo $?     # 0 ok, 22 HTTP >= 400, 28 timeout, 7 refused
curl -sf -m 3 URL | grep -q '^ok$'          # …and the body says what you expect
timeout 10 CMD                              # a deadline for anything (124 = timed out)

# what systemd knows
systemctl is-active UNIT                    # main process not exited — NOT "working"
systemctl show -p Result -p NRestarts -p ActiveEnterTimestamp UNIT
journalctl -u UNIT --since -10min

# alert on failure
# alert@.service: [Service] Type=oneshot  ExecStart=/path/to/notify "unit %i failed"
# in the unit:    [Unit] OnFailure=alert@%n.service    (fires before each Restart= too)

# end hangs
# [Service] Type=notify  WatchdogSec=5  Restart=on-failure
# the program: send READY=1 once, then WATCHDOG=1 more often than every $WATCHDOG_USEC µs
#              — from the code path that does the work, not a separate timer thread
systemd-notify --ready ; systemd-notify WATCHDOG=1     # from a shell service; with User= (non-root)
                                                       # it is ignored unless NotifyAccess=all

# crash loops
systemctl show -p NRestarts UNIT            # alert when it grows between checks

# simulate failures
kill -STOP PID ; kill -CONT PID             # a hang, and back
kill -9 PID                                 # a crash
```

## Exercises

1. Write a check script for an HTTP service that exits 0, 1 and 2 for up, degraded and down, with a
   deadline; test each case, including a server that accepts and never answers.
2. Give a unit `Restart=always` and a program that exits after two seconds. Sample `is-active` every ten
   seconds for a minute, then read `NRestarts`.
3. Add `OnFailure=` to a unit, pointing at a template that writes the failing unit's name to a file;
   make the unit fail and read the file.
4. Run a check from the machine itself and from another one, against a service bound to `127.0.0.1`.
   What does each prove?
5. Make the check itself fail (a typo in its path). How would you notice, and what watches it?

## Sources

- `man 5 systemd.unit` — `OnFailure=`, `OnSuccess=`, `StartLimitIntervalSec=`, `StartLimitBurst=`.
- `man 5 systemd.service` — `Restart=`, `RestartSec=`, `WatchdogSec=`.
- `man 1 timeout` — deadlines for any command; exit status 124.
- `man 3 sd_notify` — how a service tells systemd it is alive.
- systemd's manual online: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html

## Review

1. A health check is `curl -s http://localhost:8088/health`. The service returns `500 database
   unreachable`. What exit status does the check produce, and how do you fix it?

   > 0: curl received a response, and without `--fail` the HTTP status is only data. `curl -sf` exits 22
   > for a status of 400 or more; add `-m` for a deadline.

2. Why does a health check need its own timeout, and what did the lab machine show without one?

   > A hung service makes an unbounded check hang too, so it never reports failure — and the scheduler
   > or agent waiting on it reports nothing. With `-m 3` curl exited 28 after three seconds; without it
   > curl waited until `timeout 10` killed it (124).

3. A service's process is frozen with `SIGSTOP`. What does `systemctl is-active` say, and why is that
   correct?

   > `active`. The state means systemd started the unit and its main process has not exited; a frozen
   > process has not exited. `is-active` reports process lifecycle, not whether the service works.

4. A unit has `OnFailure=alert@%n.service`. Which of these produce an alert: a `kill -9`, a hang, a
   crash followed by an automatic restart?

   > The kill (the unit enters the failed state) and the crash with restart (systemd triggers `OnFailure=`
   > dependencies before scheduling the restart). The hang does not: no state change happens without a
   > watchdog.

5. With `Type=notify` and `WatchdogSec=5`, what happens when the process stops sending `WATCHDOG=1`?

   > After five seconds systemd logs *Watchdog timeout*, kills the process with `SIGABRT`, marks the unit
   > failed with result `watchdog`, triggers `OnFailure=`, and restarts it if `Restart=` allows.

6. A service's request handler is stuck, yet the watchdog never fires. What is the likely design fault?

   > The watchdog ping comes from an independent thread or timer, which is still healthy. A ping proves
   > only that its sender runs; it must be sent from the code path whose progress matters, so a stuck
   > handler stops the pings.

7. A check samples `systemctl is-active` and a service is in a crash loop with `Restart=always`. Why can
   the check stay green, and what should it measure instead?

   > Between crashes the unit is `active`, so most samples catch it active (six of ten on the lab machine,
   > with four restarts in thirteen seconds). Measure the restart counter (`NRestarts`) or the unit's
   > `Result`, and alert when restarts increase.

8. What failure does a dead man's switch detect that no check running on the server can?

   > The checks themselves stopping — a disabled timer, a dead agent, a dead machine or network. The
   > switch alerts when the expected "I am alive" pings stop arriving, so silence becomes an alert.
