---
title: A service that nobody can hear, and a stop that lands in the middle
topics: [python, logging-journald]
minutes: 35
---

Two properties of a long-running program matter more than its speed: you can see what it is doing,
and you can stop it without breaking anything. This worker has neither, and both failures come from
defaults that are right in a terminal and wrong in a service.

Python chooses its output buffering from what standard output is attached to. On a terminal it is
line-buffered — you see each line as it is printed. Under systemd, standard output is a pipe to the
journal, so it is block-buffered: about 8 KiB of progress lines accumulate inside the process before
anything is written. The worker is not stuck; it is inaudible.

Stopping is the same story. `SIGTERM` ends a Python program where it stands. If the work of one item
spans two writes and a slow call in between, "where it stands" is the middle of a row.

## What you should be able to do after this

- Say how Python chooses buffering for `sys.stdout`, and what changes under systemd, cron or a pipe.
- Make output appear promptly: `line_buffering`, `flush=True`, `-u`/`PYTHONUNBUFFERED`, or the
  logging module.
- Handle `SIGTERM` so a worker finishes its current step and exits, instead of dying inside it.
- Write a record in one operation, so no reader ever sees half of it.
- Order the ledger, the state and the message so that a stop between any two of them is safe.
- Replace a state file atomically with `os.replace()`.

## The mechanism

### Where the buffering comes from

`sys.stdout` is a `TextIOWrapper` over a buffered binary writer. Python chooses:

- **interactive** (a terminal): line-buffered, flushed at every newline;
- **not interactive** (a pipe, a file, the journal): block-buffered, flushed when the buffer fills
  (8 KiB) or the program exits normally;
- **`stderr`**: always unbuffered-ish — write-through, so error messages appear immediately.

That is why a program that looks chatty in a terminal goes quiet as a service, and why the last
lines of a crashed program are sometimes missing altogether: the process died before the buffer was
flushed.

Four ways to fix it, in the order they are usually reached for:

```python
print("…", flush=True)                      # one call
sys.stdout.reconfigure(line_buffering=True) # once, at the top of the program
python3 -u …  /  PYTHONUNBUFFERED=1         # from outside, in the unit
logging.basicConfig(stream=sys.stdout)      # the logging module flushes each record
```

A program that belongs in a service should not depend on its caller for this: `reconfigure` or
`logging` in the program, and the unit can still set `PYTHONUNBUFFERED=1` as a belt.

### What `SIGTERM` does to Python

By default `SIGTERM` terminates the process immediately — no `finally`, no `atexit`, no flush.
(`SIGINT` is the exception: Python turns it into `KeyboardInterrupt`.) A worker that must stop
cleanly installs a handler that records the request and returns:

```python
stopping = False
def stop(signum, frame):
    global stopping
    stopping = True
signal.signal(signal.SIGTERM, stop)
```

The handler runs between bytecode instructions, sets a flag, and the main loop checks it at a point
where stopping is safe — after finishing the item in hand, before starting the next. systemd allows
`TimeoutStopSec=` (90 s by default) for that, then sends `SIGKILL`, which no program can catch: the
work between two safe points must be shorter than the timeout.

### One record, one write

The broken worker writes a row in two parts, with the slow call between them:

```python
ledger.write(f"{name},")
ledger.flush()
time.sleep(...)           # the accounting system
ledger.write(f"{amount}\n")
```

A stop in the middle leaves `invoice-002,` on disk — a row that is neither there nor not there. Do
the slow work first, then write the complete row in one call. A single `write` of a short line to a
file opened in append mode is not formally atomic, but it is one system call, and the window is a few
microseconds rather than seconds. When several processes append to the same file, `O_APPEND` keeps
each write's bytes together.

### The order of the three steps

For each item there are three things to do: append the ledger row, record the item as done, and say
so. The order decides what a stop between them costs:

| Order | A stop in between means |
|---|---|
| state, then ledger | the item is marked done and never ingested — data lost |
| ledger, then state | the item is ingested again after the restart — a duplicate |
| ledger, then state, with a complete row and an atomic state file | the item is ingested once |

Ledger first is the right order — losing work is worse than repeating it — but it only holds when
*neither* file can be left half written. That is why the state file is replaced with `os.replace()`:
the name points at the old file or the new one, never at a truncated one. A `json.dump` straight into
the target truncates it first, so a stop there leaves an unreadable state file and the next start
re-ingests everything.

### Make it idempotent when you can

Better than any ordering is work that can be repeated harmlessly: an upsert by invoice number, a
target that ignores a duplicate key, a hash-named file. Then "at least once" is enough and the state
file is only an optimisation. Not every system offers that; this one does not, so the order and the
atomicity carry the weight.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, Python 3.14.4, before any change.

Right after boot, with the service running:

```console
$ systemctl is-active ingest.service; cat /var/lib/ingest/ledger.csv; sudo journalctl -u ingest.service -b --no-pager -o cat | tail -3
active
invoice-001.txt,Started ingest.service - Ingest the files dropped into the queue.
```

That line is two things at once: the ledger's content, `invoice-001.txt,` with no amount and no
newline, and the journal's line running straight into it. The journal has nothing from the worker
itself. Dropping a new file in shows the same asymmetry — the ledger grows, the journal stays silent:

```console
$ sudo sh -c 'printf "77.00\n" > /srv/ingest/queue/invoice-009.txt'; sleep 3; cat /var/lib/ingest/ledger.csv; echo "--- journal:"; sudo journalctl -u ingest.service -b --no-pager -o cat | tail -2
invoice-001.txt,120.00
invoice-002.txt,45.50
invoice-003.txt,8.75
--- journal:
Started ingest.service - Ingest the files dropped into the queue.
```

What Python thinks it is writing to, in a pipe and in a service:

```console
$ python3 -c "import sys; print(type(sys.stdout.buffer).__name__, sys.stdout.line_buffering, sys.stdout.write_through)" | cat
BufferedWriter False False
$ sudo systemd-run --wait --pipe -q python3 -c "import sys; print('in a service, line_buffering =', sys.stdout.line_buffering)"
in a service, line_buffering = False
```

The effect is easiest to see with timestamps: the same loop, buffered and unbuffered, printing three
lines four tenths of a second apart:

```console
$ (python3 -c "
import sys, time
for i in range(3):
    print('tick', i)
    time.sleep(0.4)
" | while read -r line; do echo "$(date +%T.%2N) $line"; done)
"17:11:54.872492754 tick 0"
"17:11:54.877795296 tick 1"
"17:11:54.881644713 tick 2"
$ (python3 -u -c "
import sys, time
for i in range(3):
    print('tick', i)
    time.sleep(0.4)
" | while read -r line; do echo "$(date +%T.%2N) $line"; done)
"17:11:54.908480963 tick 0"
"17:11:55.323475391 tick 1"
"17:11:55.725810478 tick 2"
```

Buffered, all three lines arrive in the same millisecond — when the program exits. Unbuffered, they
arrive as they happen.

After the fix — `sys.stdout.reconfigure(line_buffering=True)`, a `SIGTERM` handler that sets a flag,
the whole row written after the slow call, and the state file replaced atomically:

```console
$ sudo sh -c 'printf "12.00\n" > /srv/ingest/queue/invoice-010.txt'; sleep 3; sudo journalctl -u ingest.service -b --no-pager -o cat | tail -2; tail -2 /var/lib/ingest/ledger.csv
Started ingest.service - Ingest the files dropped into the queue.
ingested invoice-010.txt
invoice-009.txt,77.00
invoice-010.txt,12.00
$ sudo systemctl stop ingest.service; systemctl show ingest.service -p Result -p ExecMainStatus; sudo journalctl -u ingest.service -b --no-pager -o cat | tail -2; tail -1 /var/lib/ingest/ledger.csv
Result=success
ExecMainStatus=0
ingest.service: Deactivated successfully.
Stopped ingest.service - Ingest the files dropped into the queue.
invoice-010.txt,12.00
```

The journal reports each file as it is ingested, the stop is a clean success, and the last row is
complete.

## Common wrong turns

- **`PYTHONUNBUFFERED=1` in the unit and nothing in the program.** It fixes this service and not the
  same program run from cron, from a script, or by hand into a log file.
- **`flush=True` on one print.** There is usually more than one place that reports progress, and the
  next one added will not have it.
- **Doing the work inside the signal handler.** A handler should set a flag and return; writing files
  from it invites a second signal in the middle, and it can interrupt the very write it is trying to
  protect.
- **`sys.exit()` from the handler.** It raises `SystemExit` at an arbitrary point of the main
  program, which is the problem it was meant to solve.
- **Ignoring `SIGTERM` altogether** to "make sure the work finishes". systemd sends `SIGKILL` after
  the stop timeout, and that cannot be caught.
- **Writing the state before the ledger row**, to avoid duplicates. Now a stop between them loses the
  invoice instead, which is worse.
- **`json.dump(state, open(path, "w"))`.** The file is truncated at the moment of the call; a stop in
  the middle leaves it unreadable, and the next start re-ingests everything.

## Cheat sheet

```python
sys.stdout.reconfigure(line_buffering=True)   # in the program, once
print("…", flush=True)                        # per call
# from outside: python3 -u, or PYTHONUNBUFFERED=1 in the unit

stopping = False
def stop(signum, frame):
    global stopping; stopping = True
signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
while not stopping:
    ...                                       # check the flag at a safe point

with open(ledger, "a", encoding="utf-8") as f:
    f.write(f"{name},{amount}\n")             # one complete record per write

fd, tmp = tempfile.mkstemp(dir=os.path.dirname(state))
… ; os.fsync(f.fileno()) ; os.replace(tmp, state)
```

```console
journalctl -fu ingest              # follow a service's output
systemd-run --wait --pipe -q cmd   # run something with a service's stdout
systemctl show unit -p Result -p ExecMainStatus
```

## Going deeper

- `sys.stdout` and `io.TextIOWrapper.reconfigure` in the Python documentation; `python3 -u`.
- The `signal` module, especially "execution of Python signal handlers".
- `man 5 systemd.kill` (`KillSignal=`, `TimeoutStopSec=`) and `man 5 systemd.exec` (`StandardOutput=`).
- The logging journal in this repository, for what the journal does with a service's output.

## Review

1. Why does a Python program print promptly in a terminal and go silent as a systemd service?

   > Standard output is line-buffered when it is a terminal and block-buffered when it is a pipe, and
   > a service's output is a pipe to the journal.

2. Name two ways to make the program's own output prompt, and one from outside it.

   > In the program: `sys.stdout.reconfigure(line_buffering=True)` or `print(…, flush=True)` (the
   > logging module also flushes each record). From outside: `python3 -u` or `PYTHONUNBUFFERED=1`.

3. What does Python do with `SIGTERM` by default, and what should a worker do instead?

   > It ends the process immediately, without `finally` or flushing. A worker installs a handler that
   > sets a flag and checks it at a point where stopping is safe.

4. Why write the whole ledger row after the slow call rather than in two parts around it?

   > A stop between the two writes leaves a row with no amount; one write of the complete row leaves
   > either nothing or a whole row.

5. The ledger row is written before the state file. What does a stop between them cost, and why is
   that the right order?

   > The item is ingested again after a restart — a duplicate. The other order would lose the item
   > entirely, and losing work is worse than repeating it.

6. Why must the state file be replaced with `os.replace()` rather than rewritten in place?

   > Rewriting truncates it first, so a stop in the middle leaves an unreadable state and the next
   > start repeats everything; a rename is atomic.
