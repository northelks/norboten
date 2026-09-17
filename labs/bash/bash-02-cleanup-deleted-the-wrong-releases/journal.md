---
title: Deleting files is the one thing a script must get exactly right
topics: [bash, boot-systemd]
minutes: 35
---

Most scripts that go wrong produce the wrong output. A cleanup script that goes wrong produces the
wrong *absence*, and absence is hard to notice and impossible to undo. `prune-releases` is one line of
real work — `ls -t | tail -n +6 | xargs rm -rf` — and that one line contains three separate ways to
delete the wrong thing: it chooses by modification time instead of by the date in the name, it hands
names to `rm` through a channel that splits them at spaces, and it runs after a `cd` that nobody
checked, so when the directory is missing it deletes wherever it happens to be.

None of the three is exotic. They are the standard failures of shell pipelines that deal with file
names, and every one of them has a standard fix. The lab adds a fourth, unrelated problem — a timer
that points at a program that does not exist — because a cleanup that never runs is the other way a
disk fills up.

## What you should be able to do after this

- Choose files by the data you trust (a timestamp in the name) rather than by metadata that other
  tools change (mtime).
- Explain why `ls | xargs` is unsafe for file names, and iterate over names without word splitting.
- Stop a script before it acts when a precondition such as `cd` fails.
- Select only the entries a cleanup is allowed to touch: directories, not symlinks, not stray files.
- Test a destructive script against copies, including the case where its target is missing.
- Read a systemd timer and its service, find why nothing runs, and fix it with a drop-in.

## The mechanism

### What `ls -t` actually sorts by

`ls -t` sorts by modification time, newest first. A directory's mtime changes whenever an entry is
created, renamed or removed inside it — and also whenever a tool sets it deliberately. Restoring from
a backup, `cp -a`, `rsync -a`, `tar -x` and `touch` all set timestamps, and a restore that ran
yesterday makes old releases look new.

The release names already contain the only timestamp that matters: `20260913-101500`, year first,
zero-padded. Names in that form sort chronologically as plain text, so "the five newest releases" is
"the last five names, sorted". That is data the release itself carries and nothing else rewrites.

A rule worth keeping: **select by content you control, not by metadata someone else can touch.**
mtimes are fine for "has this changed since I last looked"; they are a poor identity.

### Why `ls | xargs rm` splits names

`ls` writes names separated by newlines. `xargs` reads its input as *words*: by default it splits at
spaces, tabs and newlines, and it also interprets quotes and backslashes. So the line

```
20260911-180000 hotfix
```

becomes two arguments to `rm`: `20260911-180000` and `hotfix`. Neither exists; `rm -f` says nothing
about files it cannot find; the release survives. Change the name to `a b` and create a directory
called `b` next to it, and the pipeline deletes `b` instead.

There are only two reliable ways to pass file names from one program to another:

```bash
find . -mindepth 1 -maxdepth 1 -type d -print0 | xargs -0 rm -rf --   # NUL-separated
for entry in ./*; do …; done                                          # a glob: no text in between
```

NUL is the one byte a file name cannot contain, so `-print0`/`-0` is unambiguous. A glob never turns
names into text at all: the shell expands it into separate words, one per file, and quoting
`"$entry"` keeps each one whole. A bonus: glob results come back **sorted by name** (in the current
locale), which is exactly the order a timestamped name needs.

### The unchecked `cd`

```sh
cd $RELEASES_DIR
ls -t | tail -n +$((KEEP + 1)) | xargs rm -rf
```

When `cd` fails, it prints a message and returns non-zero — and the next line runs anyway, in the
directory the script started in. Under systemd that is `/`. From a person's shell it is their current
directory. Nothing is special about deletion here; it is ordinary shell behaviour meeting the most
dangerous possible next command.

Three habits, any one of which would have saved it:

```bash
set -euo pipefail          # -e: stop when cd fails
cd -- "$RELEASES_DIR"      # quoted, and -- in case the path starts with -
cd "$dir" || exit 1        # the explicit form, for scripts that cannot use -e
```

And one habit for every destructive command: act on paths **relative to a directory you have just
verified**, like `./$old`, or on absolute paths you built from it. Never on "whatever is here".

### Choosing only what may be deleted

A releases directory holds more than releases: the `current` symlink, a README, a lock file. The
original pipeline counted all of them. A cleanup should define what it owns and ignore the rest:

```bash
for entry in [0-9]*; do                     # names that start with a digit: the timestamps
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
        releases+=("$entry")
    fi
done
```

The glob `[0-9]*` already skips `current`, but `-d` is true for any symlink that points to a
directory, so a link named like a release — `20260913-101500-live` in another layout — would match
and be counted. The `! -L` test excludes links whatever their names. When the glob matches nothing, bash leaves the pattern
as literal text, `[0-9]*`, and the `-d` test quietly rejects it; `shopt -s nullglob` is the other way
to handle that.

### Slicing the list

With the releases in an array sorted oldest first, the ones to delete are all but the last `KEEP`:

```bash
count=${#releases[@]}
if (( count > KEEP )); then
    for old in "${releases[@]:0:count-KEEP}"; do
        rm -rf -- "./$old"
    done
fi
```

`${array[@]:offset:length}` is an array slice, and quoting it preserves each element. The guard
matters: a negative length in a slice is an error in bash, and without the `if` a directory with
three releases would abort the script.

### Scheduling: a timer is two units

A systemd timer does nothing by itself. `prune-releases.timer` says *when*; it activates
`prune-releases.service` (the unit with the same name unless `Unit=` says otherwise), which says
*what*. Three things must be true for the job to run every night:

1. the timer is **started** — a timer that was never started has no next elapse;
2. the timer is **enabled**, which links it into `timers.target` so it starts at every boot;
3. the service can actually start — here, its `ExecStart=` must name an executable that exists.

`OnCalendar=*-*-* 03:30:00` is systemd's calendar syntax, and `systemd-analyze calendar` shows when an
expression next fires. `Persistent=true` runs a missed job at boot if the machine was off at 03:30.

To change one line of a unit that a package or a colleague installed, a **drop-in** is cleaner than
editing the unit: a file in `/etc/systemd/system/<unit>.d/*.conf` overrides only what it names.
`ExecStart=` is a list, so a drop-in must first clear it with an empty `ExecStart=` and then set the new
value — otherwise a oneshot service ends up with two commands.

### Testing a destructive script

Two principles. First, test against a **copy**: `cp -a` keeps the names, the modes, the symlink and —
crucially for this bug — the mtimes, so the copy reproduces the problem. Second, test the **missing
target** from a directory full of things you would hate to lose, because that is the failure you
cannot observe safely any other way. The variables the script already reads (`RELEASES_DIR`, `KEEP`)
exist precisely so it can be pointed at a sandbox.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. Compare the names with the times.**

```console
$ ls -l --time-style=+%F_%T /srv/app/releases
total 32
drwxr-xr-x 2 root root 4096 2026-09-14_03:31:06 20260801-120000
drwxr-xr-x 2 root root 4096 2026-09-14_02:31:06 20260830-090000 rollback
drwxr-xr-x 2 root root 4096 2026-09-14_01:31:06 20260905-140000
drwxr-xr-x 2 root root 4096 2026-09-14_00:31:06 20260908-101500
drwxr-xr-x 2 root root 4096 2026-09-13_23:31:06 20260910-163000
drwxr-xr-x 2 root root 4096 2026-09-13_22:31:06 20260911-180000 hotfix
drwxr-xr-x 2 root root 4096 2026-09-13_21:31:06 20260912-083000
drwxr-xr-x 2 root root 4096 2026-09-13_20:31:06 20260913-101500
lrwxrwxrwx 1 root root   33 2026-09-14_03:31:06 current -> /srv/app/releases/20260913-101500
$ ls -t /srv/app/releases
20260801-120000
current
20260830-090000 rollback
20260905-140000
20260908-101500
20260910-163000
20260911-180000 hotfix
20260912-083000
20260913-101500
```

The August release carries the newest modification time and the September 13 release the oldest —
the restore reversed them. `ls -t` also lists `current` among the "releases".

**2. Read the script, then look at what the pipeline would hand to `rm`** — without running `rm`:

```console
$ cat /usr/local/bin/prune-releases
#!/bin/sh
# prune-releases — keep the five newest releases, delete the rest

RELEASES_DIR=${RELEASES_DIR:-/srv/app/releases}
KEEP=${KEEP:-5}

cd $RELEASES_DIR
ls -t | tail -n +$((KEEP + 1)) | xargs rm -rf
$ cd /srv/app/releases && ls -t | tail -n +6
20260910-163000
20260911-180000 hotfix
20260912-083000
20260913-101500
$ cd /srv/app/releases && ls -t | tail -n +6 | xargs printf '[%s]\n'
[20260910-163000]
[20260911-180000]
[hotfix]
[20260912-083000]
[20260913-101500]
```

Replacing the destructive command with `printf '[%s]\n'` shows exactly the arguments `rm` would get,
one per bracket. The four newest releases are on the list, and the hotfix is two words.

**3. Run it on a copy.** `cp -a` preserves the mtimes, so the copy misbehaves the same way:

```console
$ mkdir -p /tmp/p && sudo cp -a /srv/app/releases /tmp/p/ && sudo chown -R "$(id -un)" /tmp/p
$ cd /tmp/p && RELEASES_DIR=/tmp/p/releases prune-releases; echo "exit=$?"; ls /tmp/p/releases
exit=0
20260801-120000
20260830-090000 rollback
20260905-140000
20260908-101500
20260911-180000 hotfix
current
```

The three newest releases are gone, the one from August 1 is kept, the hotfix survived only because
its name was split into two words that do not exist, and the script reports success.

**4. The missing directory**, started from a directory of things to keep:

```console
$ for n in 1 2 3 4 5 6 7 8; do mkdir -p /tmp/q/important-$n && echo keep > /tmp/q/important-$n/data; done; ls /tmp/q
important-1
important-2
important-3
important-4
important-5
important-6
important-7
important-8
$ cd /tmp/q && RELEASES_DIR=/tmp/q/moved-away prune-releases; echo "exit=$?"; ls /tmp/q
/usr/local/bin/prune-releases: 7: cd: can't cd to /tmp/q/moved-away
exit=0
important-1
important-2
important-3
important-4
important-8
```

`cd` failed, said so, and the pipeline ran in `/tmp/q`: three of the eight directories are gone, and
the exit status is still 0. Under the timer, the starting directory would have been `/`. (The message
format — `7: cd: can't cd to` — is dash's: the script's `#!/bin/sh` is dash on Ubuntu.)

**5. Find out why it never runs.**

```console
$ systemctl status prune-releases.timer --no-pager
○ prune-releases.timer - Delete old application releases every night
     Loaded: loaded (/etc/systemd/system/prune-releases.timer; disabled; preset: enabled)
     Active: inactive (dead)
    Trigger: n/a
   Triggers: ● prune-releases.service
$ systemctl cat prune-releases.service
# /etc/systemd/system/prune-releases.service
[Unit]
Description=Delete old application releases

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/prune-releases
$ ls -l /usr/local/sbin/prune-releases /usr/local/bin/prune-releases
ls: cannot access '/usr/local/sbin/prune-releases': No such file or directory
-rwxr-xr-x 1 root root 207 Sep 14 03:31 /usr/local/bin/prune-releases
$ systemd-analyze calendar '*-*-* 03:30:00'
Normalized form: *-*-* 03:30:00
    Next elapse: Tue 2026-09-15 03:30:00 UTC
       From now: 23h left
```

The timer is disabled and inactive (`Trigger: n/a` — no next run), and even if it fired, the service
would try to execute a path that does not exist. The calendar expression itself is fine.

**6. Rewrite the script.**

```bash
#!/bin/bash
# prune-releases — keep the newest $KEEP releases (by the timestamp in their names), delete the rest
set -euo pipefail

RELEASES_DIR=${RELEASES_DIR:-/srv/app/releases}
KEEP=${KEEP:-5}

cd -- "$RELEASES_DIR"

releases=()
for entry in [0-9]*; do
    # release directories only: not current, not files, not a glob that matched nothing
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
        releases+=("$entry")
    fi
done

# glob results are sorted by name, and the names start with a timestamp: newest last
count=${#releases[@]}
if (( count > KEEP )); then
    for old in "${releases[@]:0:count-KEEP}"; do
        rm -rf -- "./$old"
    done
fi
```

Bash, not `sh`: arrays and `(( ))` are bash features. It was written with
`sudo tee /usr/local/bin/prune-releases > /dev/null <<'SCRIPT'`, then:

```console
$ shellcheck /usr/local/bin/prune-releases && echo "shellcheck: clean"
shellcheck: clean
```

**7. Test it on a fresh copy, and on the missing directory again.**

```console
$ rm -rf /tmp/p && mkdir -p /tmp/p && sudo cp -a /srv/app/releases /tmp/p/ && sudo chown -R "$(id -un)" /tmp/p
$ RELEASES_DIR=/tmp/p/releases prune-releases; echo "exit=$?"; ls -l /tmp/p/releases
exit=0
total 0
drwxr-xr-x 2 northelks root 60 Sep 14 00:31 20260908-101500
drwxr-xr-x 2 northelks root 60 Sep 13 23:31 20260910-163000
drwxr-xr-x 2 northelks root 60 Sep 13 22:31 20260911-180000 hotfix
drwxr-xr-x 2 northelks root 60 Sep 13 21:31 20260912-083000
drwxr-xr-x 2 northelks root 60 Sep 13 20:31 20260913-101500
lrwxrwxrwx 1 northelks root 33 Sep 14 03:31 current -> /srv/app/releases/20260913-101500
$ cd /tmp/q && RELEASES_DIR=/tmp/q/moved-away prune-releases; echo "exit=$?"; ls /tmp/q
/usr/local/bin/prune-releases: line 8: cd: /tmp/q/moved-away: No such file or directory
exit=1
important-1
important-2
important-3
important-4
important-8
```

The five newest names remain whatever their mtimes, the hotfix is kept as one release, `current` is
untouched, and a missing directory now stops the script with exit 1 before anything is deleted (the
remaining canaries are the ones the old script left).

**8. Fix the service with a drop-in, then enable and start the timer.**

```console
$ sudo mkdir -p /etc/systemd/system/prune-releases.service.d && printf '[Service]\nExecStart=\nExecStart=/usr/local/bin/prune-releases\n' | sudo tee /etc/systemd/system/prune-releases.service.d/path.conf
[Service]
ExecStart=
ExecStart=/usr/local/bin/prune-releases
$ sudo systemctl daemon-reload && sudo systemctl enable --now prune-releases.timer
Created symlink '/etc/systemd/system/timers.target.wants/prune-releases.timer' → '/etc/systemd/system/prune-releases.timer'.
$ systemctl list-timers prune-releases.timer --no-pager
NEXT                        LEFT LAST PASSED UNIT                 ACTIVATES
Tue 2026-09-15 03:30:00 UTC  23h -         - prune-releases.timer prune-releases.service

1 timers listed.
Pass --all to see loaded but inactive timers, too.
$ sudo systemctl start prune-releases.service; systemctl show prune-releases.service -p Result -p ExecMainStatus; ls /srv/app/releases
Result=success
ExecMainStatus=0
20260908-101500
20260910-163000
20260911-180000 hotfix
20260912-083000
20260913-101500
current
```

The timer has a next elapse, and one manual run of the service through systemd — the same way the
timer will run it — succeeded on the real directory.

**9. Grade.** The checks ran, the machine rebooted, and they ran again: all four passed both times.

## Common wrong turns

**`ls -v` or `sort -V` on the `ls -t` output.** Sorting the text differently does not help while the
text is still produced by `ls` and split by `xargs`. Fix the channel first, then the order.

**`xargs -d '\n'`.** It stops splitting at spaces, and it is a real improvement, but names can contain
newlines, and it keeps the design of "turn names into text, then parse the text". A glob or `-print0`
avoids the problem entirely.

**Quoting `$RELEASES_DIR` and calling it fixed.** `cd "$RELEASES_DIR"` still fails on a missing
directory, and without `set -e` or `|| exit` the deletion still runs in the wrong place.

**`rm -rf "$RELEASES_DIR"/*` to "stay in the right place".** With an empty or unset variable that is
`rm -rf /*`. `set -u` catches unset, not empty; `${RELEASES_DIR:?}` catches both, and `cd` plus
relative paths avoids building such a path at all.

**Counting `current` or other files as releases.** Any entry the script did not create for itself
must be excluded explicitly, or one day it is the one deleted.

**Starting the timer but not enabling it** (or the other way round). `enable` alone creates the
boot-time link but leaves the timer inactive until the next boot; `start` alone works until the next
reboot. `enable --now` does both.

**Editing `ExecStart=` in a drop-in without clearing it first.** For a `Type=oneshot` service systemd
accepts several `ExecStart=` lines and runs them in order, so the old, missing path still runs first
and fails the unit.

**Testing on `/srv/app/releases`.** A deletion cannot be rolled back. Every experiment above ran on a
copy, and the real directory was touched once, at the end, by the finished script.

## Cheat sheet

```bash
set -euo pipefail
cd -- "$dir"                              # stops the script if it fails (with -e)
cd "$dir" || exit 1                       # the same, without -e
: "${DIR:?DIR must be set}"               # abort if unset or empty
for f in ./*; do [ -d "$f" ] && [ ! -L "$f" ] && …; done   # directories, not links
shopt -s nullglob                         # an unmatched glob expands to nothing
arr=(); arr+=("$x"); echo "${#arr[@]}"    # array append, length
"${arr[@]:0:n}"                           # slice: the first n elements
find . -mindepth 1 -maxdepth 1 -type d -print0 | sort -z | xargs -0 …   # NUL-safe pipeline
cmd | xargs printf '[%s]\n'               # see the arguments xargs would pass
ls -l --time-style=+%F_%T                 # full modification times
cp -a src dst                             # copy keeping modes, links and mtimes
```

```bash
systemctl status NAME.timer               # enabled? active? next trigger?
systemctl list-timers --all               # every timer, with next and last run
systemctl cat NAME.service                # the unit plus its drop-ins
systemd-analyze calendar '*-*-* 03:30:00' # when a calendar expression fires
sudo systemctl edit NAME.service          # create a drop-in (clears nothing by itself)
sudo systemctl daemon-reload              # after editing unit files by hand
sudo systemctl enable --now NAME.timer    # boot link + start now
sudo systemctl start NAME.service         # run the job once, exactly as the timer would
journalctl -u NAME.service -b             # what the last runs printed
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *A script that cannot fail is not a backup* (lab journal `linux-03-backup-script-lies`) — Handing a list of files to a program
- *A script that cannot fail is not a backup* (lab journal `linux-03-backup-script-lies`) — set -euo pipefail, and what it does not do

Manual pages: `man 1 ls`, `man 1 sort`, `man 1 xargs`, `man 5 systemd.timer`.

## Review

1. Why is `ls -t` the wrong way to find the newest releases after a restore from backup?

   > It sorts by modification time, and restores, `cp -a`, `rsync -a` and `tar -x` set mtimes; the timestamp in the release name is the data that stays correct.

2. What does `echo "20260911-180000 hotfix" | xargs rm -rf` pass to `rm`?

   > Two arguments, `20260911-180000` and `hotfix`, because xargs splits its input at blanks (and interprets quotes).

3. When `cd $RELEASES_DIR` fails in a script without `set -e`, where does the next command run?

   > In the script's current working directory — wherever it was started from; `/` under systemd. The failure is printed but does not stop the script.

4. Name two ways to hand file names to a command that survive spaces and newlines.

   > A glob expanded by the shell with quoted expansions (`for f in ./*; do … "$f"`), or a NUL-separated pipeline (`find … -print0 | xargs -0 …`).

5. Why does the rewritten script test both `-d` and `! -L`?

   > `-d` is true for a symlink that points to a directory, so without `! -L` the `current` link (or any link to a release) would be counted and could be deleted.

6. A timer is enabled but `systemctl list-timers` does not show it. What is missing?

   > It has not been started since it was enabled; enabling only links it into timers.target for the next boot. `systemctl start` (or `enable --now`) activates it.

7. Why must a drop-in that replaces `ExecStart=` contain an empty `ExecStart=` line first?

   > ExecStart is a list; a new line is appended to the original. The empty assignment clears the list so only the new command remains (and a oneshot does not run the old one first).

8. How do you check a destructive pipeline's selection without deleting anything?

   > Replace the destructive command with one that prints its arguments, e.g. `… | xargs printf '[%s]\n'`, or run the script against a `cp -a` copy of the directory.
