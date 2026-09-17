---
title: Publish when complete, clean up however it ends
topics: [bash, linux-basics]
minutes: 35
---

An export is read by someone else. That one fact changes what "done" means for the script that
writes it: the warehouse importer does not wait for the script to finish, it takes whatever file has
the right name the moment the name appears. So a file that is still being written, or that was cut
short by a failure or a signal, is not a harmless leftover — it is a wrong answer delivered to another
system.

`export-orders` makes three mistakes that all come from forgetting that. It writes straight to the
name the importer watches. It keeps its work in a file with a fixed name in `/tmp`, shared by every
run on the machine. And it has no idea it can be stopped: nothing cleans up when it fails, and nothing
at all runs when it receives `SIGTERM`.

## What you should be able to do after this

- Publish a file atomically: write it under a name nobody reads, then `mv` it into place.
- Create private temporary files with `mktemp`, and say why a fixed name in `/tmp` is a bug and a
  security problem.
- Install an `EXIT` trap that removes temporary files on success, failure and signals, and know
  which shells run it when a signal kills the script.
- Explain why trapping `SIGTERM` yourself makes a script slower to stop, not safer.
- Stop a whole process group the way systemd stops a unit, and test a script against it.

## The mechanism

### Readers do not wait

A redirection such as `gzip -c work > "$DEST/$name"` creates the file with its final name first,
then fills it. From the first byte, a reader that lists the directory sees `orders-…csv.gz`. If the
script is killed, the disk is full, or an input fails half way, the file stays short under a name that
says "complete".

The fix is to separate *writing* from *publishing*. Write to a name the reader ignores — here a hidden
`.orders.XXXXXX` in the same directory — and when it is complete, `mv` it to the final name. Within one
file system `mv` is a `rename(2)`: the name points at the old inode or at the new one, never at
something in between. The temporary file has to be in the same directory (or at least the same file
system); across file systems `mv` falls back to copying, and the half-written window is back.

### Temporary files that belong to one run

`/tmp/export.tmp` is the same path for every run by every user. Two runs at once truncate and delete
each other's work. A file left behind by one user can make another user's run fail, because the
sticky `/tmp` directory will not let them replace it. And a predictable name in a world-writable
directory is a classic attack: another user creates it first, as a symlink to a file of yours.

`mktemp` creates a new file with a random name, exclusively and with mode `0600`, and prints the name.
It honours `TMPDIR`. `mktemp "$DEST/.orders.XXXXXX"` does the same in a chosen directory.

### Traps: what runs when a script ends

`trap cleanup EXIT` runs `cleanup` when the shell exits: at the end of the script, through `exit`,
because `set -e` stopped it — and, in bash, when a signal such as `SIGTERM`, `SIGINT` or `SIGHUP` kills
it. Bash handles those fatal signals by running the `EXIT` trap and then dying of the signal, so the
exit status still says what happened (128 + the signal number: 143 for `SIGTERM`). That one line is
enough cleanup for a bash script.

It is not portable. `dash`, which is `/bin/sh` on Ubuntu, does not run an `EXIT` trap when a signal
kills it; a POSIX `sh` script has to trap the signals too. Which shell runs the script is decided by
its `#!` line, not by the shell you test it from.

### Trapping `SIGTERM` yourself makes a script wait

When bash has **no** trap for `SIGTERM`, the signal is handled at once, even while the script is
waiting for a foreground command: the `EXIT` trap runs and bash exits. When the script **does** trap
`SIGTERM`, bash runs that trap only after the foreground command returns — and then carries on with
the next line unless the trap exits. A trap such as `trap 'echo stopping' TERM` turns "stop now" into
"finish this command, print something, and keep going". If the command is blocked — reading from a
pipe nobody writes to, waiting on a stalled network file — the script does not stop at all until
systemd sends `SIGKILL`, and `SIGKILL` runs no trap.

So in bash, trap `EXIT` for cleanup and leave `SIGTERM` alone, unless the script has a real reason to
finish its current step first; in that case start the long command in the background and `wait` for
it, because `wait` is interrupted by a trapped signal.

### Stopping a group, as systemd does

When systemd stops a unit, it sends `SIGTERM` to every process in the unit's control group, waits
(90 seconds by default), and then sends `SIGKILL`. From a shell, `setsid cmd &` puts a command in a
new session and process group, and `kill -TERM -- -PID` signals the whole group — the same shape.
That is how this lab's grader stops the export, and it is the honest way to test cleanup: a signal
sent to the script alone is a situation that rarely happens.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, GNU bash 5.3.9, before any change.

An order file that cannot be read, and an unprivileged user running the export into a directory of
its own:

```console
$ sudo chmod 000 /srv/orders/afternoon.csv; sudo -u nobody env EXPORT_DEST=/tmp/exp1 bash -c 'mkdir -p /tmp/exp1; export-orders' 2>&1; echo "exit status: $?"; ls -l /tmp/exp1 /tmp/export.tmp; sudo chmod 644 /srv/orders/afternoon.csv
tail: cannot open '/srv/orders/afternoon.csv' for reading: Permission denied
exported to /tmp/exp1/orders-2026-09-16.csv.gz
exit status: 0
/tmp/exp1:
total 4
-rw-r--r-- 1 nobody nogroup 64 Sep 16 16:06 orders-2026-09-16.csv.gz
ls: cannot access '/tmp/export.tmp': No such file or directory
```

A 64-byte export with the morning's rows only, published under the final name, with exit status 0.
The same happens when the destination itself cannot be written:

```console
$ export-orders 2>&1; echo "exit status: $?"
/usr/local/bin/export-orders: line 13: /srv/exports/orders-2026-09-16.csv.gz: Permission denied
exported to /srv/exports/orders-2026-09-16.csv.gz
exit status: 0
```

Now an export stopped half way. The second order file is a named pipe, so reading it blocks — the
export is mid-way and stays there — and the whole process group gets `SIGTERM`, as it would from
systemd:

```console
$ mkdir -p /tmp/slow/src /tmp/slow/dest && printf 'id,sku,qty\n1,A,1\n' > /tmp/slow/src/a.csv && mkfifo /tmp/slow/src/b.csv && sudo rm -f /tmp/export.tmp; (EXPORT_SRC=/tmp/slow/src EXPORT_DEST=/tmp/slow/dest setsid export-orders & echo $! > /tmp/slow/pid); sleep 1; kill -TERM -- -$(cat /tmp/slow/pid); sleep 1; ls -l /tmp/slow/dest /tmp/export.tmp; cat /tmp/export.tmp
-rw-rw-r-- 1 northelks northelks 17 Sep 16 16:06 /tmp/export.tmp

/tmp/slow/dest:
total 0
id,sku,qty
1,A,1
```

The shared work file is left in `/tmp` with half an export in it, owned by whoever ran last.

Three experiments show what a trap does with a signal. With only an `EXIT` trap, bash cleans up and
dies of the signal; `dash` does not run the trap at all; and a `TERM` trap waits for the foreground
command, then lets the script carry on:

```console
$ bash -c 'trap "echo cleaned" EXIT; sleep 5; echo after' & sleep 1; kill -TERM $!; wait $!; echo "status=$?"
cleaned
status=143
$ sh -c 'trap "echo cleaned" EXIT; kill -TERM $$; echo after'; echo "status=$?"
status=143
Terminated                 sh -c 'trap "echo cleaned" EXIT; kill -TERM $$; echo after'
$ bash -c 'trap "echo trap ran" TERM; sleep 3; echo after' & sleep 1; kill -TERM $!; wait $!; echo "status=$?"
trap ran
after
status=0
```

The last one is the trap you do not want: it ran two seconds late, and the script then went on as if
nothing had happened.

After the fix — `set -euo pipefail`, a private work file from `mktemp`, the partial export as a hidden
`.orders.XXXXXX` in the destination, and an `EXIT` trap that removes both — the same interruption,
looking at the destination before and after the signal:

```console
$ mkdir -p /tmp/slow/src /tmp/slow/dest && printf 'id,sku,qty\n1,A,1\n' > /tmp/slow/src/a.csv && mkfifo /tmp/slow/src/b.csv; (EXPORT_SRC=/tmp/slow/src EXPORT_DEST=/tmp/slow/dest setsid export-orders & echo $! > /tmp/slow/pid); sleep 1; ls -la /tmp/slow/dest; kill -TERM -- -$(cat /tmp/slow/pid); sleep 1; ls -la /tmp/slow/dest; ls /tmp/export.tmp 2>&1
total 0
drwxrwxr-x 2 northelks northelks  60 Sep 16 16:10 .
drwxrwxr-x 4 northelks northelks 100 Sep 16 16:10 ..
-rw------- 1 northelks northelks   0 Sep 16 16:10 .orders.NcK4lp
total 0
drwxrwxr-x 2 northelks northelks  40 Sep 16 16:10 .
drwxrwxr-x 4 northelks northelks 100 Sep 16 16:10 ..
ls: cannot access '/tmp/export.tmp': No such file or directory
```

While it runs, the only file in the destination is a hidden, private one the importer ignores; after
the signal there is nothing at all. And a good run still publishes the whole export:

```console
$ rm /tmp/slow/src/b.csv; mkdir -p /tmp/good && EXPORT_DEST=/tmp/good export-orders; echo "exit status: $?"; zcat /tmp/good/orders-*.csv.gz
exported to /tmp/good/orders-2026-09-16.csv.gz
exit status: 0
id,sku,qty
1003,WASHER-6,200
1001,BOLT-M6,40
1002,NUT-M6,40
```

## Common wrong turns

- **Deleting the temporary file at the end.** `rm $tmp` as the last line runs only when every line
  before it succeeded; a failure or a signal skips it. That is the original script.
- **Adding `trap '…' TERM` "to be safe".** In bash it delays the reaction to the signal until the
  current command ends, and a trap that does not `exit` lets the script continue. The `EXIT` trap
  already runs when `SIGTERM` kills bash.
- **Testing cleanup with `sh script`.** `dash` does not run an `EXIT` trap on a signal; run the script
  the way its `#!` line says.
- **Writing the temporary file to `/tmp` and moving it to `/srv/exports`.** Across file systems `mv`
  copies, and the importer can see the copy in progress. Keep the partial file in the destination
  directory, under a name the reader ignores.
- **A name with `$$` in it.** `/tmp/export.$$` is unique per process but predictable, and it is not
  created exclusively or privately. `mktemp` is.
- **Checking only the happy path.** A cleanup that was never exercised does not work. Test failure and
  interruption on purpose, with a signal to the process group.
- **Relying on `set -e` for cleanup.** It stops the script; it does not remove anything.

## Cheat sheet

```bash
set -euo pipefail
work=$(mktemp)                                  # private, 0600, honours TMPDIR
part=$(mktemp "$DEST/.orders.XXXXXX")           # same directory as the final file
cleanup() { rm -f -- "$work" "$part"; }
trap cleanup EXIT            # bash: also runs when SIGTERM/SIGINT/SIGHUP kill the script

produce > "$part"
chmod 644 "$part"
mv -f -- "$part" "$DEST/$name"                  # atomic within one file system

long_command & wait $!                          # a trapped signal interrupts wait
setsid cmd & kill -TERM -- -$!                  # signal a whole process group
```

## Going deeper

- `man 1 bash`, *SIGNALS* and the `trap` builtin, for exactly when traps run.
- `man 1 mktemp` and `man 2 rename`.
- `man 5 systemd.kill`, `KillMode=` and `TimeoutStopSec=`, for how a unit is stopped.
- `man 7 signal`, for the default action of each signal.

## Review

1. Why is `gzip -c work > "$DEST/orders-$(date +%F).csv.gz"` unsafe when an importer watches `$DEST`?

   > The redirection creates the final name before gzip has written anything, so the importer can
   > take a partial file; a failure or a signal leaves it partial for good.

2. Why must the partial file live in the same directory, or file system, as the final one?

   > Only a rename within one file system is atomic; across file systems `mv` copies, and the copy is
   > visible while it is being written.

3. Does `trap cleanup EXIT` run when bash is killed by `SIGTERM`? And in `dash`?

   > In bash, yes: bash runs the `EXIT` trap and then dies of the signal, with status 143. `dash` does
   > not run it, so a POSIX `sh` script has to trap the signals as well.

4. What changes when a bash script traps `SIGTERM` itself?

   > The trap runs only after the current foreground command returns, and the script continues
   > afterwards unless the trap exits — so the script stops later, or not at all if that command is
   > blocked.

5. What three problems does a fixed path such as `/tmp/export.tmp` cause?

   > Concurrent runs overwrite and delete each other's work, a leftover owned by another user makes
   > later runs fail, and a predictable name in a world-writable directory can be pre-created as a
   > symlink by someone else.

6. How does systemd stop a running service?

   > It sends `SIGTERM` to every process in the unit's control group, waits for `TimeoutStopSec=`, then
   > sends `SIGKILL` to whatever remains.
