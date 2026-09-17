---
title: logrotate does exactly what it is told, and refuses what it cannot trust
topics: [logging-journald, users-permissions]
minutes: 35
---

A 300 MB log with a rotation policy beside it looks like logrotate is broken. It is not. It ran every
night and, every night, wrote a line saying why it would not touch this log — and nobody reads the
output of a nightly job that exits quietly. The policy has three separate problems, and logrotate
reacts to each in a different, deliberate way:

- the policy file is **writable by everyone**, so logrotate refuses to read it at all;
- the log directory is **writable by a non-root user**, so logrotate refuses to rename files in it
  as root, and asks — in its error message — to be told whom to act as;
- the policy, once it runs, **keeps no history** and **hands the new log to root**, which the service
  cannot write — the reason the one hand-forced rotation stopped the service logging.

The lesson is less about the directives than about the method: **`logrotate -d` tells you what it
would do and why, for free, without touching anything.** Every fault in this lab is named in its
output.

## What you should be able to do after this

- Say how logrotate is started, how it decides a log needs rotating, and where it remembers when it
  last did.
- Read `logrotate -d` output and find the reason a log is ignored, skipped or not due.
- Explain the two safety refusals — an unsafe configuration file and an unsafe log directory — and fix
  each without weakening the thing it protects.
- Choose between `create` and `copytruncate` for a program that keeps its log open, and say what each
  costs.
- Write a policy that rotates by size, keeps a bounded compressed history, and gives the new log to
  the right owner.
- Tell a log's apparent size from the space it occupies, and why logrotate uses the first.

## The mechanism

### Who runs logrotate, and what it remembers

logrotate is not a daemon. Something starts it once a day: on Ubuntu 26.04 a systemd timer
(`logrotate.timer`), on older systems or containers with cron a script in `/etc/cron.daily`. It reads
`/etc/logrotate.conf`, which sets defaults and then `include /etc/logrotate.d`, where each package
(and each administrator) drops a policy per service. For every log it considers it records the time of
the last rotation in a **state file**, `/var/lib/logrotate/status`, and the next run compares against
it. There is no daemon holding state and nothing to restart after editing a policy.

In this lab's container nothing starts it; you run `logrotate /etc/logrotate.conf` yourself, which is
exactly what the timer does.

### When a log is due

A policy names one or more logs (globs are fine) and a block of directives. The decision to rotate is
one of:

- **time-based**: `daily`, `weekly`, `monthly`, `yearly` — due when that much time has passed since
  the state file's timestamp;
- **`size 50M`**: due whenever the log is larger than that, regardless of time;
- **`minsize` / `maxsize`**: combinations — rotate on schedule but only if at least this big, or on
  schedule *or* as soon as it passes this size.

Size means the **apparent** size (`st_size`), the number `ls -l` prints. This lab's log is sparse:
300 MB to `ls` and `logrotate`, 4 KB on disk to `du`. A log that is really that size on disk behaves
the same way, only the disk fills.

`-f` forces rotation whatever the rule says; `-d` implies verbose and changes nothing, not even the
state file; `-s file` uses another state file, which is how you test a policy without disturbing the
real one.

### What rotation does

For `rotate 7`, logrotate shifts `app.log.6.gz` to `.7.gz` and so on, deletes whatever falls off the
end, renames `app.log` to `app.log.1`, and then deals with the fact that a program probably still has
the old file open. `rotate 0` means the renamed file is deleted at once: rotation happens and no
history is kept. `compress` gzips rotated files; `delaycompress` leaves `.1` uncompressed for one
cycle, for programs that are still finishing writes to it.

### The open file problem: `create` or `copytruncate`

A process that opened `app.log` holds a file descriptor, not a name. After a rename it keeps writing
into what is now `app.log.1`. There are two ways to deal with that:

- **`create mode owner group`** (the default in `/etc/logrotate.conf`) makes a fresh `app.log` right
  after the rename, and a `postrotate` script tells the program to reopen its log — usually a signal
  (`kill -HUP`, `systemctl reload`). The new file's owner and mode are whatever `create` says, and if
  the program runs as `shop` and `create` says `root root 0600`, the program cannot open it. That is
  the fault this lab planted, and why the service stopped logging.
- **`copytruncate`** copies the log to `app.log.1` and truncates the original in place, so the
  program's descriptor stays valid and no reopen is needed. The cost: lines written between the copy
  and the truncate are lost, and a program that does not open its log with `O_APPEND` keeps writing at
  its old offset, leaving a sparse hole the size of the old log.

A program that appends a line at a time (this lab's service opens, appends, closes) works with either,
as long as the file it finds is writable by it.

### Why logrotate refuses: two safety checks

logrotate usually runs as root and renames, creates, deletes and runs scripts. Both refusals protect
against an unprivileged user turning that into root's power.

**The configuration file.** A policy can contain `postrotate` shell commands that root will execute.
If the file is writable by group or others, anyone could put commands there. logrotate prints
`Potentially dangerous mode` and `Ignoring shop because it is writable by group or others`, and moves
on. The fix is to make the file root's and `0644`, never to relax the check.

**The log directory.** If a directory is writable by someone other than root, that user can replace
`app.log` with a symlink to `/etc/shadow` between logrotate's check and its rename or `create`, and
root would do the rest. So logrotate skips logs in such a directory — `because parent directory has
insecure permissions` — unless the policy says **`su user group`**, in which case it drops to that
user for the rotation and can do nothing that user could not do anyway. The directory stays the
service's, which it must be, because the service creates files in it.

A side effect worth knowing: under `su shop shop`, logrotate *is* `shop` when it creates the new log,
so `create 0600 root root` cannot give the file to root. The file comes out `shop`'s. The planted
`create` is still wrong, and still breaks rotation for anyone who "fixes" the directory by handing it
to root instead of adding `su`.

## A failure, walked through

**1. Look at the log and the policy.**

```console
$ ls -la /var/log/shop
drwxrwxr-x 2 shop shop      4096 Sep 14 10:00 .
-rw-r----- 1 shop shop 314572800 Sep 14 10:00 app.log
$ du -h --apparent-size /var/log/shop/app.log ; du -h /var/log/shop/app.log
300M	/var/log/shop/app.log
4.0K	/var/log/shop/app.log
$ ls -l /etc/logrotate.d/shop ; cat /etc/logrotate.d/shop
-rw-rw-rw- 1 root root 90 Sep 14 10:00 /etc/logrotate.d/shop
/var/log/shop/*.log {
    size 50M
    rotate 0
    create 0600 root root
    missingok
}
```

Already visible: the policy is world-writable, and the directory is group-writable by `shop`.

**2. Ask logrotate what it would do.**

```console
$ sudo logrotate -d /etc/logrotate.conf 2>&1 | grep -i -A2 shop
warning: Potentially dangerous mode on shop: 0666
error: Ignoring shop because it is writable by group or others.
error: found error in file shop, skipping
```

**3. Fix the first refusal and ask again.**

```console
$ sudo chmod 0644 /etc/logrotate.d/shop
$ sudo logrotate -d /etc/logrotate.conf 2>&1 | grep -A8 'rotating pattern: /var/log/shop'
rotating pattern: /var/log/shop/*.log 52428800 bytes empty log files are rotated, no old logs will be kept
considering log /var/log/shop/app.log
error: skipping "/var/log/shop/app.log" because parent directory has insecure permissions (It's world writable or writable by group which is not "root") Set "su" directive in config file to tell logrotate which user/group should be used for rotation.
```

The next fault, and its fix, in one line. Note also "no old logs will be kept": that is `rotate 0`.

**4. Add `su` and watch the dry run go all the way through.**

```console
$ sudo sed -i 's|^    size 50M|    su shop shop\n    size 50M|' /etc/logrotate.d/shop
$ sudo logrotate -d /etc/logrotate.conf 2>&1 | grep -A14 'rotating pattern: /var/log/shop'
rotating pattern: /var/log/shop/*.log 52428800 bytes empty log files are rotated, no old logs will be kept
switching euid from 0 to 997 and egid from 0 to 996 (pid 134)
considering log /var/log/shop/app.log
  log needs rotating
rotating log /var/log/shop/app.log, log->rotateCount is 0
renaming /var/log/shop/app.log to /var/log/shop/app.log.1
disposeName will be /var/log/shop/app.log.1
creating new /var/log/shop/app.log mode = 0600 uid = 0 gid = 0
```

It now rotates, as `shop` (uid 997), and throws the history away.

**5. See what `create 0600 root root` does when logrotate runs as root** — the tempting alternative
to `su` is to give the directory to root. Try it on a copy, never on the real log:

```console
$ sudo sh -c 'mkdir -p /tmp/rt/log && … && chown root:root /tmp/rt/log && chmod 755 /tmp/rt/log'
$ sudo logrotate -f -s /tmp/rt/state /tmp/rt/as-root.conf ; sudo ls -l /tmp/rt/log
-rw------- 1 root root 0 Sep 14 10:00 app.log
$ sudo su -s /bin/sh -c 'echo "order accepted" >> /tmp/rt/log/app.log' shop
sh: 1: cannot create /tmp/rt/log/app.log: Permission denied
```

That is last month's outage, reproduced in a scratch directory.

**6. Write the policy that was intended, check it dry, then run it.**

```console
$ printf '/var/log/shop/*.log {\n    su shop shop\n    size 50M\n    rotate 7\n    compress\n    missingok\n    create 0640 shop shop\n}\n' | sudo tee /etc/logrotate.d/shop
$ ls -l /etc/logrotate.d/shop
-rw-r--r-- 1 root root 120 Sep 14 10:00 /etc/logrotate.d/shop
$ sudo logrotate -d /etc/logrotate.conf 2>&1 | grep 'rotating pattern: /var/log/shop'
rotating pattern: /var/log/shop/*.log 52428800 bytes empty log files are rotated, (7 rotations), old logs are removed
$ sudo logrotate /etc/logrotate.conf
$ ls -la /var/log/shop
-rw-r----- 1 shop shop      0 Sep 14 10:03 app.log
-rw-r----- 1 shop shop 305356 Sep 14 10:03 app.log.1.gz
$ /usr/local/bin/shop-log ; sudo tail -1 /var/log/shop/app.log
2026-09-14T10:03:09Z order accepted
$ sudo logrotate -d /etc/logrotate.conf 2>&1 | grep -A4 'considering log /var/log/shop/app.log'
considering log /var/log/shop/app.log
  Last rotated at 2026-09-14 10:03
  log does not need rotating (log size is below the 'size' threshold)
$ sudo grep shop /var/lib/logrotate/status
"/var/log/shop/app.log" 2026-9-14-10:3:7
```

(`tee` writes with the file's existing mode, so the `0644` from step 3 survived.) The new log is
`shop`'s, the service writes to it, the 300 MB of zeros compressed to 300 KB, and the state file has
the rotation. The grader passed all five checks.

## Common wrong turns

**Making `/var/log/shop` root's to silence the "insecure permissions" error.** The error goes away
and the service can no longer create files in its own log directory — and with `create root root`, can
no longer write its log after the first rotation.

**`chmod 0644` the policy and stopping there.** Now it is read, and skipped. Always run `-d` again
after each change; each fault hides the next.

**Testing with `logrotate -f` on the real log.** A forced rotation is a real rotation: it renames,
deletes old history under `rotate 0`, and updates the state file. Test on a copy with `-s` and a
scratch directory, or use `-d`.

**Reading `-d` output and assuming it changed something.** It changed nothing; the log is still 300 MB
until logrotate runs without `-d`.

**Adding `copytruncate` and `create` together.** They are alternatives; with `copytruncate`, `create`
is ignored. Pick one on purpose.

**Using `copytruncate` for a busy log without accepting its cost.** Lines written between the copy and
the truncate are gone, and a writer without `O_APPEND` leaves a sparse file as big as the old log.

**Forgetting `postrotate` for a daemon that keeps its log open.** With `create` and no reopen signal,
the daemon keeps writing into `app.log.1`, which is then compressed and eventually deleted under it.

**Putting `size` and `daily` in the same block and expecting both.** The last time rule wins. For "on
schedule, or sooner if large", use `daily` with `maxsize`.

**Editing `/etc/logrotate.conf` to fix one service.** Service policies belong in `/etc/logrotate.d/`,
where a package update does not overwrite them and where they do not change every other log's
defaults.

**Believing `du` over `ls`.** logrotate decides on `st_size`. A sparse or preallocated log can be due
for rotation while occupying almost nothing.

## Cheat sheet

```bash
# what would happen, and why — changes nothing
sudo logrotate -d /etc/logrotate.conf
sudo logrotate -d /etc/logrotate.d/shop          # one policy (defaults from logrotate.conf not applied)
# for real
sudo logrotate /etc/logrotate.conf               # what the nightly timer runs
sudo logrotate -f /etc/logrotate.d/shop          # force, ignoring the size/time rule
sudo logrotate -v -f -s /tmp/state /tmp/test.conf # test a copy with its own state file
grep shop /var/lib/logrotate/status              # when it last rotated
systemctl list-timers logrotate.timer            # systemd: who starts it

# a policy
/var/log/shop/*.log {
    su shop shop            # rotate as the directory's owner when it is not root's
    size 50M                # or: daily / weekly … ; maxsize 50M rotates early; minsize waits
    rotate 7                # keep seven; 0 keeps none
    compress                # gzip old logs
    delaycompress           # …but not the newest, for one cycle
    missingok               # no error if the log is absent
    notifempty              # do not rotate empty logs
    create 0640 shop shop   # new log's mode and owner   (alternative: copytruncate)
    sharedscripts           # run postrotate once for the whole glob
    postrotate
        systemctl reload shop >/dev/null 2>&1 || true
    endscript
}

# the refusals
# "Ignoring X because it is writable by group or others"  → chmod 0644, owned by root
# "parent directory has insecure permissions … Set \"su\""  → su <owner> <group>, not chown root

# sizes
ls -l app.log                      # apparent size: what logrotate compares
du -h app.log ; du -h --apparent-size app.log
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The space that belongs to a file with no name* (lab journal `linux-01-disk-full`) — copytruncate versus postrotate
- *The log lines that were never written down* (topic journal `logging-journald`) — Where the journal lives, and how big it gets

Manual pages: `man 8 logrotate`.

The whole subject, end to end: the topic journal *The log lines that were never written down* (`logging-journald`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. logrotate ran every night and the log was never rotated, yet nothing failed loudly. Where would the
   reason have been, and how do you get it on demand?

   > In the output of the nightly job (the journal of `logrotate.service` on Ubuntu 26.04, cron's mail on
   > older systems), which nobody reads when the job exits. On demand: `logrotate -d
   > /etc/logrotate.conf`, which explains every decision and changes nothing.

2. Why does logrotate ignore a policy file that is world-writable, instead of just warning?

   > A policy can contain `postrotate` commands that root executes. A file anyone can write is a way
   > for anyone to run commands as root, so logrotate will not read it at all.

3. What attack does the "parent directory has insecure permissions" check prevent, and why is `su`
   the fix rather than `chown root`?

   > A user who can write the directory could swap the log for a symlink to a sensitive file between
   > logrotate's checks and its rename or create, and root would act on the target. With `su`,
   > logrotate acts as that user and can do nothing the user could not. The directory must stay the
   > service's, because the service creates its log there.

4. What happens to a running program's writes after `app.log` is renamed to `app.log.1`, and what are
   the two ways logrotate deals with it?

   > The program's descriptor still points at the renamed file, so it keeps writing to `app.log.1`.
   > Either `create` a new file and have `postrotate` tell the program to reopen its log, or
   > `copytruncate`: copy the contents away and truncate the original, so the descriptor stays valid.

5. What is lost with `copytruncate`, and what goes wrong with a writer that does not use `O_APPEND`?

   > Lines written between the copy and the truncate are lost. A writer without `O_APPEND` keeps its
   > file offset, so its next write lands at the old end of the now-empty file, leaving a sparse hole
   > as large as the log was.

6. With `su shop shop` and `create 0600 root root`, who owns the new log? And with the directory given
   to root instead, and no `su`?

   > With `su`, logrotate runs as `shop` and cannot give a file to root, so the new log is `shop`'s.
   > Without `su`, logrotate runs as root, `create` succeeds exactly as written, and the file is
   > `root:root 0600` — which `shop` cannot write.

7. A log shows 300 MB in `ls -l` and 4 KB in `du`. Which does `size 50M` use, and why do the two
   differ?

   > The apparent size, `st_size`, which `ls` shows. The file is sparse: most of it is holes that
   > occupy no blocks, so `du`, which counts blocks, reports almost nothing.

8. How do you test a changed policy's real behaviour — renames, ownership, the new file — without
   rotating the production log or disturbing when it next rotates?

   > Copy the policy with its paths pointed at a scratch directory set up with the same ownership and
   > mode, and run `logrotate -f -s /tmp/state` on the copy: forced, with its own state file. `-d`
   > alone shows decisions but not the resulting files.
