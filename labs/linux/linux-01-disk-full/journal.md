---
title: The space that belongs to a file with no name
topics: [storage-lvm, logging-journald]
minutes: 30
---

A colleague saw a full disk, deleted the biggest file on it, and went home. `df` still says the
filesystem is nearly full; `du` says it is nearly empty. Nothing about that is a contradiction, and
nothing about it is unusual — it is the single most common shape of "the disk is full" on a Unix
machine, and the reason is a detail of how files are deleted that most people learn the hard way, at
some inconvenient hour.

The second half of the lab is the part the colleague did not get to: the log had no rotation rule, so
whatever you free will be consumed again. Rotating a log that a running daemon is holding open has
its own trap, and it is a close cousin of the first one.

## What you should be able to do after this

- Explain why `df` and `du` disagree, in terms of what each one actually measures.
- Find the process holding space that no directory entry points at, with `lsof` or with `/proc`
  alone.
- Get that space back without rebooting and without stopping the service.
- Read the other reasons a filesystem can be "full" — inodes, reserved blocks, a directory hidden
  under a mount point — and tell them apart in one command each.
- Write a logrotate rule that has a limit, keeps a sensible history, and does not leave the daemon
  writing into a rotated file.
- Choose between `copytruncate` and `postrotate`+`HUP` deliberately, knowing what each one risks.
- Test rotation now instead of waiting a day for it.

## The mechanism

### Deleting a file does not delete a file

`unlink()` — which is what `rm` calls — removes a **name**. The data lives in an inode, and the
inode is freed when two counts both reach zero:

```
  link count   how many directory entries point at this inode   (ls -l shows it)
  open count   how many file descriptors the kernel holds on it (invisible to ls)
```

`rm` decrements the first. If a process still has the file open, the second is not zero, and the
inode — with every block it owns — stays exactly where it was. The file now has no name, so nothing
that walks the directory tree can see it, and it keeps its blocks until the last descriptor closes.

That is the whole explanation for the disagreement:

```console
$ df -h /var/log/app
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb        974M  882M   25M  98% /var/log/app

$ sudo du -sh /var/log/app
181M    /var/log/app
```

**`du` walks the tree and adds up the files it can find. `df` asks the filesystem how many blocks
are free.** Seven hundred megabytes are in blocks that belong to an inode with no name, and the only
place that relationship is still recorded is the file-descriptor table of the process holding it.

It is worth being clear that this is a feature, not a bug. It is what makes a temporary file that
cannot be left behind (open it, unlink it, keep using it — it disappears when your process dies, even
if you crash), and it is what makes replacing a running program's file safe.

### Finding the holder

`lsof +L1` means "open files with fewer than one link" — which is precisely the definition:

```console
$ sudo lsof -a +L1 /var/log/app
COMMAND PID USER FD   TYPE DEVICE  SIZE/OFF NLINK NODE NAME
python3 833 root 3w   REG 254,16 734003968     0   13 /var/log/app/ledger.log (deleted)
```

`NLINK 0` and the `(deleted)` suffix are the two things to read. The `-a` matters: lsof **ORs** its
selection options by default, so `lsof +L1 /var/log/app` without it means "files with no links
anywhere, *or* anything open on this filesystem" — which looks right while the deleted file is the
only thing open there, and quietly lists every healthy open file once it is not. `-a` makes the
options AND together. Note also that `COMMAND` is `python3`, not `ledger`: lsof shows the name of
the executable that is running, and ledger is a script run by the interpreter.
`systemctl status 833` maps the PID back to `ledger.service`. And when `lsof` is not installed —
which on a minimal image is most of the time — `/proc` has the same answer, because
`/proc/<pid>/fd/<n>` is a symlink to whatever that descriptor points at:

```console
$ sudo sh -c 'ls -l /proc/[0-9]*/fd/* 2>/dev/null | grep deleted'
l-wx------ 1 root root 64 Sep 13 04:15 /proc/833/fd/3 -> /var/log/app/ledger.log (deleted)

$ sudo stat -L /proc/833/fd/3 | head -2       # the real size, through the descriptor
  File: /proc/833/fd/3
  Size: 734005152       Blocks: 1433616    IO Block: 4096   regular file
```

Why `sudo sh -c '…'` rather than the tempting `sudo ls -l /proc/*/fd/* | grep deleted`? Because the
`*` in that command is expanded by **your** shell, as you, before `sudo` runs — and you may only look
inside `/proc/<pid>/fd` for your own processes. The glob silently expands to your own shell's
descriptors, `ls` runs as root over that short list, and `grep` finds nothing. Inside `sh -c` the glob
is expanded by root's shell. (It is the same trap as `sudo echo > file`: sudo elevates the command,
not what your shell did to its arguments first.) GNU `find /proc/[0-9]*/fd -lname '*(deleted)'` also
works on Ubuntu, but not with Alpine's BusyBox `find`, which has no `-lname`.

Two useful relatives: `fuser -vm /var/log/app` lists every process with anything open on that
filesystem — the command for "why can I not unmount this" — and `lsof +D /var/log/app` walks the
directory for all open files, deleted or not.

### Getting the space back

The descriptor has to close. In order of how much you should like them:

**1. Tell the daemon to reopen its log.** Many write-a-log-forever programs handle `SIGHUP` by
closing and reopening — `ledger` here does, and so do nginx, rsyslog and most others. It is the
cheapest fix and it never loses a line:

```console
$ sudo kill -HUP 833
$ df -h /var/log/app       # the space is back, immediately
```

**2. Restart the service.** Honest, obvious, one command, and it costs whatever the restart costs:

```console
$ sudo systemctl restart ledger          # systemd
$ sudo rc-service ledger restart         # OpenRC (Alpine)
```

**3. Truncate through the descriptor** — and understand what you are doing first:

```console
$ sudo truncate -s 0 /proc/833/fd/3      # know why before you type this
```

This frees the blocks without the process noticing, and the process keeps writing **at its old
offset**. With a file it appends to, the result is a sparse file that reports the old size again
immediately (the blocks are not allocated until written, so you do get the space, but every tool
reporting sizes now lies to you). With a program that seeks, or one that reads its own log back, the
result is corruption. It is the right tool for "a runaway log on a production box at 3 a.m. and I
cannot restart the service", and the wrong tool any time option 1 or 2 is available.

**What is not on the list: rebooting.** It works — every process dies and every descriptor closes —
and it destroys the evidence. The one thing you know about a disk that filled up is that it will
fill up again, and after a reboot you no longer know which process was responsible. **Also not on
the list: `rm` again.** There is no name left to remove; the second `rm` fails, or removes the *new*
file the daemon has since created, which puts you right back in this state with one more deleted
inode.

### The other reasons a filesystem is "full"

Four causes, four one-line diagnostics. Run them in this order before you start theorising:

```console
$ df -h /var/log/app      # blocks: the ordinary case
$ df -i /var/log/app      # INODES: "No space left on device" with 60% free blocks
$ sudo du -sh /var/log/app    # what the visible files add up to
$ sudo lsof -a +L1 /var/log/app  # deleted-but-open
```

**Inode exhaustion** is the one that surprises people: a filesystem formatted with a fixed number of
inodes (ext4 does this at `mkfs` time) can run out of them while blocks remain, and every write
fails with `ENOSPC` exactly as if the disk were full. Millions of tiny files — a mail queue, a
session directory, a cache — is the usual cause. There is no way to add inodes to an existing ext4
filesystem; you delete files or rebuild it.

**Reserved blocks**: ext4 reserves 5% for root by default, so `df` can show `100%` and `0 Avail`
while root can still write. That is deliberate — it leaves room to repair a full machine — and on a
1 GiB log volume it is 50 MiB you are not using:

```console
$ sudo tune2fs -l /dev/vdb | grep -i reserved
Reserved block count:     13107
$ sudo tune2fs -m 1 /dev/vdb       # reduce the reservation to 1%
```

**A directory hidden under a mount point**: files written to `/var/log/app` *before* the filesystem
was mounted there are still on the parent filesystem, invisible while the mount is in place, and
they explain a `df`/`du` mismatch in the other direction — the parent's space is gone and nothing can
be found. Look underneath:

```console
$ sudo mkdir /mnt/root && sudo mount --bind / /mnt/root
$ sudo du -sh /mnt/root/var/log/app          # what is hidden beneath the mount
$ sudo umount /mnt/root
```

And one measurement trap worth knowing, because this lab's files are made with `fallocate`: `du`
reports **blocks allocated**, `ls -l` reports the **apparent size**. For a sparse file those differ
wildly in one direction; for a preallocated file they agree while the file contains nothing.
`du --apparent-size -sh` is how you ask the other question.

### logrotate: what it actually does

`logrotate` is not a daemon. It is a program that runs on a schedule — a systemd timer on Ubuntu and
most systemd distributions, `/etc/periodic/daily` on Alpine, historically `/etc/cron.daily` — reads
its configuration, and for every rule decides whether the rotation condition is met:

```console
$ systemctl list-timers logrotate.timer         # systemd distributions
$ ls /etc/periodic/daily/                       # Alpine
$ cat /var/lib/logrotate/status                 # when each path was last rotated (after the first run)
```

That has two consequences. `daily` does not mean midnight — it means "the first time logrotate runs
after a day has passed since the last rotation of this path", which is why rotation happens whenever
the timer fires. And the state file, not the filesystem, is what logrotate consults for "when did I
last do this".

A rule lives in `/etc/logrotate.d/<name>` (a drop-in, included by `/etc/logrotate.conf`) and is a
path glob followed by a block of directives:

```
/var/log/app/*.log {
    size 20M          # rotate when it exceeds 20 MiB (a condition, not a schedule)
    rotate 4          # keep four old copies, then discard
    compress          # gzip the old ones (delaycompress defers by one round)
    missingok         # do not complain if the file is absent
    notifempty        # do not rotate an empty file
    copytruncate      # …or a postrotate script: see below
}
```

Two directives are doing the real work, and a rule missing either is a rule that does not solve the
problem:

- **A limit**: `size 20M`, or `daily`/`weekly`/`hourly`, or `maxsize` (which means "this schedule,
  but sooner if it gets this big"). `rotate 4` is *not* a limit — it says how many to keep, not when
  to act. A rule with only `rotate` never fires.
- **A way for the writer to follow the rotation**, which is the next section.

`su root root` becomes necessary when the log directory is writable by a non-root user (logrotate
refuses for good reasons), and `create 0640 root adm` sets the mode of the new file. Globs are
useful — `/var/log/app/*.log` catches the next log this service invents — but they also catch the
rotated files themselves if you are careless with names.

### `copytruncate` versus `postrotate`

Default rotation is `rename + create`: `ledger.log` becomes `ledger.log.1`, a new empty
`ledger.log` appears. But a rename does not change the inode, and the daemon's descriptor points at
the **inode**, not the name. So without further instruction:

- the daemon keeps appending to what is now `ledger.log.1`;
- the new `ledger.log` stays empty forever;
- the next rotation renames again, compresses a file being actively written, and eventually deletes
  it — at which point you are back to the first half of this lab, with space held by a nameless
  inode, permanently, until the service restarts.

That failure is quiet and it is why "we set up logrotate" is not the same as "logs are rotated". Two
ways to fix it:

```
    postrotate
        /bin/kill -HUP $(cat /run/ledger.pid) 2>/dev/null || true
    endscript
```

**`postrotate`** runs a command after the rotation — conventionally a `HUP` to make the daemon
reopen its log by name. Nothing is lost: the daemon writes to the old inode until the signal, then
to the new file. Add `sharedscripts` when the glob matches several files, or the script runs once per
file. This is the better mechanism whenever the program supports it, and it is what distribution
packages do.

```
    copytruncate
```

**`copytruncate`** does not rename. It copies the file's contents to the archive name and then
truncates the original **in place**, so the inode — and therefore the daemon's descriptor — is
retained, and the daemon carries on writing at offset zero without being told anything. It works
with programs that cannot be signalled, which is its reason for existing. Its cost is a race: any
line written between the copy and the truncate is lost, and the copy needs room for a second copy of
the file while it runs. For a log that matters to an auditor, use `postrotate`. For a
stand-in daemon like this one, or a program you do not control, `copytruncate` is the pragmatic
answer.

Test it, always, and do not wait a day:

```console
$ sudo logrotate -d /etc/logrotate.d/ledger    # dry run: says what it WOULD do, changes nothing
$ sudo logrotate -f /etc/logrotate.d/ledger    # force a rotation now, whatever the condition says
$ ls -l /var/log/app/
$ sudo tail -1 /var/log/app/ledger.log ; sleep 2 ; sudo tail -1 /var/log/app/ledger.log
```

Those last two commands are the important ones, and they are the test almost nobody runs: after a
forced rotation, **is the new file growing?** If the timestamp does not move, the daemon is still
writing into the rotated inode and your rule is broken in the quiet way.

### Two init systems

This lab runs on Ubuntu (systemd) and on Alpine (OpenRC), and the mechanisms above are identical on
both — only the service commands differ:

| | systemd | OpenRC |
|---|---|---|
| restart | `systemctl restart ledger` | `rc-service ledger restart` |
| running? | `systemctl is-active ledger` | `rc-service ledger status` |
| at boot? | `systemctl is-enabled ledger` | `rc-update show default` |
| enable | `systemctl enable ledger` | `rc-update add ledger default` |
| logs | `journalctl -u ledger` | `/var/log/messages` (syslog) |

Worth noticing in passing: the systemd unit declares `RequiresMountsFor=/var/log/app`, which makes
systemd pull in and order the mount for that path automatically — the tidy way to say "do not start
me before my filesystem is there". The OpenRC service says the same thing as `need localmount`.

## A failure, walked through

The ledger service is up. `/var/log/app` is 98% full.

**1. Ask the two questions that disagree.**

```console
$ df -h /var/log/app
Filesystem      Size  Used Avail Use% Mounted on
/dev/vdb        974M  881M   26M  98% /var/log/app
$ sudo du -sh /var/log/app
181M    /var/log/app
$ df -i /var/log/app          # rule out inodes while you are here
Filesystem     Inodes IUsed IFree IUse% Mounted on
/dev/vdb        65536    16 65520    1% /var/log/app
```

700 MiB unaccounted for, and it is not inodes. **2. Look at what is visible first**, because part of
the answer is ordinary:

```console
$ sudo ls -lhR /var/log/app
/var/log/app:
total 20K
drwxr-xr-x 2 root root 4.0K Sep 13 04:15 archive
drwx------ 2 root root  16K Sep 13 04:15 lost+found

/var/log/app/archive:
total 180M
-rw-r--r-- 1 root root 90M Sep 13 04:15 ledger-2023.log
-rw-r--r-- 1 root root 90M Sep 13 04:15 ledger-2024.log

/var/log/app/lost+found:
total 0
```

Look at what is *not* there: `ledger.log`. The service is running and writing, and the file it writes
has no name. Two old archives, 180 MiB, are exactly what `du` reported. (`lost+found` is ext4's own
directory for fsck to put orphaned files in; leave it.) They are real files with real names;
nothing clever is needed:

```console
$ sudo rm -r /var/log/app/archive
$ df -h /var/log/app
/dev/vdb        974M  701M  206M  78% /var/log/app
```

**3. Chase the rest, which has no name.**

```console
$ sudo lsof -a +L1 /var/log/app
COMMAND PID USER FD   TYPE DEVICE  SIZE/OFF NLINK NODE NAME
python3 833 root 3w   REG 254,16 734003968     0   13 /var/log/app/ledger.log (deleted)
$ systemctl status 833 --no-pager | head -1
● ledger.service - ledger transaction logger
```

`NLINK 0`: the colleague's `rm` removed the name and ledger still holds the inode, appending to it
twice a second. That is also why this lab's fourth check fails on the broken machine even though
ledger is "running": a service writing into a file nobody can see is not doing its job.

**4. Make the process let go, without stopping it.** ledger reopens on `SIGHUP`:

```console
$ sudo kill -HUP $(systemctl show -p MainPID --value ledger)
$ df -h /var/log/app
/dev/vdb        974M  284K  906M   1% /var/log/app
$ sudo lsof -a +L1 /var/log/app    # silence
$ ls -l /var/log/app/ledger.log    # reopened by name: the file exists again
-rw-r--r-- 1 root root 74 Sep 13 04:16 /var/log/app/ledger.log
$ sudo systemctl is-active ledger  # still running — nothing was stopped
active
```

A restart would have done the same thing; the `HUP` did it without a gap in the log.

**5. Now stop it happening again.** Nothing limits the log:

```console
$ ls /etc/logrotate.d/
alternatives  apt  btmp  cloud-init  dpkg  unattended-upgrades  wtmp  wtmpdb
```

No rule mentions `/var/log/app`. Write one:

```console
$ sudo tee /etc/logrotate.d/ledger >/dev/null <<'CONF'
/var/log/app/*.log {
    size 20M
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
CONF
```

**6. Test it rather than believing it.** First a dry run, which parses the rule and explains its
reasoning; then a forced rotation; then — the step that matters — check that the *new* file is
growing:

```console
$ sudo logrotate -d /etc/logrotate.d/ledger
warning: logrotate in debug mode does nothing except printing debug messages! …
reading config file /etc/logrotate.d/ledger
Reading state from file: /var/lib/logrotate/status
state file /var/lib/logrotate/status does not exist
…
rotating pattern: /var/log/app/*.log 20971520 bytes empty log files are not rotated,
  (4 rotations), old logs are removed
considering log /var/log/app/ledger.log
  log does not need rotating (log size is below the 'size' threshold)

$ sudo logrotate -f /etc/logrotate.d/ledger
$ ls -l /var/log/app/
-rw-r--r-- 1 root root     0 Sep 13 04:16 ledger.log
-rw-r--r-- 1 root root   275 Sep 13 04:16 ledger.log.1.gz
drwx------ 2 root root 16384 Sep 13 04:15 lost+found

$ sleep 2 ; sudo tail -1 /var/log/app/ledger.log ; sleep 2 ; sudo tail -1 /var/log/app/ledger.log
2026-09-13T04:16:52 txn=114 status=ok
2026-09-13T04:16:54 txn=118 status=ok
```

Immediately after a `copytruncate` the live file is empty — that is the truncate — so wait a moment
before the first `tail`, or it prints nothing and looks like a failure.

The count moved, in the new file: `copytruncate` kept ledger's descriptor pointed at the inode it is
still writing to. Had this been a `rename+create` rule with no `postrotate`, the second `tail` would
have printed the same line as the first — the quiet failure.

**7. Check the schedule exists at all.** A perfect rule that nothing runs is not rotation:

```console
$ systemctl list-timers logrotate.timer          # systemd
NEXT                         LEFT LAST                        PASSED UNIT            ACTIVATES
Sun 2026-09-13 04:29:16 UTC 13min Sat 2026-09-12 16:37:54 UTC      - logrotate.timer logrotate.service
$ systemctl cat logrotate.timer | grep -A3 '\[Timer\]'
[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true
$ ls /etc/periodic/daily/                        # Alpine
logrotate
```

**8. Reboot and confirm all four requirements.** The rotation rule is a file, the archive deletion is
permanent, and the freed space cannot come back — but "ledger starts at boot and writes its log" is a
claim about the boot, so test the boot:

```console
$ sudo reboot
$ df -h /var/log/app ; sudo lsof -a +L1 /var/log/app
$ systemctl is-enabled ledger ; systemctl is-active ledger
$ sudo tail -1 /var/log/app/ledger.log ; sleep 2 ; sudo tail -1 /var/log/app/ledger.log
```

## Common wrong turns

**Stopping or removing ledger.** The disk empties instantly and the service the disk exists for is
gone. This lab grades ledger still running and enabled, which is not artificial: "free up space by
stopping the thing that needed the space" is a real outage, reported as a fix.

**`rm` on the file again.** There is no name left to remove. What you will actually delete is the
*new* log the daemon created after the first deletion — leaving a second nameless inode, held open,
and a service writing into nothing.

**Rebooting to reclaim the space.** It works, and it throws away the only record of which process
held the file. You will be back tomorrow with no more information than today.

**`truncate -s 0 /proc/<pid>/fd/3` as a first resort.** It frees the blocks and leaves a sparse file
that reports its old size, so every subsequent measurement misleads you; with a program that seeks or
re-reads, it corrupts. Reach for `SIGHUP` or a restart first, and keep this for the case where
neither is possible.

**Assuming every `df`/`du` gap is a deleted file.** Check inodes (`df -i`), check for a directory
buried under a mount point (`mount --bind / /mnt/root`), and check whether the 5% ext4 reservation is
what you are calling "full". Each is one command.

**Writing a logrotate rule with `rotate 4` and no limit.** `rotate` says how many to keep, not when
to rotate. With no `size`/`daily`/`weekly`/`maxsize`, the condition is never met and the rule does
nothing at all — while looking, to a quick reader, exactly like a rule that works.

**Rotating a daemon's log with neither `copytruncate` nor `postrotate`.** The default is
rename-then-create, and the daemon's descriptor follows the inode, not the name. The new file stays
empty, the renamed one keeps growing, and a couple of rotations later logrotate deletes a file that
is still being written — recreating the problem you started with, permanently.

**Reaching for `copytruncate` without knowing its cost.** Lines written between the copy and the
truncate are lost, and the copy needs room for a second copy of the log. Where the program handles
`SIGHUP` — which is most of them — `postrotate` loses nothing.

**`postrotate` with a glob and no `sharedscripts`.** The script runs once per matched file, so a
five-file glob sends five `HUP`s. Harmless here, not always.

**Believing a rule because it parses.** `logrotate -d` shows what it would do, `-f` makes it do it,
and then `tail` twice a few seconds apart shows whether the daemon followed. The last step is the one
that catches the silent failure.

**Fixing rotation and never checking that logrotate runs.** On systemd it is `logrotate.timer`; on
Alpine it is `/etc/periodic/daily/logrotate`. If neither is in place, the rule is documentation.

**Forgetting that `daily` is not midnight.** logrotate compares against its state file
(`/var/lib/logrotate/status`) when it happens to run. A rule can be correct and still not have
rotated yet, which is what `-f` is for while you are testing.

## Cheat sheet

```console
# is it really full, and of what?
df -h /path                    # blocks
df -i /path                    # inodes — ENOSPC with free blocks
du -sh /path                   # what the visible files add up to
du -sh --apparent-size /path   # …ignoring sparseness/preallocation
du -xh --max-depth=1 /path | sort -h   # where it went, one level at a time (-x: one filesystem)
sudo tune2fs -l /dev/vdb | grep -i reserved     # the 5% root reservation (ext4)
sudo tune2fs -m 1 /dev/vdb                      # …make it 1%

# space with no name
lsof -a +L1 /path              # open files with no remaining link, on that fs  ← the command
                               # (-a: AND the options; lsof ORs them by default)
lsof +D /path                  # everything open under a directory
fuser -vm /path                # every process with anything open on that filesystem
sudo sh -c 'ls -l /proc/[0-9]*/fd/* 2>/dev/null | grep deleted'   # without lsof
                               # (not `sudo ls /proc/*/fd/*`: that glob expands as YOU, first)
stat -L /proc/PID/fd/N         # the real size through the descriptor

# giving it back
kill -HUP PID                  # ask the daemon to reopen its log  ← cheapest, loses nothing
systemctl restart UNIT         # honest and obvious
rc-service NAME restart        # OpenRC
truncate -s 0 /proc/PID/fd/N   # last resort; leaves a sparse file and may corrupt

# hidden under a mount point
mount --bind / /mnt/root ; du -sh /mnt/root/var/log/app ; umount /mnt/root

# logrotate
logrotate -d /etc/logrotate.d/x    # dry run: what it would do
logrotate -f /etc/logrotate.d/x    # force it now
cat /var/lib/logrotate/status      # when each path last rotated
systemctl list-timers logrotate.timer   # what runs it (systemd)
ls /etc/periodic/daily/                 # what runs it (Alpine)

# a rule that works
# /etc/logrotate.d/ledger
#   /var/log/app/*.log {
#       size 20M            ← a limit: size|maxsize|hourly|daily|weekly|monthly
#       rotate 4            ← how many to keep (NOT a limit)
#       compress            ← delaycompress to defer by one round
#       missingok notifempty
#       copytruncate        ← keeps the inode: for daemons that cannot be signalled
#       # or:
#       # postrotate
#       #     /bin/kill -HUP $(cat /run/ledger.pid) 2>/dev/null || true
#       # endscript
#       # sharedscripts     ← run the script once, not once per matched file
#   }

# after a forced rotation, the test that matters
tail -1 /var/log/app/ledger.log ; sleep 2 ; tail -1 /var/log/app/ledger.log
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *logrotate does exactly what it is told, and refuses what it cannot trust* (lab journal `linux-06-log-that-never-rotates`) — Who runs logrotate, and what it remembers
- *Active, green, and not working* (topic journal `monitoring`) — is-active is about the process, not the service

Manual pages: `man 1 df`, `man 1 du`, `man 8 lsof`, `man 5 proc`, `man 8 logrotate`.

The whole subject, end to end: the topic journal *The log lines that were never written down* (`logging-journald`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. `df` says a filesystem is 98% full and `du` on its mount point says 181 MiB of 974 MiB. What is
   each command measuring, and where is the difference?

   > `du` walks the directory tree and sums the files it can reach; `df` asks the filesystem how many
   > blocks are free. The difference is in inodes whose link count has reached zero but which are
   > still held open by a process — deleted files, invisible to a tree walk, still owning their
   > blocks.

2. Why does `rm` on a large file sometimes free no space at all, and what has to happen before the
   blocks come back?

   > `rm` calls `unlink()`, which removes a *name*. The inode survives while any process holds a
   > descriptor on it. The blocks are freed when both the link count and the open count reach zero —
   > so the holder must close it, by reopening its log (`SIGHUP`), by restarting, or by exiting.

3. Name the three ways to make a daemon release a deleted log, and the specific risk of the third.

   > `kill -HUP <pid>` if it reopens on that signal — cheapest, loses nothing; restarting the
   > service — honest, costs a gap; and `truncate -s 0 /proc/<pid>/fd/<n>`, which frees the blocks
   > behind the daemon's back and leaves it writing at its old offset — a sparse file that misreports
   > its size, and corruption for any program that seeks or re-reads.

4. A filesystem reports *No space left on device* while `df -h` shows 40% free. What is the second
   thing to check, and can it be fixed in place?

   > Inodes: `df -i`. An ext4 filesystem has a fixed inode count set at `mkfs` time, and millions of
   > tiny files can exhaust it while blocks remain. It cannot be increased on an existing ext4
   > filesystem — delete files, or rebuild the filesystem.

5. A logrotate rule contains `rotate 4`, `compress` and `missingok`, and the log has never been
   rotated. Why not?

   > There is no rotation condition. `rotate` is how many old copies to keep, not when to act. The
   > rule needs `size`, `maxsize`, or one of `hourly`/`daily`/`weekly`/`monthly` before logrotate
   > will ever act on it.

6. Explain what goes wrong when a daemon's log is rotated with the default rename-and-create and no
   `postrotate` script.

   > The daemon's descriptor points at the inode, and a rename does not change the inode — so it
   > keeps appending to the rotated file while the new one stays empty. A few rotations later
   > logrotate compresses and deletes a file that is still being written, and the space is held by a
   > nameless inode until the service restarts.

7. `copytruncate` and a `postrotate` `HUP` solve the same problem. What does each cost, and when do
   you need `copytruncate`?

   > `postrotate` loses nothing but requires a program that reopens its log on a signal.
   > `copytruncate` copies then truncates in place, keeping the inode — so it works with programs
   > that cannot be signalled, at the price of losing any line written during the copy and needing
   > room for a second copy of the file.

8. You have written a rotation rule and run `logrotate -f`. Which single check tells you whether it
   actually works?

   > `tail -1` on the live log, twice, a couple of seconds apart: if the new file is growing, the
   > writer followed the rotation. If the last line does not change, the daemon is still writing into
   > the rotated inode — the rule is broken in the way that produces no error message.
