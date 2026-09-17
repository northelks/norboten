---
title: Four reasons a service will not stay up
topics: [boot-systemd, firewall-selinux, networking]
minutes: 40
---

"It sometimes comes up, and a few minutes later it is gone. After a reboot it never comes back, and
colleagues see an old page saying the service was retired." That is three different sentences about
three different faults, reported as one problem — which is what a real ticket looks like. There is a
fourth fault nobody mentioned, because nobody could see it.

The four are: a config file the service user may not read, a retired unit still holding the port, an
AppArmor profile pointing at a directory the data left years ago, and no restart policy at all.
Each produces a plausible-but-wrong theory, and each is confirmed or killed by one command. The
skill this lab teaches is not any single fix; it is **getting the machine to tell you which of the
four you are looking at**, one question at a time, and resisting the urge to fix the security policy
by removing it.

## What you should be able to do after this

- Read `systemctl status` and `journalctl -u` well enough to separate "the program never started"
  from "the program started and quit".
- Test a service the way the service runs — as its own user, not as root.
- Find out which process owns a port, and why a unit that cannot bind flaps rather than fails.
- Recognise an AppArmor denial in the log, read the profile that caused it, and grant exactly the
  path that is missing.
- Say how AppArmor and SELinux differ in what they attach a rule to, and why that changes how you
  debug them.
- Choose a `Restart=` policy on purpose, and know what the start-rate limiter will do to you.

## The mechanism

### Ask the two questions in the right order

Every failing service is one of two stories, and the journal tells you which in its first line:

**The program never ran.** systemd could not execute it, or the unit did not load. The exit code is
in the 200s (`203/EXEC`, `200/CHDIR`, `226/NAMESPACE`) and there is no output from the program
itself, because there was no program.

**The program ran and quit.** Then the interesting output is the program's own, and systemd is only
reporting the corpse: `status=1`, or a Python traceback, or `status=0` for something that exited
cleanly and was not supposed to.

```console
$ systemctl status notes
× notes.service - notes internal web app
     Loaded: loaded (/etc/systemd/system/notes.service; disabled; preset: enabled)
     Active: failed (Result: exit-code) since Sun 2026-09-13 04:20:35 UTC; 986ms ago
   Duration: 34ms
    Process: 981 ExecStart=/usr/local/bin/notes-app (code=exited, status=1/FAILURE)

$ sudo journalctl -u notes -b --no-pager | tail -5
notes-app[981]:     with open(CONF) as f:  # raises PermissionError if the service user cannot read it
notes-app[981]:          ~~~~^^^^^^
notes-app[981]: PermissionError: [Errno 13] Permission denied: '/etc/notes/notes.ini'
systemd[1]: notes.service: Main process exited, code=exited, status=1/FAILURE
systemd[1]: notes.service: Failed with result 'exit-code'.
```

Note the `sudo` on `journalctl`. An ordinary account sees only its own messages — without it you get
*"No journal files were opened due to insufficient permissions"* and nothing else, which is easy to
misread as "the service logged nothing". Membership of `adm` or `systemd-journal` is the alternative.

`status=1` with a traceback: the second story. The program started, and it could not read its own
configuration. Note also `disabled` on the `Loaded:` line — a second fault, visible for free, which
answers "after a reboot it never comes back".

### Test as the user, not as root

The reason this fault survived several people looking at it is that `sudo cat /etc/notes/notes.ini`
works perfectly. Root does not consult the permission bits. The unit says `User=notes`, so the
question to ask is what **notes** can read:

```console
$ ls -l /etc/notes/notes.ini
-rw------- 1 root root 38 Sep 13 04:20 /etc/notes/notes.ini

$ sudo -u notes cat /etc/notes/notes.ini
cat: /etc/notes/notes.ini: Permission denied
```

`0600 root:root` — readable by root alone. The conventional shape for a config file that a service
user must read but nobody else should is **`root:<service> 0640`**: owned by root so the service
cannot modify its own configuration, group-readable so it can read it.

```console
$ sudo chown root:notes /etc/notes/notes.ini
$ sudo chmod 0640 /etc/notes/notes.ini
$ sudo -u notes cat /etc/notes/notes.ini
[notes]
port = 8080
```

One detail specific to system users: `notes` has `/usr/sbin/nologin` as its shell, so `su - notes`
fails — as you it asks for a password nobody has, and even as root it only prints *This account is
currently not available* — and either way it tells you nothing about permissions. `sudo -u notes <cmd>` and `runuser -u notes -- <cmd>`
both run a command without needing a login shell, which is why they are the right tools here. If you
need a shell as such a user, `sudo -u notes -s /bin/bash` overrides it.

### Who owns the port

The second symptom — colleagues seeing a retired page — is not your service misbehaving. It is
something else answering. The header is the giveaway, and so is the listener:

```console
$ curl -si localhost:8080/ | head -3
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.13.5

$ sudo ss -lntp | grep :8080
LISTEN 0      5            0.0.0.0:8080      0.0.0.0:*    users:(("python3",pid=870,fd=3))
$ systemctl status 870            # systemd maps a PID back to its unit
● notes-legacy.service - notes (legacy static page)
     Loaded: loaded (/etc/systemd/system/notes-legacy.service; enabled; preset: enabled)
```

`ss -lntp` — listening, numeric, TCP, with the process — is the command to have in your fingers;
`-u` for UDP, `-x` for Unix sockets. `sudo lsof -i :8080` says the same thing. And `systemctl status
<pid>` is the trick worth remembering: it names the *unit* a process belongs to, which turns "some
python is on my port" into "an enabled unit I did not know about is on my port".

A retired unit is retired properly with both axes:

```console
$ sudo systemctl disable --now notes-legacy
```

`--now` stops it, `disable` removes it from the next boot. Stopping without disabling means the port
is free until the reboot, at which point your service loses the race — and it is a race, since
nothing orders the two. If two units genuinely must never run together, say so in the unit:
`Conflicts=notes-legacy.service` makes systemd stop one when starting the other.

What a port conflict looks like from the other side is worth recognising, because it is easy to
misread:

```console
$ sudo journalctl -u notes -b | tail -2
notes-app[1455]: OSError: [Errno 98] Address already in use
```

`EADDRINUSE` (98), not `EACCES` (13). Errno 13 on a bind would be a policy problem — SELinux port
labels, or a low port without privileges (see the rhcsa-04 journal); 98 means another process simply
has it.

### AppArmor: rules attached to paths

Ubuntu's mandatory access control is AppArmor, and the difference from SELinux is worth stating
plainly, because it changes how you debug:

- **SELinux** labels the *inode*. A rule is about a type — `httpd_sys_content_t` — and moving a file
  carries its label along. You debug by asking what label something has.
- **AppArmor** matches the *path*. A rule is a literal or globbed filename inside a profile attached
  to an executable. Moving a file changes which rules apply to it, and nothing about the file itself
  records anything.

So an AppArmor profile is a readable text file naming the paths one program may touch:

```
/usr/local/bin/notes-app {
  include <abstractions/base>
  include <abstractions/python>

  network inet stream,

  /usr/local/bin/notes-app r,
  /usr/bin/python3* ix,
  /etc/notes/ r,
  /etc/notes/** r,

  # notes data
  /var/lib/notes/ r,
  /var/lib/notes/** r,
}
```

The syntax that matters:

- **`r w a k l m ix px ux`** are the permissions: read, write, append, lock, link, memory-map, and
  the three "execute" flavours — `ix` inherits the current profile, `px` transitions to the target's
  own profile, `ux` runs unconfined (avoid).
- **A trailing `/`** means the directory itself. `/srv/notes/ r` grants *listing the directory*;
  `/srv/notes/** r` grants reading the things inside it. You almost always need both, and forgetting
  the first produces a program that can read a file it cannot find.
- **`*` does not cross `/`; `**` does.** `/srv/notes/*` is one level, `/srv/notes/**` is the whole
  subtree.
- **`include <abstractions/…>`** pulls in a curated set of rules (the dynamic linker, `/etc/nsswitch`,
  Python's library paths). Reaching for an abstraction is nearly always better than guessing at
  twenty individual paths.

The profile in this lab is enforcing and correct — for a data directory that no longer exists. The
data is in `/srv/notes`; the profile still names `/var/lib/notes`. The program therefore starts,
listens, answers, and returns a 500 for every request:

```console
$ curl -s localhost:8080/
notes: cannot read /srv/notes: [Errno 13] Permission denied: '/srv/notes'
```

Errno 13 again, and this time the file permissions really are fine (`notes` owns the directory). When
ownership says yes and the kernel says no, something above the permission bits is refusing — so go
and read the denial.

### Reading and fixing a denial

AppArmor denials go to the kernel audit log, which on an Ubuntu system means the journal and `dmesg`:

```console
$ sudo journalctl -k -b | grep -i apparmor | tail -3
audit: type=1400 audit(…): apparmor="DENIED" operation="open" class="file"
  profile="/usr/local/bin/notes-app" name="/usr/local/bin/" pid=1034 comm="notes-app"
  requested_mask="r" denied_mask="r" fsuid=995 ouid=0
audit: type=1400 audit(…): apparmor="DENIED" operation="open" class="file"
  profile="/usr/local/bin/notes-app" name="/srv/notes/" pid=1034 comm="notes-app"
  requested_mask="r" denied_mask="r" fsuid=995 ouid=995
```

There are two denials, and only one of them matters — which is typical. The first is the program
listing its own directory, which it does not need and never notices; the second is the one that
produces the 500. Match the denial to the symptom (`name="/srv/notes/"` is the path in the error
message) instead of granting everything the log mentions.

Read it the way you read an SELinux AVC: `profile=` is who was refused, `name=` is what, and
`denied_mask=` is which permission. Then:

```console
$ sudo aa-status | head -5           # how many profiles, and in which mode
$ sudo apparmor_status               # the same command under its other name
```

The fix is to change the path in the profile — the rule is right in shape and wrong in location —
and reload it. **A profile is not consulted from the file; it is loaded into the kernel**, so editing
without reloading changes nothing:

```console
$ sudo sed -i 's#/var/lib/notes/#/srv/notes/#' /etc/apparmor.d/usr.local.bin.notes-app
$ sudo apparmor_parser -r /etc/apparmor.d/usr.local.bin.notes-app     # -r = replace
$ sudo systemctl restart notes
```

`apparmor_parser -r` replaces a loaded profile; `-a` adds, `-R` removes. `systemctl reload apparmor`
reloads everything. And the tooling can write rules for you from the denials, which is the right way
round when a profile needs many rules:

```console
$ sudo aa-logprof                    # walk the recent denials, propose rules, you approve each
$ sudo aa-genprof /usr/local/bin/notes-app    # build a profile from scratch by exercising the app
```

### The two modes, and the fix that is not a fix

```console
$ sudo aa-complain /usr/local/bin/notes-app    # complain: log, do not block
$ sudo aa-enforce  /usr/local/bin/notes-app    # enforce: block and log
$ sudo aa-disable  /usr/local/bin/notes-app    # unload it entirely
$ sudo cat /sys/kernel/security/apparmor/profiles | grep notes
/usr/local/bin/notes-app (enforce)
```

**Complain mode is a diagnostic**, exactly like SELinux's permissive: put the profile in complain,
exercise the application, collect every denial in one pass with `aa-logprof`, write the rules, go
back to enforce. Leaving it in complain — or `aa-disable`, or `systemctl disable apparmor` — is
turning the security control off to make the application work, which this lab grades against with a
check that already passes on the broken machine. There is nothing artificial about that: an
application that requires MAC to be off is a finding, and "it worked when we disabled AppArmor" is
how it gets written down.

The other tempting shortcut is to widen the rule instead of correcting it — `/** r,` grants the
program read access to the entire filesystem, and the profile then documents nothing. The point of a
profile is that it is a list of what this program legitimately needs; a wildcard at the root is the
same as no profile with extra steps. And a third, subtler version: moving the *data* to
`/var/lib/notes` so the existing rule matches. It would work — and it answers a question nobody
asked, leaving the next person to wonder why the notes are not where every other document says they
are.

### `Restart=`, and the limiter that stops it

A service that dies is a fact of life; whether it comes back is a policy you write down:

| `Restart=` | restarts after |
|---|---|
| `no` (default) | nothing. It stays dead. |
| `on-failure` | non-zero exit, signal, timeout, watchdog — **the usual choice** |
| `on-abnormal` | signal, timeout, watchdog — but not a non-zero exit |
| `always` | any exit at all, clean included |

The app in this lab exits non-zero after a few minutes on purpose (its stand-in for a real leak), so
`on-failure` is enough and is the honest description of the intent. `always` would also work, and
would additionally restart a service that someone deliberately exited cleanly — which you sometimes
want for a daemon that must never be absent, and sometimes very much do not.

The neighbouring knobs:

```ini
[Service]
Restart=on-failure
# wait before restarting (default 100ms)
RestartSec=2s

[Unit]
# the window…
StartLimitIntervalSec=10s
# …and how many starts are allowed in it
StartLimitBurst=5
```

Those last two produce the message that looks like a new fault:

```
Failed to start notes.service: start request repeated too quickly
```

A service that fails immediately — because its config is unreadable, or its port is taken — will hit
the limit within seconds, and then systemd stops trying. Nothing extra is broken; clear the counter
with `systemctl reset-failed notes` once the real cause is fixed. And use a drop-in to add the
policy, rather than editing a unit file in place:

```console
$ sudo mkdir -p /etc/systemd/system/notes.service.d
$ printf '[Service]\nRestart=on-failure\n' | \
    sudo tee /etc/systemd/system/notes.service.d/restart.conf
$ sudo systemctl daemon-reload
$ systemctl show -p Restart --value notes
on-failure
```

(The rhcsa-02 journal covers drop-ins, `enable` versus `start`, and `systemctl cat` in detail; the
same mechanics apply here.)

## A failure, walked through

`http://server:8080/` shows a page saying the service was retired.

**1. Ask who is answering, before assuming it is your service.**

```console
$ curl -si localhost:8080/ | head -3
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.13.5
$ systemctl is-active notes
inactive
```

Your service is not even running, so whatever is on 8080 belongs to something else.

**2. Find the owner, and its unit.**

```console
$ sudo ss -lntp | grep :8080
LISTEN 0      5            0.0.0.0:8080      0.0.0.0:*    users:(("python3",pid=870,fd=3))
$ systemctl status 870 --no-pager | head -3
● notes-legacy.service - notes (legacy static page)
     Loaded: loaded (/etc/systemd/system/notes-legacy.service; enabled; preset: enabled)
     Active: active (running) since Sun 2026-09-13 04:20:27 UTC; 8s ago
$ sudo systemctl disable --now notes-legacy
Removed '/etc/systemd/system/multi-user.target.wants/notes-legacy.service'.
```

`disable` as well as stop, or the reboot hands the port back to it.

**3. Now start the real service and read what it says.**

```console
$ sudo systemctl start notes
$ systemctl is-active notes
failed
$ sudo journalctl -u notes -b --no-pager | tail -3
notes-app[981]: PermissionError: [Errno 13] Permission denied: '/etc/notes/notes.ini'
systemd[1]: notes.service: Main process exited, code=exited, status=1/FAILURE
systemd[1]: notes.service: Failed with result 'exit-code'.
```

`start` itself printed nothing: for a simple service systemd reports success as soon as the process is
running, and the failure arrives 34 ms later. A traceback, so the program ran and quit — this is not
systemd failing to execute it. **4. Reproduce
it as the service user**, which is the step that separates a real answer from a guess:

```console
$ systemctl show -p User --value notes
notes
$ ls -l /etc/notes/notes.ini
-rw------- 1 root root 38 Sep 13 04:20 /etc/notes/notes.ini
$ sudo -u notes cat /etc/notes/notes.ini
cat: /etc/notes/notes.ini: Permission denied
$ sudo chown root:notes /etc/notes/notes.ini && sudo chmod 0640 /etc/notes/notes.ini
$ sudo -u notes head -1 /etc/notes/notes.ini
[notes]
```

**5. Start again. A different failure is progress.**

```console
$ sudo systemctl start notes && systemctl is-active notes
active
$ curl -s localhost:8080/
notes: cannot read /srv/notes: [Errno 13] Permission denied: '/srv/notes'
```

The service is up and answering; it cannot read its data. Check the ordinary permissions first, so
you are not blaming the policy for a `chmod`:

```console
$ sudo ls -ld /srv/notes /srv/notes/welcome.txt
drwxr-x--- 2 notes notes 4096 Sep 13 04:20 /srv/notes
-rw-r----- 1 notes notes   50 Sep 13 04:20 /srv/notes/welcome.txt
```

(`sudo`, because the directory is `750 notes:notes` and you are not `notes` — without it `ls` cannot
even see the file inside.)

`notes` owns both. Ownership says yes, the kernel says no. **6. So read the denial:**

```console
$ sudo journalctl -k -b | grep -i apparmor | tail -1
… apparmor="DENIED" operation="open" class="file" profile="/usr/local/bin/notes-app"
  name="/srv/notes/" pid=1034 comm="notes-app" requested_mask="r" denied_mask="r" fsuid=995 ouid=995
$ sudo aa-status | head -5
apparmor module is loaded.
107 profiles are loaded.
8 profiles are in enforce mode.
   /usr/bin/man
   /usr/local/bin/notes-app
```

A profile is attached to this program and it is enforcing. **7. Read the profile and find the
mismatch:**

```console
$ sudo grep -n notes /etc/apparmor.d/usr.local.bin.notes-app
4:/usr/local/bin/notes-app {
12:  /usr/local/bin/notes-app r,
16:  /etc/notes/ r,
17:  /etc/notes/** r,
19:  # notes data
20:  /var/lib/notes/ r,
21:  /var/lib/notes/** r,
```

The rule is the right shape for the wrong directory — the data moved to `/srv/notes` and the profile
did not. Correct the path, keep both lines (the directory and its contents), and reload into the
kernel:

```console
$ sudo sed -i 's#/var/lib/notes/#/srv/notes/#' /etc/apparmor.d/usr.local.bin.notes-app
$ sudo apparmor_parser -r /etc/apparmor.d/usr.local.bin.notes-app
$ sudo systemctl restart notes
$ curl -s localhost:8080/
notes:
On call this week: apatel.
Welcome to notes. If you can read this, it works.
$ sudo cat /sys/kernel/security/apparmor/profiles | grep notes-app
/usr/local/bin/notes-app (enforce)
```

Enforcing, and working. **8. Deal with the part of the report nobody has addressed yet** — "a few
minutes later it is gone". Wait for it, and watch:

```console
$ sudo journalctl -u notes -f
notes-app[1600]: fatal: connection pool exhausted
systemd[1]: notes.service: Main process exited, code=exited, status=1/FAILURE
systemd[1]: notes.service: Failed with result 'exit-code'.
```

The app dies by design and nothing brings it back:

```console
$ systemctl show -p Restart --value notes
no
$ sudo mkdir -p /etc/systemd/system/notes.service.d
$ printf '[Service]\nRestart=on-failure\nRestartSec=2s\n' | \
    sudo tee /etc/systemd/system/notes.service.d/restart.conf
$ sudo systemctl daemon-reload && sudo systemctl restart notes
```

Prove the policy rather than trusting it — kill the process and watch systemd put it back:

```console
$ pid=$(systemctl show -p MainPID --value notes)
$ sudo kill -9 $pid ; sleep 4 ; systemctl is-active notes
active
$ sudo journalctl -u notes -n 3 --no-pager
systemd[1]: notes.service: Scheduled restart job, restart counter is at 1.
systemd[1]: Started notes.service - notes internal web app.
notes-app[1142]: notes listening on :8080, data in /srv/notes
```

**9. Make the boot do all of it**, and then test the boot:

```console
$ sudo systemctl enable notes
$ sudo reboot
$ systemctl is-active notes ; systemctl is-enabled notes
$ curl -s localhost:8080/ | head -2
$ sudo cat /sys/kernel/security/apparmor/profiles | grep notes-app
$ sudo ss -lntp | grep :8080          # notes-app, not a legacy python
```

## Common wrong turns

**`aa-complain`, `aa-disable`, or stopping AppArmor.** All three make the 500 disappear, and all
three are the finding rather than the fix — the lab has a check that passes on the broken machine
purely to fail this. Complain mode is for *collecting* denials (`aa-logprof` turns them into rules);
enforce is where you leave it.

**Widening the profile to `/** r,`.** The service works and the profile now documents nothing. A
profile's value is that it enumerates what the program legitimately needs; a wildcard at the root is
an unconfined program with a configuration file.

**Moving the data to `/var/lib/notes` so the existing rule matches.** It works, and it silently
relocates the service's data to satisfy a stale rule. Fix the rule; that is why profiles are text.

**Granting `/srv/notes/** r` and not `/srv/notes/ r`.** AppArmor treats the directory itself and its
contents as separate objects: without the trailing-slash rule the program cannot list the directory,
so it never gets as far as the files it is allowed to read. The denial names `/srv/notes/` with the
slash — read it literally.

**Editing the profile and not reloading it.** Profiles live in the kernel. Without `apparmor_parser
-r`, you are looking at a corrected file and running the old rules — and concluding, wrongly, that
the path was not the problem.

**Testing file access as root.** `sudo cat /etc/notes/notes.ini` succeeds on a file readable by root
alone, which is how this fault survived several people looking at it. `sudo -u notes …` or
`runuser -u notes -- …` asks the real question. (`su - notes` will not work at all: a system user
with `nologin` has no shell, and the failure tells you nothing about permissions.)

**`chmod 644` on the config.** It fixes the service and publishes whatever else that file ever comes
to hold. `root:<service>` with `0640` gives the service read access and nobody else any — and keeps
the service unable to rewrite its own configuration.

**Stopping the legacy unit without disabling it.** The port is free now and taken again after the
reboot, and the loser of that race is whichever unit systemd starts second. `disable --now`, or
`Conflicts=` if the two must genuinely never coexist.

**Reading `EACCES` and `EADDRINUSE` as the same problem.** Errno 13 on a bind is a policy question
(SELinux port label, a privileged port); errno 98 is another process. `ss -lntp` distinguishes them
in one line.

**`Restart=always` without thinking, or no restart policy at all.** The default is `no`: a service
that dies stays dead, which is exactly the reported symptom. `on-failure` matches the intent here;
`always` also restarts after a clean, deliberate exit, which is occasionally what you want and
should be a decision.

**Fighting `start request repeated too quickly`.** With a restart policy and a service that fails
instantly, the rate limiter engages within seconds and systemd stops trying. It is a symptom of the
real fault, not a new one: fix the cause, then `systemctl reset-failed notes`.

**Believing the restart policy without testing it.** `systemctl show -p Restart` proves the setting;
`kill -9` on the main PID and a status check four seconds later proves the behaviour.

## Cheat sheet

```console
# which story is it?
systemctl status UNIT              # Loaded: (enabled?), Active:, the exit code, Drop-In:
sudo journalctl -u UNIT -b --no-pager   # this unit, this boot (without sudo/adm: nothing)
sudo journalctl -u UNIT -f              # follow it and wait for the next death
systemctl show -p User -p Restart -p MainPID --value UNIT
# 2xx exit codes = systemd could not run it; status=1 + program output = it ran and quit

# as the service user
sudo -u notes cat /etc/notes/notes.ini      # a system user with nologin still works here
runuser -u notes -- cat /etc/notes/notes.ini
sudo -u notes -s /bin/bash                  # …if you really need a shell
# config a service must read:  chown root:SERVICE + chmod 0640

# who owns the port
ss -lntp | grep :8080              # listening/numeric/tcp/process   (-u UDP, -x unix)
lsof -i :8080
systemctl status PID               # which UNIT a process belongs to
systemctl disable --now other-unit # free it now and at the next boot
# Conflicts=other.service          # …if the two must never run together

# AppArmor
aa-status                          # profiles loaded, and their modes
sudo cat /sys/kernel/security/apparmor/profiles | grep prog     # (enforce) / (complain)
sudo journalctl -k -b | grep -i apparmor   # the denials: profile=, name=, denied_mask=
dmesg | grep -i apparmor
apparmor_parser -r /etc/apparmor.d/PROFILE   # RELOAD after editing (-a add, -R remove)
aa-complain PROG ; aa-logprof ; aa-enforce PROG   # collect denials → rules → back to enforce
aa-genprof PROG                    # build a profile by exercising the program
# rules:  /srv/notes/ r,           ← the directory itself (trailing slash!)
#         /srv/notes/** r,         ← its contents (* stops at /, ** does not)
#         r w a k l m  ix px ux    ← read write append lock link mmap / exec flavours
#         include <abstractions/python>   ← prefer an abstraction to twenty guesses

# restart policy
# [Service] Restart=on-failure|always|on-abnormal|no ; RestartSec=2s
# [Unit]    StartLimitIntervalSec=10s ; StartLimitBurst=5
systemctl reset-failed UNIT         # after "start request repeated too quickly"
kill -9 $(systemctl show -p MainPID --value UNIT) ; sleep 4 ; systemctl is-active UNIT
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The log lines that were never written down* (topic journal `logging-journald`) — Asking precise questions
- *Resolves here, listens there, routes until Tuesday* (topic journal `networking`) — Listening on loopback, or on everything

Manual pages: `man 1 journalctl`, `man 5 systemd.service`, `man 8 ss`, `man 7 apparmor`, `man 8 aa-status`.

Documentation:

- https://ubuntu.com/server/docs/how-to/security/apparmor/

The whole subject, end to end: the topic journal *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. `systemctl status` shows `status=203/EXEC` for one service and `status=1/FAILURE` with a Python
   traceback for another. What does each tell you about where to look next?

   > 203/EXEC means systemd never ran the program — a missing path, a missing execute bit, a bad
   > interpreter line — so the unit file is the place to look. `status=1` with program output means
   > the program ran and chose to exit, so the program's own message in `journalctl -u` is the
   > diagnosis.

2. A config file is `-rw------- root root` and the service fails with `PermissionError`. Why does
   `sudo cat` on that file mislead you, and what is the conventional fix?

   > Root ignores the permission bits, so the test succeeds as root and fails as the service. Test
   > with `sudo -u <service> …`. The conventional ownership for a config a service reads is
   > `root:<service>` mode `0640` — readable by the service, writable by neither it nor anyone else.

3. Something answers on your service's port with an unfamiliar page. Which two commands identify it,
   and why is `systemctl stop` on the culprit not enough?

   > `ss -lntp` (or `lsof -i :8080`) names the process and PID; `systemctl status <pid>` maps that
   > PID back to its unit. `stop` frees the port only until the reboot — the unit is still enabled,
   > so after a reboot the two units race. Use `disable --now`, or declare `Conflicts=`.

4. How do AppArmor and SELinux differ in what a rule attaches to, and what practical difference does
   that make when data moves?

   > AppArmor matches paths inside a profile attached to an executable; SELinux matches labels stored
   > on inodes. So moving a file changes which AppArmor rules apply to it and carries its SELinux
   > label with it. Debugging AppArmor means reading the profile's paths; debugging SELinux means
   > asking what label something has.

5. A profile grants `/srv/notes/** r` and the program still cannot read the notes. What is missing?

   > `/srv/notes/ r` — the directory itself. AppArmor treats the directory and its contents as
   > separate objects, so without the trailing-slash rule the program cannot list the directory and
   > never reaches the files it is allowed to read. The denial names `/srv/notes/` exactly.

6. You correct a path in `/etc/apparmor.d/…` and nothing changes. Why, and what did you skip?

   > Profiles are loaded into the kernel; the file on disk is only the source. Reload it with
   > `apparmor_parser -r /etc/apparmor.d/<profile>` (or `systemctl reload apparmor`), then restart
   > the service.

7. Complain mode makes the problem go away. Why is that not the fix, and what is complain mode
   actually for?

   > It stops enforcing while still logging: the application works because the control was removed,
   > which is an audit finding rather than a repair. Its purpose is to collect every denial in one
   > pass — put the profile in complain, exercise the app, run `aa-logprof` to turn the denials into
   > rules, then `aa-enforce`.

8. The default `Restart=` is `no`. Given a service that dies with a non-zero status every few
   minutes, which policy do you choose, and what will the start-rate limiter do while the underlying
   fault is still present?

   > `Restart=on-failure` — it covers non-zero exits, signals and timeouts without restarting a
   > deliberate clean exit. While the real fault persists the service fails immediately, hits
   > `StartLimitBurst` within its interval, and systemd refuses further attempts with *start request
   > repeated too quickly*. Fix the cause, then `systemctl reset-failed`.
