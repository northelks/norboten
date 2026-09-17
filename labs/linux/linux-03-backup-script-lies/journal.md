---
title: A script that cannot fail is not a backup
topics: [bash, linux-basics]
minutes: 35
---

The script has written "backup OK" every night for a year. It is not lying on purpose: it ends with
`echo "backup OK"` and `exit 0`, unconditionally, so there is no state of the world in which it says
anything else. The restore that failed did not reveal a new bug — it revealed that nobody had ever
had any information about whether the backup worked.

Underneath that there are two genuine defects, both classics. Unquoted variables, so a filename with
a space in it becomes two filenames, neither of which exists. And a `cron` entry that works when you
test it by hand and not when cron runs it, because cron's environment is almost nothing like yours.

Each of the three is worth knowing on its own. Together they make the lesson of the lab, which is
that **a script's job is not to do the work; it is to tell you the truth about whether the work
happened.**

## What you should be able to do after this

- Quote variables and command substitutions so that filenames with spaces, tabs and newlines survive.
- Explain what word splitting and globbing do to an unquoted expansion, and name the two safe ways to
  hand a list of files to another program.
- Make a script fail loudly: non-zero exit, a message on stderr, and no success written to a log.
- Say what `set -e`, `set -u` and `set -o pipefail` each do, and where `set -e` does not save you.
- Diagnose a job that works in your shell and fails under cron, and fix it in the crontab rather than
  by guessing.
- Write a log line that will let someone a year from now tell a good night from a bad one.

## The mechanism

### The lie itself

```bash
cd $SRC
FILES=$(find . -type f)
tar -czf $ARCHIVE $FILES 2>/dev/null
echo "$(date -Is) backup OK: $ARCHIVE" >> $LOG
exit 0
```

Four lines, four independent failures of honesty:

1. `cd $SRC` is not checked. If the directory does not exist, `cd` fails, prints to stderr, and the
   script carries on **in whatever directory it was already in** — which for cron is `/root` or the
   user's home. `find .` then archives that.
2. `2>/dev/null` throws away tar's complaints. Every "file not found" caused by the quoting bug goes
   to the same place.
3. tar's exit status is never examined. Neither is `find`'s, nor `cd`'s.
4. `echo … backup OK` and `exit 0` are unconditional. The script has no code path that reports
   failure, so the log is a record of the script having run, not of a backup having happened.

That last point is the one to carry away. A log line that is always the same carries no information.
The information content of "backup OK" is exactly zero if there is no "backup FAILED" to compare it
with.

### Word splitting, in the order it happens

When bash expands `$FILES`, the result is not a string handed to tar. It goes through two more steps:

```
   $FILES          →  the variable's value
   word splitting  →  cut into words at every character in IFS (space, tab, newline by default)
   globbing        →  any word containing * ? [ ] is expanded against the filesystem
```

So with `FILES` containing `./invoices/2026 Q3 summary.csv`, tar receives **four** arguments:
`./invoices/2026`, `Q3`, `summary.csv` — and none of those files exists. Add a file called `report*`
and the glob step will match things you never named. This is why the archive held "a fraction of the
files": exactly the files whose names had no spaces.

Quoting stops both steps:

```bash
tar -czf "$ARCHIVE" "$FILE"        # one argument, whatever is in it
```

The rules worth internalising, because they are the whole subject:

| written | you get |
|---|---|
| `$var` | split into words, then globbed — almost never what you want |
| `"$var"` | exactly one argument, byte for byte |
| `$(cmd)` | the output, split and globbed |
| `"$(cmd)"` | the output as one argument, with trailing newlines stripped |
| `$@` | split again — a bug |
| `"$@"` | each argument preserved separately — **the only correct way to pass arguments on** |
| `"$*"` | all arguments joined into one string with spaces |

Two places where quoting is *not* needed, so you can recognise them rather than fearing them: inside
`[[ ]]` (bash's test keyword does not split), and on the right-hand side of a plain assignment
(`x=$y` is safe). Everywhere else, quote. A useful rule of thumb: if you are not certain, quote —
there is no case where correct quoting breaks a correct script.

### Handing a list of files to a program

`FILES=$(find …)` is broken in principle, not just in this script: a newline-separated string in a
variable cannot represent a filename containing a newline, and filenames may contain newlines. Three
robust patterns replace it:

```bash
# 1. Let the other program do the walking — best when it can
tar -czf "$ARCHIVE" -C "$SRC" .

# 2. find … -exec, with + to batch arguments
find "$SRC" -type f -exec tar -rf "$TAR" {} +

# 3. NUL-separated, for anything that supports it — the only fully safe separator,
#    because NUL is the one byte a filename cannot contain
find "$SRC" -type f -print0 | xargs -0 tar -czf "$ARCHIVE"
find "$SRC" -type f -print0 | while IFS= read -r -d '' f; do process "$f"; done
```

The first is the right answer here, and it is worth seeing why it is better than merely safe. `tar
-C "$SRC" .` changes directory inside tar, so the archive holds `./invoices/march.csv` rather than
`/srv/data/invoices/march.csv` — relative paths, which is what you want at restore time (you can
unpack them anywhere, and tar will not refuse to overwrite from an absolute path). It also archives
empty directories, symlinks and permissions, which a `find -type f` list silently drops.

That `while IFS= read -r` incantation in pattern 3 is worth decoding once, since it appears in every
careful shell script: `IFS=` stops leading and trailing whitespace being trimmed, `-r` stops
backslashes being interpreted, and `-d ''` reads up to a NUL instead of a newline.

### Failing loudly

Three mechanisms, and you want all three.

**Exit status.** The caller — cron, a systemd timer, a monitoring check, a human — learns success or
failure from `$?` and nothing else. `0` is success; anything else is failure. Check the commands that
matter:

```bash
tar -czf "$ARCHIVE" -C "$SRC" . || fail "could not write $ARCHIVE"
```

**stderr.** Diagnostics go to file descriptor 2, and data goes to 1. This is not a stylistic
preference: it is what lets `backup-data > /dev/null` stay quiet on success and still shout on
failure, and it is why cron mails you stderr.

```bash
echo "backup-data: $*" >&2
```

**The log.** Write a line for both outcomes, with a timestamp, so the log answers questions:

```bash
log()  { echo "$(date -Is) $*" >> "$LOG"; }
fail() { echo "backup-data: $*" >&2; log "backup FAILED: $*"; exit 1; }
```

A small function pair like that is the difference between a script that can be trusted and one that
cannot, and it costs two lines. Note the order inside `fail`: message to stderr, record to the log,
then a non-zero exit — and note that `fail` exits, so callers read as assertions:

```bash
[ -d "$SRC" ] || fail "source $SRC does not exist"
[ -d "$DEST" ] || fail "destination $DEST is not a directory"
```

Check preconditions *before* doing work, and check the work afterwards. `[ -d ]` for a directory,
`[ -f ]` for a regular file, `[ -r ]`/`[ -w ]`/`[ -x ]` for access, `[ -n ]`/`[ -z ]` for a non-empty
or empty string.

### `set -euo pipefail`, and what it does not do

```bash
set -euo pipefail
```

- **`-e`** exit as soon as any command returns non-zero. Turns a silent failure into a stopped script.
- **`-u`** treat an unset variable as an error. Catches `$BACKUP_DEST` when you typed `$BACKUP_DST` —
  which without `-u` expands to nothing, and `tar -czf /data-…tar.gz` writes to the root directory.
- **`-o pipefail`** make a pipeline fail if *any* stage fails. Without it, `find … | xargs tar …`
  reports only `xargs`'s status, so a failing `find` is invisible.

`set -e` is a safety net, not a strategy, and its exceptions are worth knowing because they surprise
people:

```bash
cmd || true                  # explicitly ignored — and now -e does not fire (this is the point)
if cmd; then …                # a command in a condition is exempt: no exit
cmd1 && cmd2                 # only the last command's status counts
f() { false; echo reached; }  # -e inside a function called in a condition does not fire
count=$(grep -c x file)      # assignment from a substitution: the status is the assignment's
```

Which is why explicit `|| fail "…"` on the commands that matter is better than relying on `-e` to
catch everything. Use both: `-e` for the things you forgot, explicit checks for the things you care
about. And `${BACKUP_SRC:-/srv/data}` — "this variable, or this default" — coexists happily with
`-u`, since the default makes it defined.

### cron's environment is not yours

The nightly job is:

```
15 2 * * * root backup-data
```

Test it in your shell and it works. Under cron it does not, because cron runs jobs with a minimal
environment — typically `PATH=/usr/bin:/bin` and nothing else. `/usr/local/bin`, where the script
lives, is not in it. Your interactive shell has it because `/etc/profile` put it there, and cron does
not read `/etc/profile`, `~/.bashrc`, or any of your shell's configuration.

Three fixes, best first:

```
15 2 * * * root /usr/local/bin/backup-data      # 1. an absolute path — always correct

PATH=/usr/local/bin:/usr/bin:/bin               # 2. set PATH in the crontab itself
15 2 * * * root backup-data

15 2 * * * root . /etc/profile; backup-data     # 3. source a profile — fragile, avoid
```

The rest of the crontab's own rules, which cost people a night each:

- **Five time fields**: minute, hour, day-of-month, month, day-of-week. `15 2 * * *` is 02:15 daily.
- **`/etc/cron.d/*` and `/etc/crontab` have a user field**; a user's own crontab (`crontab -e`) does
  not. Putting `root` in the wrong one makes cron try to run a program called `root`.
- **`%` is special** in a crontab command — it means a newline and starts the stdin section. In a
  `date +%Y%m%d` inside a crontab line it must be `\%`. This is the single most common "works by hand,
  not in cron" cause after `PATH`.
- **Anything printed is mailed** to the job's user. On a machine with no mail transport that output
  is simply lost, which is why a job should write its own log rather than rely on stdout.
- **A file in `/etc/cron.d` must be owned by root, not writable by others, and must have no dot in
  its name** — otherwise cron ignores it, silently.
- **The last line needs a newline.** A crontab file that does not end with one has historically been
  ignored by some cron implementations.

And the daemon has to be running and enabled, which differs by system — `cron` on Ubuntu,
`crond` on Alpine and RHEL:

```console
$ systemctl is-enabled cron && systemctl is-active cron      # Ubuntu
$ rc-update show default | grep crond ; rc-service crond status   # Alpine
```

The honest way to test a cron job is to reproduce cron's environment rather than to wait for 02:15:

```console
$ sudo env -i PATH=/usr/bin:/bin /usr/local/bin/backup-data ; echo "exit=$?"
```

`env -i` starts with an empty environment and adds only what you name. If it works under that, it
will work under cron. It is also how you discover that your script depended on `$HOME`, or on a
`umask` your shell set, or on a locale that changes how `date` formats.

For completeness: a systemd timer (see the rhcsa-05 journal) is the modern alternative, and it
sidesteps most of this — the service unit states its own `Environment=`, output goes to the journal
rather than to mail, and `systemd-analyze calendar` checks the schedule. cron remains everywhere,
which is why its traps are worth knowing.

## A failure, walked through

The log says "backup OK". `/var/backups` has nothing recent in it.

**1. Read the script before running anything.** Four lines in, the verdict is already available:

```console
$ cat /usr/local/bin/backup-data
cd $SRC
FILES=$(find . -type f)
tar -czf $ARCHIVE $FILES 2>/dev/null
echo "$(date -Is) backup OK: $ARCHIVE" >> $LOG
exit 0
```

`exit 0` with no conditional above it means the log line tells you nothing at all. Everything else is
now a question about *what* is broken, not *whether*.

**2. Run it with the stderr it was hiding.** The variables exist so this can be done safely, in a
sandbox, with test data:

```console
$ mkdir -p /tmp/t/src/"a dir" /tmp/t/dest
$ printf 'x\n' > /tmp/t/src/plain.txt
$ printf 'y\n' > /tmp/t/src/"a dir"/"inner file.log"
$ BACKUP_SRC=/tmp/t/src BACKUP_DEST=/tmp/t/dest BACKUP_LOG=/tmp/t/log \
    bash -x /usr/local/bin/backup-data
+ SRC=/tmp/t/src
+ DEST=/tmp/t/dest
+ LOG=/tmp/t/log
++ date +%Y%m%d-%H%M%S
+ STAMP=20260913-042411
+ ARCHIVE=/tmp/t/dest/data-20260913-042411.tar.gz
+ cd /tmp/t/src
++ find . -type f
+ FILES='./plain.txt
./a dir/inner file.log'
+ tar -czf /tmp/t/dest/data-20260913-042411.tar.gz ./plain.txt ./a dir/inner file.log
++ date -Is
+ echo '2026-09-13T04:24:11+00:00 backup OK: /tmp/t/dest/data-20260913-042411.tar.gz'
+ exit 0
```

`bash -x` prints each command after expansion, and the expansion *is* the bug: one filename became
three arguments. What the trace does not show is tar's reaction, because `2>/dev/null` swallowed it.
Run the same command by hand without the redirection:

```console
$ cd /tmp/t/src && tar -czf /tmp/t/x.tgz $(find . -type f) ; echo "tar exit=$?"
tar: ./a: Cannot stat: No such file or directory
tar: dir/inner: Cannot stat: No such file or directory
tar: file.log: Cannot stat: No such file or directory
tar: Exiting with failure status due to previous errors
tar exit=2
```

tar knew, said so, and exited 2. The script threw the message away, ignored the status, and wrote
"backup OK".

**3. Confirm what the archive actually holds**, because that is the claim that failed for the restore:

```console
$ tar -tzf /tmp/t/dest/data-*.tar.gz
./plain.txt
```

One file of two. Exactly the file with no space in its name.

**4. Rewrite it.** The changes are small and each one maps to a fault:

```bash
#!/bin/bash
# backup-data — nightly archive of the data directory.
# BACKUP_SRC, BACKUP_DEST and BACKUP_LOG override the defaults.
set -euo pipefail

SRC=${BACKUP_SRC:-/srv/data}
DEST=${BACKUP_DEST:-/var/backups}
LOG=${BACKUP_LOG:-/var/log/backup-data.log}
ARCHIVE="$DEST/data-$(date +%Y%m%d-%H%M%S).tar.gz"

log()  { echo "$(date -Is) $*" >> "$LOG"; }
fail() { echo "backup-data: $*" >&2; log "backup FAILED: $*"; exit 1; }

[ -d "$SRC" ] || fail "source $SRC does not exist"
tar -czf "$ARCHIVE" -C "$SRC" . || fail "could not write $ARCHIVE"
log "backup OK: $ARCHIVE"
```

What changed, and why:

- `set -euo pipefail` — the net.
- `-C "$SRC" .` instead of `cd $SRC` and a file list — tar walks the tree itself, so there is no list
  to split, and the archive holds relative paths.
- every expansion quoted, including `"$ARCHIVE"` and inside `log`/`fail`.
- `2>/dev/null` gone: tar's complaints are the most valuable output the script produces.
- a `fail` function, so every failure exits non-zero, says why on stderr, and leaves a "backup
  FAILED" line rather than a lie.
- `"backup OK"` reached only if tar succeeded.

**5. Test all three outcomes, because two of them are what the lab actually grades.** A script is
only trustworthy if you have seen it fail:

```console
$ sudo install -m 755 /tmp/backup-data /usr/local/bin/backup-data
$ rm -f /tmp/t/log /tmp/t/dest/*          # start the log fresh, so the count below means something

# the happy path, with awkward names
$ BACKUP_SRC=/tmp/t/src BACKUP_DEST=/tmp/t/dest BACKUP_LOG=/tmp/t/log backup-data
$ echo "exit=$?" ; tar -tzf /tmp/t/dest/data-*.tar.gz
exit=0
./
./plain.txt
./a dir/
./a dir/inner file.log

# a missing source
$ BACKUP_SRC=/tmp/t/nope BACKUP_DEST=/tmp/t/dest BACKUP_LOG=/tmp/t/log backup-data
backup-data: source /tmp/t/nope does not exist
$ echo "exit=$?"
exit=1

# a destination that cannot be written (a file where the directory should be)
$ : > /tmp/t/notadir
$ BACKUP_SRC=/tmp/t/src BACKUP_DEST=/tmp/t/notadir BACKUP_LOG=/tmp/t/log backup-data
tar (child): /tmp/t/notadir/data-20260913-042427.tar.gz: Cannot open: Not a directory
tar (child): Error is not recoverable: exiting now
tar: Child returned status 2
tar: Error is not recoverable: exiting now
backup-data: could not write /tmp/t/notadir/data-20260913-042427.tar.gz
$ echo "exit=$?" ; grep -c 'backup OK' /tmp/t/log
exit=1
1
$ cat /tmp/t/log
2026-09-13T04:24:27+00:00 backup OK: /tmp/t/dest/data-20260913-042427.tar.gz
2026-09-13T04:24:27+00:00 backup FAILED: source /tmp/t/nope does not exist
2026-09-13T04:24:27+00:00 backup FAILED: could not write /tmp/t/notadir/data-20260913-042427.tar.gz
```

(`tar (child)` is gzip's half of `tar -z`: tar runs the compressor as a child process, and it is the
child that failed to open the output.)

One "backup OK" in the log — from the successful run — and two "backup FAILED" lines. The log now
distinguishes nights.

**6. Fix cron.** The entry names a bare command, and cron's `PATH` does not include
`/usr/local/bin`:

```console
$ cat /etc/cron.d/backup-data
# nightly backup
15 2 * * * root backup-data
$ sudo env -i PATH=/usr/bin:/bin backup-data ; echo "exit=$?"
env: ‘backup-data’: No such file or directory
exit=127
```

Exit 127 is "command not found" — the shell's way of saying `PATH`. Use an absolute path:

```console
$ sudo sed -i 's#root backup-data#root /usr/local/bin/backup-data#' /etc/cron.d/backup-data
$ sudo env -i PATH=/usr/bin:/bin /usr/local/bin/backup-data ; echo "exit=$?"
exit=0
$ systemctl is-active cron && systemctl is-enabled cron
active
enabled
```

(On Alpine the same job lives in `/etc/crontabs/root` — readable only with `sudo` — with no user
field, next to the `run-parts /etc/periodic/…` lines, and the daemon is `crond` under OpenRC:
`rc-update add crond default`. BusyBox's `tar` words its failure differently, *tar: can't open
'…': Not a directory*, and the script's own `fail` line is the same on both.)

**7. Reboot and check the whole chain again**, because a cron daemon that is running and not enabled
is the next version of this bug:

```console
$ sudo reboot
$ systemctl is-enabled cron ; systemctl is-active cron
$ sudo run-parts --test /etc/cron.daily >/dev/null ; cat /etc/cron.d/backup-data
$ sudo /usr/local/bin/backup-data && tail -2 /var/log/backup-data.log
```

## Common wrong turns

**Quoting `$FILES` and stopping there.** `tar -czf "$ARCHIVE" "$FILES"` hands tar a *single*
argument containing every filename and a few newlines, so now nothing is archived instead of some
things. The list-in-a-variable shape is the problem; quoting it does not fix it. Let tar walk the tree
(`-C "$SRC" .`), or use `-print0 | xargs -0`.

**Setting `IFS=$'\n'` to make the loop work.** It makes spaces safe and leaves newlines in filenames
broken, and it changes the behaviour of every later command in the script. NUL separation is the
mechanism that actually holds: it is the one byte a filename cannot contain.

**Leaving `2>/dev/null` in place because the errors are noisy.** The noise was tar telling you the
script was broken, for a year. If output is genuinely uninteresting, send it to the log, not to
`/dev/null`.

**Adding `set -e` and believing the script now fails loudly.** `set -e` makes it *stop*; it does not
make it *say* anything, and it does not stop a previously-written "backup OK" from being the last
thing in the log. It is also exempt inside conditions, in `&&`/`||` chains, and for commands whose
status is consumed by an assignment. Explicit `|| fail "…"` on the commands you care about is what
makes a failure legible.

**Checking `$?` in a separate `if` several lines later.** `$?` is the status of the *last* command,
and the `echo` you inserted while debugging has already overwritten it. Test the command directly
(`if tar …; then`) or use `|| fail`.

**Writing the error to stdout.** `echo "backup failed"` on stdout means a caller redirecting stdout
to `/dev/null` sees silence, and cron mails nothing. Errors belong on `>&2`.

**Exiting 0 after reporting a failure.** The message is for humans; the exit status is for machines,
and the machine is what runs it nightly. A monitoring check reads `$?`.

**Using `date +%Y%m%d` directly in a crontab line.** In a crontab, `%` starts the stdin section and
must be written `\%`. It works perfectly when you paste the command into a shell to test it, which
is what makes it so hard to find.

**Adding `/usr/local/bin` to your own `.bashrc` and re-testing.** That changes your shell, not
cron's. `sudo env -i PATH=/usr/bin:/bin <cmd>` is the test; an absolute path in the crontab is the
fix.

**Using a bare command name in `/etc/cron.d` and putting the user field in a user crontab (or the
reverse).** `/etc/crontab` and `/etc/cron.d/*` take a user field; `crontab -e` files do not. Get it
wrong and cron either runs the wrong thing or reports that it cannot find a command called `root`.

**Naming a file in `/etc/cron.d` with a dot in it**, or making it group-writable. cron ignores it
without explanation.

**Testing only the happy path.** The two graded failure cases are the whole point: a backup script is
a claim about failure handling, and you have not verified it until you have watched it fail on a
missing source and on an unwritable destination.

## Cheat sheet

```bash
# quoting
"$var"          # one argument, exactly
"$(cmd)"        # the output as one argument (trailing newlines stripped)
"$@"            # each positional argument preserved   ← always this, never $@
"${arr[@]}"     # each array element preserved
${var:-default} # this, or a default (works with set -u)
${var:?message} # …or die with a message if unset
# no quoting needed: inside [[ ]], and on the right of a plain x=$y assignment

# file lists, safely
tar -czf "$ARCHIVE" -C "$SRC" .                 # let the tool walk the tree  ← preferred
find "$SRC" -type f -exec cmd {} +              # batched, no shell in between
find "$SRC" -print0 | xargs -0 cmd              # NUL-separated
find "$SRC" -print0 | while IFS= read -r -d '' f; do cmd "$f"; done
mapfile -d '' files < <(find "$SRC" -print0)    # into an array (bash 4.4+)

# failing loudly
set -euo pipefail                  # -e stop on error, -u unset is an error, pipefail
log()  { echo "$(date -Is) $*" >> "$LOG"; }
fail() { echo "$0: $*" >&2; log "FAILED: $*"; exit 1; }
[ -d "$SRC" ]  || fail "no source $SRC"         # -f file, -d dir, -r/-w/-x access
[ -n "$var" ]  || fail "empty var"              # -z empty, -n non-empty
cmd || fail "cmd failed"
if ! cmd; then fail "…"; fi
trap 'rm -rf "$tmp"' EXIT                       # clean up on any exit path

# debugging
bash -n script            # syntax only, run nothing
bash -x script            # print each command after expansion  ← finds quoting bugs
set -x ; … ; set +x       # trace one section
shellcheck script         # static analysis; finds every unquoted expansion (not on the lab image: apt install shellcheck)

# cron
# min hour dom mon dow [user]  command       (user field: /etc/crontab, /etc/cron.d/* only)
15 2 * * * root /usr/local/bin/backup-data   # absolute path — cron's PATH is /usr/bin:/bin
PATH=/usr/local/bin:/usr/bin:/bin            # …or set it at the top of the crontab
# \% : a literal percent (unescaped % starts the stdin section)
crontab -l ; crontab -e ; crontab -u user -l
systemctl is-enabled cron ; systemctl is-active cron        # Ubuntu
rc-update show default | grep crond ; rc-service crond status   # Alpine
sudo env -i PATH=/usr/bin:/bin /usr/local/bin/job ; echo $?   # reproduce cron's environment
journalctl -t CRON -b                        # what cron says it ran (systemd systems)
# exit 127 = command not found → PATH.  exit 126 = found, not executable.
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Active, green, and not working* (topic journal `monitoring`) — A check is an exit status

Manual pages: `man 1 bash`, `man 5 crontab`.

## Review

1. `FILES=$(find . -type f)` then `tar -czf $ARCHIVE $FILES`. Exactly what happens to a file called
   `2026 Q3 summary.csv`, and what do the archive and the log say afterwards?

   > Word splitting cuts the unquoted `$FILES` at every space, so tar receives `./invoices/2026`,
   > `Q3` and `summary.csv` as three separate arguments, none of which exists. tar reports three
   > errors and exits non-zero; the archive contains only the files whose names had no spaces; and
   > because the script discards stderr and ends in `exit 0`, the log still says "backup OK".

2. Why is quoting `$FILES` not the fix, and what are the two robust ways to hand a list of files to
   another program?

   > `"$FILES"` becomes one argument containing every name and some newlines, so nothing is archived
   > instead of some things — a list cannot live in a string, because a filename may contain a
   > newline. Either let the tool walk the tree itself (`tar -C "$SRC" .`), or use NUL separation
   > (`find -print0 | xargs -0`, or `while IFS= read -r -d ''`).

3. What do `set -e`, `set -u` and `set -o pipefail` each catch, and name two situations where
   `set -e` does not fire?

   > `-e` exits on the first non-zero status; `-u` makes an unset variable an error (catching a typo
   > that would otherwise expand to nothing); `pipefail` makes a pipeline fail if any stage fails,
   > not just the last. It does not fire for a command used as a condition (`if cmd`, `cmd || true`,
   > `a && b` except the last), nor when the status is consumed by an assignment
   > (`x=$(failing-cmd)`).

4. A script prints "backup failed" and exits 0. Name both defects and who is harmed by each.

   > The message is on stdout rather than stderr, so a caller that redirects stdout — cron included —
   > sees nothing at all. And exit 0 tells every machine consumer, from cron's mail to a monitoring
   > check, that the run succeeded. Humans lose the message; automation loses the truth.

5. What is the minimum a log line needs for someone to distinguish a good night from a bad one a year
   later?

   > A timestamp, an explicit outcome written on *both* paths (OK and FAILED), and the reason plus the
   > artifact on failure. A log that only ever contains one sentence carries no information — there
   > must be a line that could have been different.

6. A job works when you run it in your shell and does nothing under cron. What is the first thing to
   suspect, and what single command reproduces cron's conditions?

   > `PATH`: cron gives a job roughly `/usr/bin:/bin` and reads none of your shell's startup files,
   > so anything in `/usr/local/bin` is not found — exit 127. Reproduce it with
   > `env -i PATH=/usr/bin:/bin /path/to/job`. Fix it with an absolute path in the crontab, or a
   > `PATH=` line at the top of the crontab.

7. Why does `date +%Y%m%d` behave differently in a crontab line than in a shell?

   > In a crontab, `%` is special: it terminates the command and starts the data fed to it on stdin.
   > It must be escaped as `\%`. The command tests perfectly when pasted into a shell, which is what
   > makes this failure so persistent.

8. `bash -n`, `bash -x` and `shellcheck` — what does each one tell you, and which finds a quoting bug
   fastest?

   > `bash -n` parses without running, catching syntax errors only. `bash -x` prints every command
   > *after* expansion, so an unquoted variable that became three arguments is visible on the trace —
   > the fastest way to see this class of bug in action. `shellcheck` finds unquoted expansions
   > statically, before you run anything, and should be in the habit.
