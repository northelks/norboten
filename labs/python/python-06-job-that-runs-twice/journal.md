---
title: One writer at a time, and a file that is only ever whole
topics: [python, boot-systemd]
minutes: 40
---

A timer that starts a job every minute is a promise about how often the job *starts*, not about how
long it takes. The day the catalogue grows past a minute's work, two rebuilds run at once, and they
are both writing the same file. Nobody planned that; it arrives on its own.

Two separate mistakes make it dangerous. Nothing stops the second run — the script names a lock file
and never takes it. And the file being rebuilt is the file the shop reads, written product by
product, so during a rebuild there is no moment at which it is a complete price list. Either
mistake alone is survivable. Together they explain a shop that served half its catalogue.

## What you should be able to do after this

- Take an advisory lock with `flock`, without waiting, and release it by ending the process.
- Say why a lock file that is merely created and deleted is not a lock.
- Replace a file's contents atomically with a temporary file and `os.replace()`.
- Explain what a reader sees during each of the two kinds of write.
- Know what systemd does when a timer fires while the last run is still going.

## The mechanism

### The kernel already has a lock

`flock(2)` puts an advisory lock on an open file. The rules are short: one exclusive holder at a
time; `LOCK_NB` makes the call fail instead of waiting; and the lock lives as long as the open file
description — so when the process ends, for any reason, the kernel releases it. There is nothing to
clean up after a crash, and no stale lock to inherit.

```python
fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:            # BlockingIOError, errno EWOULDBLOCK
    return "another run holds it"
```

Two details matter. Keep `fd` open for the whole run: closing it releases the lock, so a `with
open(...)` around just the acquisition is a bug. And *advisory* means only that processes which ask
are held back; a program that never takes the lock writes anyway. The lock is a convention among
the programs that share the resource, enforced by the kernel for those who join in.

The alternative most people write first — "if the lock file exists, exit; else create it; delete it
at the end" — has two holes. Between the test and the creation another process can do the same
(a race), and a run that dies leaves the file behind so every later run refuses. `flock` has
neither problem.

`flock` locks are per file description, so a fork inherits the lock, and two different paths to the
same file (a bind mount, a symlink) are still the same inode and the same lock. On NFS, use
`fcntl(F_SETLK)` instead — or a lock service.

### What a reader sees

Writing `open(OUT, "w")` and then filling the file leaves the live file in every intermediate state:
truncated to nothing, then half a JSON object, then whole. A reader that opens it at the wrong
moment gets a parse error or — worse for a price list — a syntactically valid subset.

`os.replace(tmp, path)` is a `rename(2)` within one file system: the directory entry points at the
old inode or the new one, and never at something in between. Readers that have the old file open
keep reading it to the end; readers that open afterwards get the new one. The recipe is always the
same:

```python
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))   # same file system, private
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(data, f); f.flush(); os.fsync(f.fileno()) # on disk, not just in the page cache
os.chmod(tmp, 0o644)                                    # mkstemp makes it 0600
os.replace(tmp, path)
```

With that, a second writer is a waste of work rather than a corruption — which is why both halves
are worth having even when the lock is in place.

### Overlap is systemd's business too

A `oneshot` service that is still running when its timer fires again does not start a second copy:
systemd sees the unit as active and the job is queued or dropped, depending on the unit's job mode.
That is exactly why the lock still matters here: a rebuild started **by hand**, by Ansible, or by
another timer unit is not the same unit, and systemd has no view of it at all. `RefuseManualStart=`
and the unit's `Conflicts=` are policy for the unit, not protection for the file.

`OnUnitActiveSec=` (this timer) measures from the end of the last activation, so it will not chase a
slow job; `OnCalendar=` or `OnUnitInactiveSec=` behave differently. Knowing which one a timer uses
is part of knowing whether overlap is possible at all.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, Python 3.14.4, before any change.

Two rebuilds started a second apart both run to the end, and both report success:

```console
$ sudo sh -c 'python3 /opt/pricing/rebuild.py & sleep 0.8; python3 /opt/pricing/rebuild.py; echo "second run exit: $?"; wait'
rebuilt 4 prices
rebuilt 4 prices
second run exit: 0
```

While a rebuild is running, a reader finds the price list unreadable — twice in a row here, and
whole only once the run has finished:

```console
$ sudo sh -c 'python3 /opt/pricing/rebuild.py & sleep 0.9; for i in 1 2 3; do python3 -c "import json;print(json.load(open(\"/var/lib/pricing/prices.json\")))" 2>&1 | tail -1; sleep 0.4; done; wait'
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 4 column 1 (char 39)
json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 5 column 1 (char 59)
rebuilt 4 prices
{'BOLT-M6': 0.56, 'NUT-M6': 0.35, 'WASHER-6': 0.14, 'SPANNER-13': 9.1}
```

What the lock the script never takes would have done, in eight lines:

```console
$ python3 - <<'PY'
import fcntl, os, subprocess, sys
fd = os.open("/tmp/demo.lock", os.O_CREAT | os.O_RDWR, 0o644)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
print("first holder: got the lock")
code = "…second process tries the same…"
subprocess.run([sys.executable, "-c", code])
PY
second holder refused: BlockingIOError 11
first holder: got the lock
```

(errno 11 is `EWOULDBLOCK`: the lock is held, and `LOCK_NB` means do not wait. The two lines arrive
out of order because the parent's own output is still buffered — see the worker lab.)

After the fix — the lock taken before the work and held for the whole run, the prices built in
memory and the file replaced in one step:

```console
$ sudo sh -c 'python3 /opt/pricing/rebuild.py & sleep 0.8; python3 /opt/pricing/rebuild.py; echo "second run exit: $?"; wait'
second run exit: 1
rebuilt 4 prices
rebuild: another rebuild holds /run/pricing-rebuild.lock
$ sudo sh -c 'python3 /opt/pricing/rebuild.py & sleep 0.9; for i in 1 2 3; do python3 -c "import json;print(sorted(json.load(open(\"/var/lib/pricing/prices.json\"))))" 2>&1 | tail -1; sleep 0.4; done; wait'
['BOLT-M6', 'NUT-M6', 'SPANNER-13', 'WASHER-6']
['BOLT-M6', 'NUT-M6', 'SPANNER-13', 'WASHER-6']
rebuilt 4 prices
['BOLT-M6', 'NUT-M6', 'SPANNER-13', 'WASHER-6']
```

The second run refuses in milliseconds with a message and a non-zero status, and every read during a
rebuild sees the full list.

## Common wrong turns

- **`if os.path.exists(LOCK): sys.exit()` … `os.remove(LOCK)`.** Two runs can pass the test in the
  same instant, and a run that dies leaves the file behind so every later run refuses. This is the
  lock file without the lock.
- **Taking the lock in a `with` block, or closing the file.** The lock is released when the last file
  descriptor for that open file description is closed; the rebuild then has no protection at all.
- **`fcntl.flock(fd, fcntl.LOCK_EX)` without `LOCK_NB`.** The second run waits instead of refusing,
  so every minute adds another waiting rebuild and the queue never drains.
- **Writing the temporary file in `/tmp`.** `os.replace()` across file systems raises
  `OSError: [Errno 18] Invalid cross-device link`; the temporary file belongs in the target's
  directory.
- **Forgetting `os.chmod` after `mkstemp`.** The new file is `0600`, so the shop's reader loses access
  the first time the rebuild runs.
- **Leaving the lock to systemd.** It knows about its own unit; a run started by hand or by another
  tool is invisible to it.
- **Locking the output file itself.** The rename replaces the inode, so the lock the next process
  takes is on a different file. Lock a path that nobody replaces.

## Cheat sheet

```python
import fcntl, os, tempfile, json

fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)   # keep fd open for the whole run
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit("another run holds the lock")

tmp_fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), prefix=".prices-")
with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
    json.dump(prices, f); f.flush(); os.fsync(f.fileno())
os.chmod(tmp, 0o644)
os.replace(tmp, OUT)        # atomic within one file system
```

```console
flock -n /run/job.lock -c 'command'      # the same lock, from a shell
systemctl list-timers --no-pager         # what is due, and when it last ran
systemctl show unit -p Result -p ExecMainStatus
```

## Going deeper

- `man 2 flock`, `man 1 flock`, and `fcntl.flock` in the Python documentation.
- `man 2 rename` and `os.replace`.
- `man 5 systemd.timer` — `OnUnitActiveSec=` against `OnCalendar=` — and `man 5 systemd.unit` for
  what happens when a unit is already active.
- The `filelock` package, when a project wants the same thing with a context manager and Windows
  support.

## Review

1. Why is "create the lock file if it does not exist, delete it at the end" not a lock?

   > The test and the creation are two steps, so two processes can both pass; and a run that dies
   > leaves the file, which blocks every later run.

2. What releases a `flock` lock?

   > Closing the last descriptor of that open file description, or the process ending — the kernel
   > does it, so a crash leaves nothing behind.

3. What does `LOCK_NB` change?

   > The call fails with `BlockingIOError` (`EWOULDBLOCK`) instead of waiting, which is what lets the
   > second run refuse immediately rather than queue up.

4. What does a reader see while `open(path, "w")` is being filled, and what does it see with
   `os.replace()`?

   > With the direct write: a truncated file, then partial content. With the replace: the old file or
   > the new one, never anything in between.

5. Why must the temporary file be in the same directory as the target?

   > `os.replace()` is a rename, which only works within one file system; across file systems it
   > raises `EXDEV`, and any copy-based fallback brings back the half-written window.

6. A timer fires while its own service is still running. Does that start a second copy — and why is
   the lock still needed?

   > No: systemd sees the unit as active. The lock is for the runs systemd does not know about — by
   > hand, from Ansible, from another unit.
