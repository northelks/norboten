---
title: A job that cannot fail cannot be trusted
topics: [python, boot-systemd]
minutes: 35
---

`sync.py` is twenty lines of perfectly readable Python. It fetches a list from an HTTP API and writes
it to a file. The dashboards that read the file showed zero machines for an hour, and during that
hour systemd reported every run of the job as a success, and the job's own log said `done: 0
records` every five minutes. Nobody was lying. The job had been written so that **there was no way
for it to report a failure**: it caught every exception, turned it into an empty list, wrote the
empty list over the good data, and ended normally.

Two days later the same job hung for hours on a slow API, and no later run could start. That is the
other half of the same design: a network call with no deadline trusts the network to answer.

This journal is about the difference between a script that runs and a job that can be operated. A job
has callers — systemd, a timer, a monitoring check, the services that read its output — and each of
them relies on a contract: the exit status says whether it worked, it finishes in bounded time, and
its output is either the new data or the old data, never something in between.

## What you should be able to do after this

- Decide where an exception should be handled, and turn a failure into a non-zero exit status with a
  message on standard error.
- Put an explicit timeout on every network call, and say what `urllib` and `requests` do without one.
- Replace a file atomically with a temporary file, `fsync` and `os.replace`, and explain what a reader
  sees during an in-place write.
- Keep existing data when new data could not be fetched.
- Test failure modes with throwaway servers: one that errors, one that never answers.
- Trace a timer job's configuration from `systemctl cat` through `EnvironmentFile=` to the port it
  calls.

## The mechanism

### The broken contract

```python
def fetch():
    try:
        with urllib.request.urlopen(API) as response:
            return json.load(response)
    except Exception as e:
        print(f"warning: {e}")
        return []


def main():
    records = fetch()
    with open(OUTPUT, "w") as f:
        json.dump(records, f, indent=2)
    print(f"done: {len(records)} records")


main()
```

Four decisions, each reasonable in isolation, add up to a job that cannot fail:

1. `except Exception` catches everything — connection refused, HTTP 500, a timeout, invalid JSON, a
   bug in the code.
2. Handling means printing a "warning" to **standard output** and returning a value that looks like
   valid data.
3. `main()` cannot tell "the API has no records" from "the API could not be reached"; both are `[]`.
4. The script ends normally, so Python exits with status 0.

systemd records a oneshot service as successful when its main process exits 0. From the outside, a run
that fetched nothing because nothing answered is indistinguishable from a good run.

### Exceptions belong where something can be done about them

Catching an exception is a claim: "I know what to do instead." `fetch()` does not know — it has no
good answer when the API fails. The only honest options for a low-level function are to let the
exception propagate, or to wrap it in a more meaningful one. The decision belongs to the top of the
program, where the policy lives: for this job, *do not touch the output, say what went wrong, exit
non-zero*.

```python
def main():
    try:
        records = fetch()
    except (OSError, ValueError, http.client.HTTPException) as e:
        print(f"sync: {API}: {e}", file=sys.stderr)
        return 1
    write_atomically(OUTPUT, records)
    print(f"done: {len(records)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

The exception classes are not arbitrary. `urllib.error.URLError` (nothing answered, DNS failed,
connection refused) is a subclass of `OSError`; so is `urllib.error.HTTPError` (a 4xx or 5xx answer),
and so is `TimeoutError`. `json.JSONDecodeError` is a `ValueError`. A response cut short raises
`http.client.IncompleteRead`, an `HTTPException`. Catching exactly those means a genuine bug — a
`NameError`, a `KeyError` in your own code — still crashes with a traceback, which is what a bug
should do. `sys.exit(main())` turns the return value into the process's exit status.

Diagnostics go to `sys.stderr`. Under systemd both streams end up in the journal, but the distinction
still matters wherever the output is consumed — a shell pipeline, a cron mail, a wrapper that parses
stdout.

### Every network call needs a deadline

`urllib.request.urlopen(url)` without `timeout=` uses the socket default, which is **no timeout**: a
server that accepts the TCP connection and never sends a response keeps the call blocked forever. The
same is true of `requests.get(url)`. A connection that is refused fails at once; a connection that is
accepted and ignored — an overloaded backend, a half-dead proxy, a firewall that drops the reply —
is the dangerous case, because nothing ever happens.

```python
urllib.request.urlopen(API, timeout=10)
```

The timeout applies to each blocking socket operation — connecting, and each read — not to the whole
request, so a server that trickles one byte every nine seconds can still hold the call longer. For a
hard wall-clock limit, put one around the whole job as well: systemd's `TimeoutStartSec=` for a
oneshot service, or `timeout 60 …` in a script. A hung oneshot service blocks its timer: the next
activation cannot start while the unit is still activating.

### What a reader sees during `open(path, "w")`

Opening a file for writing **truncates it immediately**. Between that moment and the moment the new
content is fully written and flushed, any other process that reads the file sees an empty or partial
document. For a JSON file read by dashboards every few seconds, that is a real window. If the writer
crashes halfway, the partial file stays.

The standard pattern avoids the window entirely:

```python
def write_atomically(path, records):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".records-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
```

- The temporary file is created **in the same directory**: `os.replace` is a `rename(2)`, which is
  atomic only within one filesystem. `/tmp` may be a different filesystem, and then the rename fails.
- `flush()` moves Python's buffer to the kernel; `fsync()` asks the kernel to put it on disk, so a
  power loss after the rename does not leave a zero-length file.
- `mkstemp` creates the file with mode 0600. The services that read the output need `chmod` before
  the rename.
- `os.replace` swaps the directory entry in one step. A reader that opened the old file keeps reading
  the old content; a reader that opens the path after the rename gets the new file. Nobody sees half.
- On any failure the temporary file is removed, so aborted runs do not litter the directory.

A useful tell: after an in-place write the file keeps its inode number; after an atomic replace it has
a new one. The walkthrough uses `stat -c %i` to see which one a program does.

### Keeping old data is a feature

"Do not overwrite good data with nothing" sounds obvious, and it is the most violated rule in data
jobs. Stale-but-real data is almost always better than empty data: the dashboards can show a warning
based on the file's age, and the next successful run brings everything up to date. Empty data is
indistinguishable from a real outage of the thing being reported on. The atomic write gives this for
free, as long as the write happens only after a successful fetch.

### How the job is configured

```ini
[Service]
Type=oneshot
EnvironmentFile=/etc/sync/sync.env
ExecStart=/usr/bin/python3 /opt/sync/sync.py
```

`EnvironmentFile=` reads `KEY=value` lines into the service's environment, and the script reads
`SYNC_API` and `SYNC_OUTPUT` from it with `os.environ.get`, falling back to defaults. The defaults in
the code are correct; the file overrides one of them with a wrong port. That is why the script
"works" when someone runs it by hand without the environment file, and fails only under systemd.
`systemctl cat` shows the unit and its drop-ins; `systemctl show -p Environment` shows inline
`Environment=` values but not the contents of an `EnvironmentFile=`, so read that file directly.

The timer (`OnBootSec=10s`, `OnUnitActiveSec=5min`) runs the service shortly after boot and five
minutes after each run. `systemctl list-timers` shows the last and next activation.

### Testing failures on purpose

A job's failure paths are only tested if you make them happen. Two twenty-line test servers cover this
job: one that answers every request with HTTP 500, and one that listens but never accepts, so a client
connects and waits forever. Pointing the script at them through its own environment variables,
against a scratch output file, shows exactly what a real outage would do — without touching the
production API or the file the dashboards read.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. Ask systemd what happened.** The timer fires ten seconds after boot; wait for it, then read the
job's journal (the journal of system units needs `sudo`, or membership in `adm` or `systemd-journal`):

```console
$ sleep 15; systemctl list-timers sync.timer --no-pager
NEXT                            LEFT LAST                        PASSED UNIT       ACTIVATES
Mon 2026-09-14 03:42:25 UTC 4min 55s Mon 2026-09-14 03:37:25 UTC 4s ago sync.timer sync.service

1 timers listed.
Pass --all to see loaded but inactive timers, too.
$ sudo journalctl -u sync.service -b --no-pager | tail -n 6
Sep 14 03:37:25 lima-nb-python-01 systemd[1]: Starting sync.service - Copy inventory records for the dashboards...
Sep 14 03:37:25 lima-nb-python-01 python3[881]: warning: <urlopen error [Errno 111] Connection refused>
Sep 14 03:37:25 lima-nb-python-01 python3[881]: done: 0 records
Sep 14 03:37:25 lima-nb-python-01 systemd[1]: sync.service: Deactivated successfully.
Sep 14 03:37:25 lima-nb-python-01 systemd[1]: Finished sync.service - Copy inventory records for the dashboards.
$ systemctl show sync.service -p Result -p ExecMainStatus
Result=success
ExecMainStatus=0
$ cat /var/lib/sync/records.json
[]
```

The warning is right there — connection refused — followed by `done: 0 records` and systemd's
"Deactivated successfully". Exit status 0, and an empty file.

**2. Find where it points.**

```console
$ systemctl cat sync.service
# /etc/systemd/system/sync.service
[Unit]
Description=Copy inventory records for the dashboards
After=records-api.service

[Service]
Type=oneshot
EnvironmentFile=/etc/sync/sync.env
ExecStart=/usr/bin/python3 /opt/sync/sync.py
$ cat /etc/sync/sync.env
SYNC_API=http://127.0.0.1:8091/records
SYNC_OUTPUT=/var/lib/sync/records.json
$ sudo ss -ltnp | grep -E ':8901|:8091'
LISTEN 0      5          127.0.0.1:8901      0.0.0.0:*    users:(("python3",pid=816,fd=3))
$ curl -sS http://127.0.0.1:8091/records; echo " exit=$?"
curl: (7) Failed to connect to 127.0.0.1 port 8091 after 0 ms: Could not connect to server
 exit=7
$ curl -sS http://127.0.0.1:8901/records; echo
[{"host": "web01", "role": "web", "rack": "A3"}, {"host": "web02", "role": "web", "rack": "A4"}, {"host": "db01", "role": "database", "rack": "B1"}]
```

The environment file names port 8091; the API listens on 8901. That explains the refused connection.
But fixing the port alone would leave a job that lies the next time the API is down — so the code
comes next.

**3. Build two test servers**, one that fails and one that never answers:

```python
# /tmp/s/fake_api.py
import socket, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

class Broken(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(500, "database unavailable")
    def log_message(self, *a):
        pass

if sys.argv[1] == "error":
    HTTPServer(("127.0.0.1", 9500), Broken).serve_forever()
else:  # listen, never accept, never answer
    s = socket.socket(); s.bind(("127.0.0.1", 9999)); s.listen(8); time.sleep(300)
```

**4. Run the old job against them**, with a scratch output file holding "good" data:

```console
$ (python3 /tmp/s/fake_api.py error & echo '[{"host": "keep-me"}]' > /tmp/s/records.json; sleep 1; SYNC_API=http://127.0.0.1:9500/records SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; echo "exit=$?"; cat /tmp/s/records.json; kill %1)
warning: HTTP Error 500: database unavailable
done: 0 records
exit=0
[]
$ (python3 /tmp/s/fake_api.py silent & sleep 1; time timeout 20 env SYNC_API=http://127.0.0.1:9999/records SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; echo "exit=$?"; kill %1)

real	0m20.478s
user	0m0.046s
sys	0m0.012s
exit=124
```

A server error destroyed the good data and exited 0. Against the silent server the script never
returned: `timeout` killed it after 20 seconds (124 is `timeout`'s own status), and without `timeout`
it would still be waiting.

**5. Check whether the write is in place.** Serve real records with Python's built-in HTTP server and
compare inode numbers:

```console
$ (python3 -m http.server -d /tmp/s 9600 >/dev/null 2>&1 & sleep 1; curl -s http://127.0.0.1:8901/records > /tmp/s/good.json; stat -c 'inode %i' /tmp/s/records.json; SYNC_API=http://127.0.0.1:9600/good.json SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; stat -c 'inode %i' /tmp/s/records.json; kill %1)
inode 15
done: 3 records
inode 15
```

Same inode: the file was truncated and rewritten where it stood.

**6. Rewrite the job.** The new `/opt/sync/sync.py`, written with `sudo tee /opt/sync/sync.py`:

```python
#!/usr/bin/env python3
"""Copy the records from the inventory API into a JSON file other services read."""

import http.client
import json
import os
import sys
import tempfile
import urllib.request

API = os.environ.get("SYNC_API", "http://127.0.0.1:8901/records")
OUTPUT = os.environ.get("SYNC_OUTPUT", "/var/lib/sync/records.json")
TIMEOUT = 10


def fetch():
    # urlopen raises HTTPError for 4xx and 5xx answers, URLError when nothing answers
    with urllib.request.urlopen(API, timeout=TIMEOUT) as response:
        records = json.load(response)
    if not isinstance(records, list):
        raise ValueError("the API did not return a list")
    return records


def write_atomically(path, records):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".records-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    try:
        records = fetch()
    except (OSError, ValueError, http.client.HTTPException) as e:
        print(f"sync: {API}: {e}", file=sys.stderr)
        return 1
    write_atomically(OUTPUT, records)
    print(f"done: {len(records)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**7. Run the same three tests.**

```console
$ (python3 /tmp/s/fake_api.py error & echo '[{"host": "keep-me"}]' > /tmp/s/records.json; sleep 1; SYNC_API=http://127.0.0.1:9500/records SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; echo "exit=$?"; cat /tmp/s/records.json; kill %1)
sync: http://127.0.0.1:9500/records: HTTP Error 500: database unavailable
exit=1
[{"host": "keep-me"}]
$ (python3 /tmp/s/fake_api.py silent & sleep 1; time timeout 20 env SYNC_API=http://127.0.0.1:9999/records SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; echo "exit=$?"; kill %1)
sync: http://127.0.0.1:9999/records: timed out

real	0m10.091s
user	0m0.057s
sys	0m0.014s
exit=1
$ (python3 -m http.server -d /tmp/s 9600 >/dev/null 2>&1 & sleep 1; stat -c 'inode %i' /tmp/s/records.json; SYNC_API=http://127.0.0.1:9600/good.json SYNC_OUTPUT=/tmp/s/records.json python3 /opt/sync/sync.py; echo "exit=$?"; stat -c 'inode %i %a' /tmp/s/records.json; ls -a /tmp/s; kill %1)
inode 15
done: 3 records
exit=0
inode 17 644
.
..
fake_api.py
good.json
records.json
```

The error leaves the old data and exits 1. The silent server is abandoned after the 10-second timeout
with a clear message. A good run replaces the file — new inode, mode 644 — and leaves no temporary
file behind.

**8. Fix the configuration and run it the way the timer does.**

```console
$ sudo sed -i 's#^SYNC_API=.*#SYNC_API=http://127.0.0.1:8901/records#' /etc/sync/sync.env && cat /etc/sync/sync.env
SYNC_API=http://127.0.0.1:8901/records
SYNC_OUTPUT=/var/lib/sync/records.json
$ sudo systemctl start sync.service; systemctl show sync.service -p Result -p ExecMainStatus
Result=success
ExecMainStatus=0
$ sudo journalctl -u sync.service -b --no-pager | tail -n 3
Sep 14 03:38:07 lima-nb-python-01 python3[971]: done: 3 records
Sep 14 03:38:07 lima-nb-python-01 systemd[1]: sync.service: Deactivated successfully.
Sep 14 03:38:07 lima-nb-python-01 systemd[1]: Finished sync.service - Copy inventory records for the dashboards.
$ jq -c '.[]' /var/lib/sync/records.json
{"host":"web01","role":"web","rack":"A3"}
{"host":"web02","role":"web","rack":"A4"}
{"host":"db01","role":"database","rack":"B1"}
```

Now "success" means something: it can only be reported after the API answered and the file was
replaced.

**9. Grade.** The checks ran against the grader's own failing, silent and good servers, the machine
rebooted, and the timer's first run after boot was checked too: all four passed in both passes.

## Common wrong turns

**Fixing only the port.** The dashboards come back, and the next API outage empties them again while
systemd reports success. The port was the trigger; the code was the incident.

**`except Exception: sys.exit(1)` in `fetch()`.** It fixes the exit status, but a library function
that exits the process cannot be reused or tested, and the catch-all still hides real bugs. Handle the
expected failures once, at the top.

**`requests.get(url, timeout=None)` or no timeout "because the API is fast".** It is fast until the
day it accepts connections and stops answering, which is precisely when the job must give up.

**Writing the temporary file in `/tmp`.** `os.replace` across filesystems fails with `OSError:
[Errno 18] Invalid cross-device link`. Create the temporary file next to the target.

**Forgetting the mode of the temporary file.** `mkstemp` makes it 0600; after the rename the
dashboards, running as other users, cannot read the new file. The failure appears only in the readers'
logs.

**`shutil.move` instead of `os.replace`.** When source and destination are on different filesystems,
`shutil.move` silently falls back to copy-then-delete, which is not atomic. `os.rename` is atomic on
POSIX; `os.replace` is the same operation, spelled so that it also overwrites on Windows.

**Testing against the real API by stopping it.** It works once, affects every other consumer, and
cannot produce the "accepts but never answers" case at all. A throwaway server can.

**Reading `systemctl status` and stopping there.** "Deactivated successfully" only says the process
exited 0. The job's own lines in the journal, and the file it wrote, are the evidence.

## Cheat sheet

```python
import sys, urllib.request, json, os, tempfile, http.client

urllib.request.urlopen(url, timeout=10)          # always a timeout
# HTTPError (4xx/5xx), URLError, TimeoutError are OSError; JSONDecodeError is ValueError
try:
    data = fetch()
except (OSError, ValueError, http.client.HTTPException) as e:
    print(f"job: {e}", file=sys.stderr)
    sys.exit(1)

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))   # same filesystem as the target
with os.fdopen(fd, "w") as f:
    json.dump(data, f); f.flush(); os.fsync(f.fileno())
os.chmod(tmp, 0o644)
os.replace(tmp, path)                            # atomic swap

if __name__ == "__main__":
    sys.exit(main())                             # return value → exit status
```

```console
$ systemctl list-timers NAME.timer              # last and next run
$ sudo journalctl -u NAME.service -b            # what the job printed this boot
$ systemctl show NAME.service -p Result -p ExecMainStatus
$ systemctl cat NAME.service                    # unit, drop-ins, EnvironmentFile path
$ sudo ss -ltnp                                 # who listens on which port
$ curl -sS URL; echo "exit=$?"                  # 7 = could not connect
$ stat -c '%i %a' FILE                          # inode and mode: in place or replaced?
$ timeout 20 CMD; echo "exit=$?"                # 124 = killed by timeout
$ python3 -m http.server -d DIR PORT            # serve files for a test
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Active, green, and not working* (topic journal `monitoring`) — A check is an exit status
- *Active, green, and not working* (topic journal `monitoring`) — A check must have a deadline
- *The log lines that were never written down* (topic journal `logging-journald`) — Asking precise questions

Manual pages: `man 5 systemd.exec`.

Documentation:

- https://docs.python.org/3/library/sys.html#sys.exit
- https://docs.python.org/3/library/urllib.request.html#urllib.request.urlopen
- https://docs.python.org/3/library/os.html#os.replace

## Review

1. Why did systemd report every run of the broken job as successful?

   > The script caught every exception, returned an empty list, wrote it and ended normally, so Python exited with status 0 — and a oneshot service whose main process exits 0 is a success.

2. What does `urllib.request.urlopen(url)` do when the server accepts the connection and never responds?

   > It blocks indefinitely: without a `timeout` argument the socket has no timeout. The same holds for `requests.get` without `timeout=`.

3. Which exception types should the job catch around the fetch, and why not `Exception`?

   > `OSError` (covers `URLError`, `HTTPError` and `TimeoutError`), `ValueError` (invalid JSON) and `http.client.HTTPException` (a truncated response). A catch-all would also hide real programming errors, which should crash with a traceback.

4. What can a reader of the file see while `open(path, "w")` and `json.dump` run?

   > An empty or partially written file, because opening for writing truncates it at once; if the writer crashes, the partial file remains.

5. Why must the temporary file be created in the same directory as the target?

   > `os.replace` is a rename, which is atomic only within one filesystem; across filesystems it fails with "Invalid cross-device link".

6. After switching to `tempfile.mkstemp` and `os.replace`, the dashboards cannot read the file. Why?

   > `mkstemp` creates the file with mode 0600 and the rename keeps that mode; the file needs `chmod 0644` (or whatever the readers need) before the rename.

7. How can you tell from the shell whether a program rewrote a file in place or replaced it?

   > Compare `stat -c %i FILE` before and after: an in-place write keeps the inode number, a replacement via rename gives the path a new inode.

8. The job worked when run by hand but failed under systemd. Where did the difference come from?

   > From `EnvironmentFile=/etc/sync/sync.env`, which set `SYNC_API` to port 8091; run by hand without it, the script used its correct default of 8901.
