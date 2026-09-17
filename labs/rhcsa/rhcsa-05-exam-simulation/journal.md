---
title: Ninety minutes on a machine that will not boot
topics: [users-permissions, boot-systemd, storage-lvm, networking, linux-basics]
minutes: 70
---

Fifteen tasks, ninety minutes, and a pass line of seventy per cent — eleven tasks. You do not know
the root password, your own `sudo` is gone, and the machine does not finish booting, so the first
thing to earn is a shell. Everything is graded after a reboot.

The individual tasks here are not hard; most of them are one or two commands, and the mechanisms
behind them appear in the other four journals in this track. What this lab actually tests is
different, and it is the thing that decides real exams: **whether you can order the work, verify as
you go, and leave nothing that only works until the next boot.** Fifteen correct fixes, one of which
you did in a shell instead of a file, is fourteen. And there is one trap on this machine that
converts a correct fix into a locked-out system — it is the second task, and it is the most
important paragraph in this journal.

## What you should be able to do after this

- Interrupt the bootloader, get a root shell through `rd.break`, change the root password, and
  — crucially — leave SELinux able to read the file you just rewrote.
- Repoint a repository at a local mirror, and check that nothing else is enabled.
- Write a systemd timer that genuinely fires, and prove its schedule without waiting for it.
- Create accounts and groups with specified numeric IDs, set password aging, and make an account
  that owns files but cannot log in.
- Configure a time client, a persistent journal and key-based SSH, and verify each of them rather
  than assuming.
- Write a small Bash script that handles its arguments, writes errors to stderr, and exits with the
  status it was asked for.
- Plan ninety minutes: what to do first because everything else depends on it, what to defer, and
  when to spend a reboot.

## The mechanism

### Getting in: interrupt the boot

The bootloader is the one place where nothing on the disk can stop you — which is why physical (or
console) access is root access, and why disk encryption exists. On the lab's screen press **`b`**:
it presses the reset button and attaches to the boot console.

The menu waits ten seconds. Press an arrow key to stop the countdown, highlight the kernel you want,
and press **`e`** to edit its boot entry. On this machine the entry looks like this:

```
 |load_video                                                                  |
 |set gfxpayload=keep                                                         |
 |insmod gzio                                                                 |
 |linux ($root)/vmlinuz-6.12.0-211.54.1.el10_2.aarch64 no_timer_check root=UU\|
 |ID=adbc700e-905a-4aa3-90a2-084cd25fcc12  console=tty0 console=ttyAMA0,11520\|
 |0n8                                                                         |
 |initrd ($root)/initramfs-6.12.0-211.54.1.el10_2.aarch64.img $tuned_initrd   |
```

The `linux` line is *one* line drawn across three rows — the `\` at the right edge marks the wrap. Move
the cursor down onto it, press **Ctrl-E** to jump to the end of that logical line (after `0n8`), and
type a space and:

```
rd.break
```

Get the line right: land on the `initrd` line instead, or on an empty line below it, and GRUB treats
`rd.break` as a command of its own and the boot fails. Then **Ctrl-X** to boot what you have edited. Note that these edits are not written anywhere: they
apply to this boot only, which is exactly what you want, and also means a typo costs one reset.

`rd.break` stops the boot in the **initramfs**, before control is handed to the real root
filesystem. The kernel console is the serial line, so the shell appears on the serial
console (`k`), not the boot console. That is a deliberately strange environment and it explains every
subsequent step — all of which were checked on this machine:

- your root filesystem is mounted at **`/sysroot`**, and it is mounted **read-only**
  (`findmnt /sysroot` shows `ro`);
- the tools you are using are the initramfs's, not the system's — there is no `head`, no
  `getenforce`;
- **SELinux policy is not loaded** — `/sys/fs/selinux` does not exist, and inside the chroot
  `id -Z` says *works only on an SELinux-enabled kernel*.

Older guides show the prompt as `switch_root:/#`. On Rocky 10 both shells — before and after the
`chroot` — say `sh-5.2#`, so the prompt will not tell you where you are; `findmnt /sysroot` will. So:

```console
sh-5.2# mount -o remount,rw /sysroot
sh-5.2# chroot /sysroot
sh-5.2# passwd root
New password:
Retype new password:
passwd: password updated successfully
sh-5.2# ls -Z /etc/shadow
? /etc/shadow
sh-5.2# touch /.autorelabel
sh-5.2# exit
exit
sh-5.2# exit
exit
```

That `?` is the whole next section in one character: the file you just rewrote has no label.

Two neighbouring routes exist and are worth knowing. `init=/bin/bash` replaces PID 1 with a shell,
which boots further and mounts `/` directly — but you must then remount `/` read-write yourself and
you have no systemd, so `exit` does not continue the boot and you must reboot forcibly.
`systemd.debug-shell=1` gives you a root shell on tty9 of a system that otherwise boots normally.
`rd.break` is the documented RHCSA path and the one to have in your fingers.

### The trap: `/.autorelabel`

`passwd` rewrites `/etc/shadow`. In the `rd.break` environment there is no SELinux policy loaded, so
the file that comes out has no valid label — and once the system boots with the policy in force,
nothing may read it. Not `login`, not `sshd`, not `su`, not `sulogin`. The failure is spectacular
and entirely silent at the moment you cause it. This is what it looked like when the relabel was
skipped on this machine, which also has a broken `fstab` and so drops to emergency mode:

```
You are in emergency mode. After logging in, type "journalctl -xb" to view
system logs, "systemctl reboot" to reboot, or "exit"
to continue bootup.
Cannot open access to console, the root account is locked.
See sulogin(8) man page for more details.
Press Enter to continue.
```

*The root account is locked* — seconds after you set its password. `sulogin` cannot read `/etc/shadow`,
so it concludes there is no usable root password. Pressing Enter retries the boot, which fails on the
same `fstab`, which lands on the same message: a loop with no way out except the bootloader. Booted
permissive, the label shows what happened:

```console
# getenforce ; ls -Z /etc/shadow
Permissive
system_u:object_r:unlabeled_t:s0 /etc/shadow      # should be shadow_t
```

`touch /.autorelabel` tells the next boot to relabel the whole filesystem and then reboot again. It
costs a couple of minutes on a lab machine (and much more on a real one), and it is the safe answer.

If you are already locked out, the recovery is to go back to the bootloader and append **`enforcing=0`**
instead of `rd.break`. The system boots permissive, `sulogin` can read the file, and you can repair
just the account files — verified on this machine:

```console
# restorecon -v /etc/shadow /etc/passwd /etc/group /etc/gshadow
Relabeled /etc/shadow from system_u:object_r:unlabeled_t:s0 to system_u:object_r:shadow_t:s0
```

and then reboot into enforcing (the kernel-line edit was never saved, so a plain reboot does it).

Some older guides offer a third route: `load_policy -i` inside the `rd.break` chroot, then
`restorecon /etc/shadow`. **Do not use it on RHEL/Rocky 10.** Tried on this machine, `load_policy -i`
loaded the policy in *enforcing* mode while the shell was still running as `kernel_t`: `restorecon`
failed with *Permission denied*, `ls` was denied reading `/etc/shadow`, and after `exit` the
initramfs could not execute its own cleanup (`Failed to start initrd-cleanup.service`). It turns a
missing label into a machine that cannot finish the initramfs. Note
what is *not* on the list: setting `SELINUX=disabled`. That converts a two-minute relabel into an
audit finding, and this lab's second check — which passes on the broken machine and can only be
broken by you — exists precisely to catch the version of task 1 that skips this step.

The general rule behind the specific trap: **a file written while the policy was not loaded has no
label, and a file moved rather than copied keeps its old one.** Any time you edit system files from
a rescue environment, relabel afterwards.

### Repositories and packages

A repository is a file in `/etc/yum.repos.d/*.repo`:

```ini
[lab-local]
name=Lab packages
baseurl=file:///opt/repos/local
enabled=1
gpgcheck=0
```

The id in brackets is what `dnf` calls it; `baseurl` can be `http://`, `https://`, or `file://` for
a local directory — note the three slashes, two for the scheme and one for the absolute path. When
the mirror is a directory on this machine, `file:///opt/repos/local` is the whole configuration.
`gpgcheck=0` says do not verify signatures, which is acceptable for a local mirror you control and
is what the task asks for; the alternative is `gpgkey=file:///etc/pki/rpm-gpg/…`.

```console
$ dnf repolist                       # enabled repositories
$ dnf repolist --all                 # including the disabled ones — read this when asked
                                     # for "no other repository enabled"
# dnf config-manager --set-disabled some-repo
# dnf clean all                 # after changing a baseurl, so stale metadata is not reused
# dnf -y install tree
$ rpm -q tree                        # the verification, from the other tool
$ dnf provides '*/sysreport'         # which package ships a given file
```

`dnf` caches metadata aggressively, so a repository that was pointing at a dead URL can keep
reporting the dead URL's error after you fix it. `dnf clean all` is the reflex.

### Timers that actually fire

A systemd timer is a *pair* of units: `foo.service` does the work, `foo.timer` decides when. You
enable the **timer**, not the service — the service is `static` and pulled in by the timer:

```ini
[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
```

`OnCalendar` takes a calendar expression: `*:0/15` is "every 15 minutes starting at minute 0" —
`0/15` means from 0, in steps of 15. `*:0,15,30,45` says the same thing by listing. Other shapes
worth recognising: `hourly`, `daily`, `Mon..Fri 09:00`, `*-*-01 03:00` (the first of the month).
`Persistent=true` means that if the machine was off when the timer should have fired, it fires once
after boot — the `anacron` behaviour. `OnBootSec=`/`OnUnitActiveSec=` express a monotonic schedule
instead: `OnUnitActiveSec=15min` is "15 minutes after the last run", which drifts, where `OnCalendar`
does not.

Never trust a calendar expression you have not checked, and never wait fifteen minutes to find out:

```console
$ systemd-analyze calendar '*:0/15'
  Original form: *:0/15
Normalized form: *-*-* *:00/15:00
    Next elapse: Sun 2026-09-13 05:15:00 UTC
       From now: 48s left
$ systemctl list-timers | grep sysreport
Sun 2026-09-13 05:15:00 UTC    42s -                                - sysreport.timer              sysreport.service
# systemctl start sysreport.service    # test the work without waiting for the schedule
```

The fault on this machine is a misspelling — `OnCalender=` — and it is worth dwelling on what
systemd does with it. An unknown key on its own is not fatal: it is ignored with a warning. But once
it is ignored this timer has no schedule at all, and a timer with no schedule is refused outright:

```console
$ systemd-analyze verify /etc/systemd/system/sysreport.timer
/etc/systemd/system/sysreport.timer:5: Unknown key 'OnCalender' in section [Timer], ignoring.
sysreport.timer: Timer unit lacks value setting. Refusing.
Unit sysreport.timer has a bad unit file setting.
$ systemctl list-timers --all | grep -c sysreport
0
```

So `list-timers --all` does not show a broken timer — it does not show the timer at all, and a fast
reader concludes it was never installed. Two habits protect you: run `systemd-analyze verify` on any
unit you did not write, which names the unknown key, and read `systemctl list-timers` rather than the
file.

```console
# systemctl daemon-reload
# systemctl enable --now sysreport.timer      # the TIMER, and --now so it is running too
Created symlink '/etc/systemd/system/timers.target.wants/sysreport.timer' → '/etc/systemd/system/sysreport.timer'.
```

### Accounts with specified numbers, and two ways to say "no login"

```console
# groupadd -g 5000 auditors
# useradd -u 5001 -G auditors maria
# useradd -u 5002 -G auditors -s /sbin/nologin sam
```

`-u` and `-g` are the numeric ID flags; `-G` is the supplementary group list (see the rhcsa-01
journal for `-G` versus `-aG`). `-s /sbin/nologin` is the shell that prints a message and exits,
which is how you make an account that exists for file ownership and cannot be logged into.

Distinguish three things that all sound like "disabled":

| | what it stops | what it does not stop |
|---|---|---|
| `usermod -s /sbin/nologin` | interactive login, by any means | `su - sam -c cmd` as root, file ownership, cron |
| `passwd -l` / `usermod -L` | password authentication (a `!` prefix in `/etc/shadow`) | **SSH key** login, sudo from another account |
| `chage -E 0` | the account entirely, as expired | nothing much; this is the strong one |

The task here says *no interactive login is possible*, and the shell is the mechanism that answers
it. Locking the password would leave key-based login open, which is the classic half-answer.

Password aging lives in `/etc/shadow` and is edited with `chage`:

```console
# chage -M 90 maria          # maximum age: must change at least every 90 days
# chage -m 7 maria           # minimum age: may not change more often than weekly
# chage -W 14 maria          # warn 14 days ahead
# chage -E 2026-12-31 maria  # the account expires on this date
# chage -d 0 maria           # force a change at the next login
# chage -l maria             # read all of it back  ← always verify
```

`/etc/login.defs` holds the defaults (`PASS_MAX_DAYS`, `PASS_MIN_DAYS`, `PASS_WARN_AGE`) applied to
accounts created *afterwards*; changing it does not touch existing users, which is a common
misreading of a task that says "maria's password must expire every 90 days".

### Time, journal, keys

**chrony.** The client config is `/etc/chrony.conf`. A `pool` line resolves to many servers, a
`server` line to one; when a task says "use only this server", every existing `pool` and `server`
line has to go — comment them out rather than deleting, so you can see what you changed.

```console
# vi /etc/chrony.conf             # comment out pool/server lines; add: server 192.168.5.2 iburst
# systemctl restart chronyd
# chronyc sources | tail -1
^? _gateway                      0   6     0     -     +0ns[   +0ns] +/-    0ns
# chronyc -n sources | tail -1
^? 192.168.5.2                   0   7     0     -     +0ns[   +0ns] +/-    0ns
$ timedatectl                     # clock, timezone, NTP enabled/synchronised
```

`iburst` makes the first synchronisation fast rather than polite; it is what you want on a server
that just booted. `chronyc sources` showing your server — and nothing else — is the proof, with one
trap: chrony resolves addresses to names, and on this machine `192.168.5.2` is the gateway, so it is
listed as `_gateway` and looks like the wrong server. `-n` shows numbers, and it is an option to
`chronyc` itself, so it goes *before* the command: `chronyc -n sources`. (`chronyc sources -n` is
silently the same as without it.) The `^?` means not yet reachable — in this lab nothing answers on
that address, and the task is the configuration, not the synchronisation.

**The journal.** `journald` keeps logs in memory unless it is told, or allowed, to keep them on disk:

```
Storage=persistent   always /var/log/journal, created if missing
Storage=auto          /var/log/journal if it EXISTS, otherwise /run  ← the compiled-in default
Storage=volatile      /run only: nothing survives a reboot
```

The setting comes from `/etc/systemd/journald.conf` and then every drop-in in
`/etc/systemd/journald.conf.d/`, **in filename order, the last one winning**. On this machine:

```console
# ls /etc/systemd/journald.conf.d/
90-norboten.conf  99-retention.conf
# cat /etc/systemd/journald.conf.d/90-norboten.conf /etc/systemd/journald.conf.d/99-retention.conf
[Journal]
Storage=persistent
[Journal]
Storage=volatile
```

The image asks for `persistent`; somebody's later drop-in says `volatile`, and `99` sorts after `90`,
so volatile wins. (Deleting `/var/log/journal` would not have done it on its own: Rocky's
`systemd-tmpfiles` configuration recreates the directory at every boot.) Remove the drop-in — with
`-f`, because root's `rm` on RHEL is an alias for `rm -i` and will stop to ask:

```console
# rm -f /etc/systemd/journald.conf.d/99-retention.conf
# mkdir -p /var/log/journal ; systemd-tmpfiles --create --prefix /var/log/journal
# systemctl restart systemd-journald
# journalctl --flush                                    # move /run's journal to /var
# journalctl --list-boots | tail -2                     # more than one line = it is kept
```

`--list-boots` is the honest test, and it can only pass after a reboot has happened with the
configuration in place — which is one more reason to spend a reboot before the clock runs out.

**SSH keys.** Key authentication is a keypair plus one line in the target account's
`authorized_keys`, and `sshd` is deliberately fussy about permissions (`StrictModes`): a
group-writable home directory or a readable-by-others private key makes it refuse the key and fall
back to a password, with the reason only in the server's log.

```console
# su - maria
$ ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
$ ssh-copy-id maria@localhost          # or: cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
$ chmod 700 ~/.ssh ; chmod 600 ~/.ssh/authorized_keys
$ ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new maria@localhost true && echo key-login-works
Warning: Permanently added 'localhost' (ED25519) to the list of known hosts.
key-login-works
```

`BatchMode=yes` is the verification that matters: it disables every interactive prompt, so the
command succeeds only if the key alone was enough. Testing with a plain `ssh` and typing a password
proves nothing about the key. If it fails, `journalctl -u sshd -n 20` (as root) names the reason —
usually `Authentication refused: bad ownership or modes`.

### Script arguments

The task specifies behaviour precisely, and the specification *is* the test: three lines on stdout,
`-o FILE` writes them to a file instead, any other option prints to **stderr** and exits **2**.

```bash
#!/bin/bash
report() {
    echo "hostname: $(hostname -s)"
    echo "kernel: $(uname -r)"
    echo "root_free: $(df --output=pcent / | tail -1 | tr -dc '0-9' | awk '{print 100-$1}')%"
}
case "${1:-}" in
    "") report ;;
    -o) [ -n "${2:-}" ] || { echo "sysreport: -o needs a file" >&2; exit 2; }
        report > "$2" ;;
    *)  echo "sysreport: unknown option: $1" >&2; exit 2 ;;
esac
```

The pieces worth naming: `$1`, `$2` are positional parameters and `$#` is how many there are;
`${1:-}` is "`$1`, or empty if unset", which keeps `set -u` scripts from dying on no arguments;
`>&2` redirects to stderr, which is where errors belong because stdout is data; `exit 2` is the
status the caller was promised; and `"$2"` is quoted, because a filename with a space is not your
script's business to mangle. `shift` and a `while` loop are the general pattern when there are more
options than this; `getopts` is the tidy version.

Two details specific to the output. `hostname -s` is the *short* name, so a machine called
`web01.lab.example` would report `web01` (this one is simply `lima-nb-rhcsa-05`). And free space as a percentage is the complement of what `df`
prints: `df --output=pcent /` gives used percent, so subtract from 100 — and check it against
`df -h /` by eye, because an off-by-one here is a failed task on an otherwise perfect script.

### You have no sudo: `su -`

The briefing says your account's `sudo` was removed, and it means it — `sudo` asks for a password and
then refuses, and even `ls /etc/sudoers.d` is denied. Once task 1 has given root a password you know,
the first command over SSH is:

```console
$ sudo -n true
sudo: a password is required
$ su -
Password:
#
```

Everything else is done in that root shell (so the `#` prompts in this journal), or you do task 15
first — put yourself back in `wheel` — and **log in again** so your session picks the group up. Either
works; what does not work is typing `sudo` in front of fifteen tasks and wondering why none of them
happened. And remember what a root shell on RHEL changes: `rm`, `cp` and `mv` are aliased with `-i`,
so a script-like sequence pasted into it stops at the first prompt and the *next line* becomes the
answer.

### The last two: a shared directory, and your own sudo

`/srv/audit` is the rhcsa-01 mechanism exactly: group `auditors`, group `rwx`, setgid so new files
inherit the group, and **nothing for others** because the task says nobody else may enter:

```console
# mkdir -p /srv/audit
# chgrp auditors /srv/audit
# chmod 2770 /srv/audit               # not 2777: `o` must be empty
```

And your own administrative access is group membership, not a new sudoers file. RHEL's
`/etc/sudoers` already contains `%wheel ALL=(ALL) ALL`; the previous admin removed you from the
group:

```console
# usermod -aG wheel YOUR_ACCOUNT      # -aG: add, do not replace (not $USER — in `su -` that is root)
# sudo -l -U YOUR_ACCOUNT | tail -1
    (ALL) ALL
```

Remember that your *current* session still holds its old group list. Log in again before concluding
it did not work — the same lesson as rhcsa-01, and the reason people redo a correct fix twice.

### How to spend ninety minutes

An order, because some tasks block others and some are cheap:

1. **Get in** (task 1), with `/.autorelabel` (task 2). Nothing else can start until you have root.
   Budget 10 minutes, including the relabel reboot. From then on work in `su -`, or do task 15 first
   and log in again.
2. **Make it boot** (task 3): the `fstab` UUID. Do this next, because every later verification wants
   a machine that boots normally, and because a broken `fstab` has no network — see the rhcsa-03
   journal for the mechanism.
3. **The repository** (task 4), because task 5 (`tree`) cannot happen without it.
4. **Everything independent**, cheapest first: accounts and group (7), aging (8), nologin (9), the
   shared directory (14), wheel (15), chrony (11), the journal (12). None of these takes more than a
   minute or two. (Task 12 is a one-line fix once you have found the drop-in that wins.)
5. **The script** (10) and the **timer** (6). The script is the longest single task; do it while you
   still have attention, and test it three ways (no arguments, `-o`, a bad option) rather than once.
6. **Keys** (13), then **reboot with time to spare** and re-verify everything. The reboot is not
   optional: it is where a runtime-only fix confesses, and it is the only way task 12 can pass.

Two exam habits worth more than any single command. **Verify each task as you finish it** — `chage
-l`, `systemctl list-timers`, `chronyc sources`, `dnf repolist`, `sudo -l -U`, `ls -Zd` — because a
task you believe is done and is not costs you the whole task and you will never look again. And
**keep moving**: eleven of fifteen is a pass, so a task that is fighting you is worth abandoning for
ten minutes while you collect three cheap ones, and coming back to.

## A failure, walked through

The machine hangs in the boot. Nothing is known and nothing can be logged into.

**1. Get to the bootloader and interrupt the initramfs.**

```console
  (b on the lab's screen: reset, and the boot console)
  (an arrow key to stop the countdown; `e` on the first entry; cursor down to the `linux` line;
   Ctrl-E; type " rd.break")
 |linux ($root)/vmlinuz-6.12.0-211.54.1.el10_2.aarch64 no_timer_check root=UU\|
 |ID=adbc700e-905a-4aa3-90a2-084cd25fcc12  console=tty0 console=ttyAMA0,11520\|
 |0n8 rd.break                                                                |
  (Ctrl-X)
```

The shell arrives on the serial console, so detach (`Ctrl-]`) and press `k` for it:

```console
sh-5.2# findmnt /sysroot
TARGET   SOURCE    FSTYPE OPTIONS
/sysroot /dev/vda3 xfs    ro,relatime,attr2,inode64,logbufs=8,logbsize=32k,noquota
sh-5.2# mount -o remount,rw /sysroot
sh-5.2# chroot /sysroot
sh-5.2# passwd root
New password:
Retype new password:
passwd: password updated successfully
sh-5.2# touch /.autorelabel
sh-5.2# exit
exit
sh-5.2# exit
exit
```

The boot resumes, the relabel runs, and the machine reboots itself once more — that second reboot is
the relabel finishing; do not interrupt it.

**2. It still does not finish booting, and now you can read why.** You have a root password, so the
maintenance prompt accepts you:

```console
Give root password for maintenance
(or press Control-D to continue):
[root@lima-nb-rhcsa-05 ~]# ls -Z /etc/shadow ; ls /.autorelabel
system_u:object_r:shadow_t:s0 /etc/shadow
ls: cannot access '/.autorelabel': No such file or directory
```

Checked first, deliberately: `shadow_t`, and the flag file is gone — the relabel ran and consumed it.
The trap did not spring. Now the boot:

```console
# systemctl --failed --no-legend
# journalctl -xb -p err --no-pager | grep -v '░' | tail -1
… systemd[1]: Timed out waiting for device dev-disk-by\x2duuid-76d3b598\x2d71c5\x2d45f9\x2d85b2\x2d29a902d956a2.device - /dev/disk/by-uuid/76d3b598-71c5-45f9-85b2-29a902d956a2.
# systemctl status data.mount --no-pager | grep -E 'Active|What'
     Active: inactive (dead)
       What: /dev/disk/by-uuid/76d3b598-71c5-45f9-85b2-29a902d956a2
# blkid /dev/vdb
/dev/vdb: UUID="74cb22f9-11f8-4a0f-a843-69b47d79f402" BLOCK_SIZE="512" TYPE="xfs"
```

`systemctl --failed` prints nothing — the device job timed out and the mount was never attempted, so
nothing is *failed* (the rhcsa-03 journal explains why). The error log has the answer: `fstab` names a
UUID that does not exist on this machine. Fix the source, verify, and continue the boot:

```console
# uuid=$(blkid -s UUID -o value /dev/vdb)
# sed -i "s|^UUID=[^ ]* /data |UUID=$uuid /data |" /etc/fstab
# systemctl daemon-reload
# findmnt --verify --tab-file /etc/fstab
Success, no errors or warnings detected
# mount -a && findmnt /data
TARGET SOURCE   FSTYPE OPTIONS
/data  /dev/vdb xfs    rw,relatime,seclabel,attr2,inode64,logbufs=8,logbsize=32k,noquota
# systemctl default
Failed to connect to system scope bus via local transport: No such file or directory
…
lima-nb-rhcsa-05 login:
```

Despite the complaint, the boot continues to a login prompt and SSH answers.

**3. Become root.** Your own account has no sudo:

```console
$ sudo -n true
sudo: a password is required
$ su -
Password:
#
```

**4. The repository, then the package.**

```console
# dnf repolist --all | grep -v disabled
repo id                    repo name                                    status
lab-local                  Lab packages                                 enabled
# cat /etc/yum.repos.d/lab-local.repo
[lab-local]
name=Lab packages
baseurl=http://mirror.lab.invalid/rocky10/
enabled=1
gpgcheck=0
# ls /opt/repos/local
repodata  tree-2.1.0-8.el10.aarch64.rpm  zsh-5.9-15.el10.aarch64.rpm
```

The mirror is a directory on this machine; point the repository at it and clear the metadata:

```console
# sed -i 's|^baseurl=.*|baseurl=file:///opt/repos/local|' /etc/yum.repos.d/lab-local.repo
# dnf clean all
# dnf repolist
repo id        repo name
lab-local      Lab packages
# dnf -y install tree
…
Complete!
# rpm -q tree
tree-2.1.0-8.el10.aarch64
```

Everything else was already disabled, which satisfies "no other repository is enabled" — but the
`--all` listing is how you know rather than assume.

**5. The timer that never fires — and does not even appear.**

```console
# systemctl list-timers --all | grep -c sysreport
0
# systemd-analyze verify /etc/systemd/system/sysreport.timer
/etc/systemd/system/sysreport.timer:5: Unknown key 'OnCalender' in section [Timer], ignoring.
sysreport.timer: Timer unit lacks value setting. Refusing.
```

One letter, and systemd refuses the whole unit. Fix it, check the expression, reload, enable the timer:

```console
# sed -i 's/^OnCalender=/OnCalendar=/' /etc/systemd/system/sysreport.timer
# systemd-analyze calendar '*:0/15'
  Original form: *:0/15
Normalized form: *-*-* *:00/15:00
    Next elapse: Sun 2026-09-13 05:15:00 UTC
       From now: 48s left
# systemctl daemon-reload && systemctl enable --now sysreport.timer
Created symlink '/etc/systemd/system/timers.target.wants/sysreport.timer' → '/etc/systemd/system/sysreport.timer'.
# systemctl list-timers | grep sysreport
Sun 2026-09-13 05:15:00 UTC    42s -                                - sysreport.timer              sysreport.service
```

The timer's service runs `/usr/local/bin/sysreport -o /var/log/sysreport.txt`, which does not exist
yet — so the schedule is right and the work will fail until task 10 is done. Note the dependency and
move on.

**6. The cheap block, verified one at a time.**

```console
# groupadd -g 5000 auditors
# useradd -u 5001 -G auditors maria
# useradd -u 5002 -G auditors -s /sbin/nologin sam
# id maria; id sam
uid=5001(maria) gid=5001(maria) groups=5001(maria),5000(auditors)
uid=5002(sam) gid=5002(sam) groups=5002(sam),5000(auditors)

# chage -M 90 maria && chage -l maria | grep Maximum
Maximum number of days between password change		: 90

# mkdir -p /srv/audit && chgrp auditors /srv/audit && chmod 2770 /srv/audit
# ls -ld /srv/audit
drwxrws---. 2 root auditors 6 Sep 13 05:14 /srv/audit

# usermod -aG wheel YOUR_ACCOUNT && sudo -l -U YOUR_ACCOUNT | tail -1
    (ALL) ALL

# sed -i -E 's/^(server|pool)[[:space:]]/# &/' /etc/chrony.conf
# echo 'server 192.168.5.2 iburst' >> /etc/chrony.conf
# systemctl enable --now chronyd ; systemctl restart chronyd
# chronyc -n sources | tail -1
^? 192.168.5.2                   0   7     0     -     +0ns[   +0ns] +/-    0ns
```

The journal, which needs one more look than the others:

```console
# ls /etc/systemd/journald.conf.d/
90-norboten.conf  99-retention.conf
# cat /etc/systemd/journald.conf.d/99-retention.conf
[Journal]
Storage=volatile
# rm -f /etc/systemd/journald.conf.d/99-retention.conf
# mkdir -p /var/log/journal ; systemd-tmpfiles --create --prefix /var/log/journal
# systemctl restart systemd-journald && journalctl --flush
# ls -ld /var/log/journal
drwxr-sr-x+ 3 root systemd-journal 46 Sep 13 05:03 /var/log/journal
```

Note the `-f` on `rm`. Without it, root's `rm -i` alias asks *remove regular file …?* — and if you
pasted several lines, the next one is taken as the answer, the file stays, and nothing complains.

**7. The script, tested against its specification rather than by eye.**

```console
# vi /usr/local/bin/sysreport      # (the case/esac version above)
# chmod 755 /usr/local/bin/sysreport
# sysreport
hostname: lima-nb-rhcsa-05
kernel: 6.12.0-211.54.1.el10_2.aarch64
root_free: 89%
# df -h / | tail -1                # sanity-check the arithmetic: 11% used is 89% free
/dev/vda3        15G  1.6G   14G  11% /
# sysreport -o /tmp/r && cat /tmp/r
hostname: lima-nb-rhcsa-05
kernel: 6.12.0-211.54.1.el10_2.aarch64
root_free: 89%
# sysreport -z ; echo "exit=$?"
sysreport: unknown option: -z
exit=2
# systemctl start sysreport.service && cat /var/log/sysreport.txt
hostname: lima-nb-rhcsa-05
kernel: 6.12.0-211.54.1.el10_2.aarch64
root_free: 89%
```

**8. Keys, proved without a password prompt.**

```console
# su - maria -c 'ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519 &&
    cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
# su - maria -c 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new maria@localhost true'; echo "exit=$?"
Warning: Permanently added 'localhost' (ED25519) to the list of known hosts.
exit=0
```

**9. Reboot, with time left, and walk the list again.** This is a task in its own right, not a
formality:

```console
# reboot
$ findmnt /data                       # 3
$ dnf repolist ; rpm -q tree          # 4, 5
$ systemctl list-timers | grep sysreport   # 6
$ id maria ; id sam ; sudo chage -l maria | head -4   # 7, 8, 9  (sudo works again: new login)
$ sysreport                           # 10
$ chronyc -n sources                  # 11
$ sudo journalctl --list-boots        # 12  ← only provable after a reboot
$ sudo su - maria -c 'ssh -o BatchMode=yes maria@localhost true'   # 13
$ ls -ld /srv/audit ; sudo -l | tail -1   # 14, 15
$ ls -Z /etc/shadow ; getenforce      # 1, 2
```

## Common wrong turns

**`rd.break` without `touch /.autorelabel`.** The password is set, and `sulogin` answers *Cannot open
access to console, the root account is locked* — because `/etc/shadow` is `unlabeled_t` and the policy
forbids reading it. On this machine, whose `fstab` is also broken, Enter just retries the failing boot
and returns to the same message. Recover by booting with `enforcing=0` and running `restorecon` on the
account files, or by going back to `rd.break` and touching the flag. This is the single most expensive
mistake available on this machine.

**`load_policy -i` in the `rd.break` chroot, to avoid the relabel.** Older guides suggest it. On Rocky
10 it loads the policy enforcing while the shell is still `kernel_t`: `restorecon` is denied, and after
`exit` the initramfs cannot run its own cleanup. Use `/.autorelabel`, or `enforcing=0` afterwards.

**Typing `sudo` for every task.** Your account's sudo was removed; every one of those commands asks for
a password and refuses. `su -` with the root password you just set, or task 15 first and a fresh
login.

**Pasting commands into a root shell.** Root's `rm`, `cp` and `mv` are aliased with `-i` on RHEL. The
first one asks a question, the next pasted line becomes the answer (not *y*), the file survives, and
the lines after it run against a state you did not intend. `rm -f`, or `\rm`.

**"Fixing" the label problem with `SELINUX=disabled`.** It works, it needs a reboot, coming back
needs another reboot plus a relabel, and it fails the check that exists for exactly this. Permissive
(`enforcing=0` on the kernel line, once) is the diagnostic; relabelling is the fix.

**Forgetting that the boot-menu edit is temporary.** It is — which is good. People sometimes go back
to remove `rd.break` from GRUB's configuration; there is nothing to remove.

**Leaving `/data` out of `fstab`, or mounting it by device name.** `mount /dev/vdb /data` satisfies
the eye and not the reboot. The task says mount at boot, by UUID or label. `findmnt --verify` before
the reboot, every time.

**Changing `/etc/login.defs` for maria's aging.** `PASS_MAX_DAYS` there applies to accounts created
afterwards. An existing user's aging lives in `/etc/shadow` and is set with `chage -M 90 maria`.
`chage -l maria` is the read-back.

**Locking sam's password instead of setting `nologin`.** `passwd -l sam` blocks password
authentication and leaves key-based login working. "No interactive login" is a property of the
shell.

**Enabling `sysreport.service` instead of `sysreport.timer`.** The service has no `[Install]` section,
so `enable` refuses and prints a paragraph about static units; adding `WantedBy=multi-user.target` to
make that go away gives you a job that runs once at boot and never again. The timer is the unit with
the schedule and the `[Install]` section that belongs in `timers.target`.

**Trusting a calendar expression.** `*/15` where `0/15` was meant, `15` on its own, a missing colon:
each produces a timer that either never fires or fires at a surprising moment. `systemd-analyze
calendar` costs one second and `systemctl list-timers` shows the next elapse.

**Looking for the timer in `list-timers` and concluding it was never installed.** The unknown key is
ignored, the timer is then left with no schedule, and systemd *refuses* it — so `list-timers --all`
does not list it at all. The file is there and looks right. `systemd-analyze verify <unit>` names the
key.

**Configuring chrony by adding a line and leaving the pool.** "Only this server" means the existing
`pool`/`server` lines go. `chronyc -n sources` shows what it is really using, which is the only answer
that counts — and without `-n`, placed before the command, the lab's server is listed as `_gateway`
and looks wrong when it is right.

**Adding `Storage=persistent` in a new drop-in and leaving the volatile one.** Drop-ins apply in
filename order and the last one wins: a `50-persistent.conf` loses to `99-retention.conf`. Find the
file that sets the value you do not want and remove it. And without `journalctl --flush` the current
boot's logs stay in `/run` — which matters because the check asks for more than one boot in
`--list-boots`.

**Testing SSH by typing a password.** That proves the account works, not the key. `-o
BatchMode=yes`, or watch for the absence of a prompt. When it fails, the reason is in
`journalctl -u sshd`, and it is usually the permissions on `~/.ssh` or the home directory.

**A script that prints its error to stdout, or exits 1.** The specification said stderr and 2. In a
graded task and in a pipeline, the difference is the whole point of the exercise: stdout is data,
stderr is commentary, and the exit status is what the caller branches on.

**Reporting used space where free space was asked for.** `df --output=pcent` is *used*; the task
wants the complement. Compare your script's output with `df -h /` before you move on.

**Doing the tasks in file order.** Task 5 needs task 4; almost everything needs tasks 1 and 3; and
task 12 cannot be proved without a reboot. Read all fifteen first, then order them by dependency and
by cost.

**Not spending a reboot.** More than half the failure modes in this lab are runtime-only fixes, and
the grading reboot finds every one of them. Reboot yourself, with fifteen minutes left, and re-walk
the list.

## Cheat sheet

```console
# getting in
# at the GRUB menu: any key to stop the countdown, `e` to edit, Ctrl-X to boot
rd.break                       # stop in the initramfs; root is /sysroot, read-only, no policy
                               # (the linux line wraps: cursor onto it, Ctrl-E, append; Ctrl-X boots)
  mount -o remount,rw /sysroot ; chroot /sysroot ; passwd ; touch /.autorelabel ; exit ; exit
init=/bin/bash                 # PID 1 is a shell; remount / rw yourself; no clean exit
enforcing=0                    # boot permissive once, to repair labels
systemd.debug-shell=1          # a root shell on tty9

# labels after a rescue edit
restorecon -v /etc/shadow /etc/passwd /etc/group /etc/gshadow
restorecon -n -v PATH          # dry run: silence means correct
touch /.autorelabel && reboot  # relabel everything (then it reboots again by itself)

# repositories and packages
dnf repolist ; dnf repolist --all
dnf config-manager --set-enabled|--set-disabled REPO
dnf clean all                  # after changing a baseurl
dnf -y install|remove PKG ; rpm -q PKG ; dnf provides '*/file'
# /etc/yum.repos.d/x.repo:  [id] / name= / baseurl=file:///opt/repos/local / enabled=1 / gpgcheck=0

# timers
systemctl list-timers --all
systemd-analyze calendar '*:0/15'
systemd-analyze verify /etc/systemd/system/foo.timer      # names unknown keys
systemctl enable --now foo.timer                          # the TIMER, not the service
systemctl start foo.service                               # test the work now
# OnCalendar=*:0/15 | hourly | Mon..Fri 09:00 ; Persistent=true ; WantedBy=timers.target

# accounts
groupadd -g 5000 auditors
useradd -u 5001 -G auditors maria
useradd -u 5002 -G auditors -s /sbin/nologin sam
usermod -aG wheel USER         # administrator, the standard way
chage -M 90 -m 7 -W 14 USER ; chage -E 2026-12-31 USER ; chage -d 0 USER
chage -l USER                  # verify
passwd -l USER                 # password auth off — does NOT stop key login

# time
vi /etc/chrony.conf            # comment out pool/server; add: server 192.168.5.2 iburst
systemctl enable --now chronyd ; chronyc -n sources ; chronyc tracking ; timedatectl

# journal
# Storage=auto (default) uses /var/log/journal if it exists; persistent always; volatile never
ls /etc/systemd/journald.conf.d/   # drop-ins apply in filename order: the LAST Storage= wins
mkdir -p /var/log/journal ; systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald ; journalctl --flush ; journalctl --list-boots

# ssh keys
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
ssh-copy-id user@host          # or append the .pub to ~/.ssh/authorized_keys
chmod 700 ~/.ssh ; chmod 600 ~/.ssh/authorized_keys
ssh -o BatchMode=yes user@host true && echo ok     # proves the KEY worked
journalctl -u sshd -n 20       # why it refused

# script arguments
"$1" "$2" "$#" "$@" "${1:-}"   # positional, count, all, defaulted
case "${1:-}" in -o) … ;; *) echo "msg" >&2 ; exit 2 ;; esac
hostname -s ; uname -r ; df --output=pcent /        # used percent: free is 100 minus this
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Three layers of "permission denied"* (lab journal `rhcsa-04-selinux-firewall-network`) — Everything has a label
- *The volume that filled overnight* (lab journal `rhcsa-03-storage-and-lvm`) — fstab, and what systemd does with it
- *The volume that filled overnight* (lab journal `rhcsa-03-storage-and-lvm`) — The maintenance prompt
- *Counting things, and the specification is the test* (lab journal `linux-04-write-the-report`) — Options: getopts
- *The log lines that were never written down* (topic journal `logging-journald`) — Where the journal lives, and how big it gets
- *The account that was almost on the team* (lab journal `rhcsa-01-users-and-permissions`) — The bits on a directory mean something different

Manual pages: `man 7 dracut.cmdline`, `man 5 fstab`, `man 5 dnf.conf`, `man 8 dnf`, `man 5 systemd.timer`, `man 7 systemd.time`, `man 8 groupadd`, `man 8 useradd`, `man 1 chage`, `man 5 shadow`, `man 5 passwd`, `man 1 bash`, `man 5 chrony.conf`, `man 5 journald.conf`, `man 1 ssh-keygen`, `man 8 sshd`, `man 5 sudoers`.

The whole subject, end to end: the topic journal *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. You set the root password through `rd.break`, and the maintenance prompt now says *Cannot open
   access to console, the root account is locked*. What happened, and name two ways out.

   > `passwd` rewrote `/etc/shadow` in an environment with no SELinux policy loaded, so the file is
   > `unlabeled_t` and the policy forbids reading it — `sulogin` cannot see a usable root password. Either boot with `enforcing=0` and
   > `restorecon -v /etc/shadow /etc/passwd /etc/group /etc/gshadow`, or return to `rd.break` and
   > `touch /.autorelabel`. Disabling SELinux is not one of the ways out.

2. In the `rd.break` shell, why is `mount -o remount,rw /sysroot` needed before `passwd`, and why
   `chroot /sysroot` after it?

   > The initramfs mounts the real root read-only at `/sysroot`, so nothing can be written yet. The
   > `chroot` makes `/sysroot` the shell's `/`, so `passwd` edits the system's `/etc/shadow` rather
   > than the initramfs's, and uses the system's own configuration.

3. A timer unit file exists and looks correct, but `systemctl list-timers --all` does not list it at
   all. What class of mistake is that, and which command names it?

   > A key systemd does not recognise — `OnCalender=` for `OnCalendar=`. The unknown key is ignored,
   > the timer is left with no schedule, and systemd refuses to load it (*Timer unit lacks value
   > setting. Refusing.*).
   > `systemd-analyze verify <unit>` reports the unknown key; `systemd-analyze calendar '<expr>'`
   > then confirms the schedule means what you think.

4. A task says a user's password must be changed at least every 90 days. Why is editing
   `/etc/login.defs` the wrong answer?

   > `login.defs` supplies defaults for accounts created *after* the change; it does not touch
   > existing ones. Aging for an existing account lives in `/etc/shadow`: `chage -M 90 maria`, read
   > back with `chage -l maria`.

5. Two ways to stop someone logging in are `usermod -s /sbin/nologin` and `passwd -l`. Which one
   answers "no interactive login is possible", and what does the other one leave open?

   > The `nologin` shell: there is no interactive shell to start, by any authentication method.
   > `passwd -l` only disables password authentication — an SSH key in `authorized_keys` still
   > works, which is exactly the gap a task like this is testing for.

6. `/etc/systemd/journald.conf.d/` holds `90-norboten.conf` with `Storage=persistent` and
   `99-retention.conf` with `Storage=volatile`, and `/var/log/journal` exists. Is the journal kept
   across reboots, and what is the fix?

   > No. Drop-ins apply in filename order and the last assignment wins, so `volatile` from `99-…`
   > overrides `persistent`, and the existing directory is ignored. Remove the `99-` drop-in (with
   > `rm -f`, since root's `rm` asks first), restart `systemd-journald`, and `journalctl --flush` to
   > move the current boot out of `/run`. Adding another `persistent` drop-in with a smaller number
   > would change nothing.

7. You test key-based SSH with `ssh maria@localhost`, type maria's password, and get a shell. What
   have you proved, and what is the correct test?

   > Only that the account and the password work — the key may not have been used at all.
   > `ssh -o BatchMode=yes maria@localhost true` disables every prompt, so a zero exit status means
   > the key alone authenticated. Failures are explained in `journalctl -u sshd`, usually as bad
   > ownership or modes on `~/.ssh`.

8. With fifteen tasks, ninety minutes and a pass line of eleven, what are the two habits that most
   change the outcome?

   > Verify each task the moment you finish it, with the command that reads the state back
   > (`chage -l`, `list-timers`, `chronyc sources`, `dnf repolist`, `sudo -l -U`, `ls -Zd`) — a task
   > you wrongly believe is done is never revisited. And reboot deliberately, with time left, then
   > re-walk the list: the grading reboot is where every runtime-only fix fails, and one task here
   > cannot even be proved without it.
