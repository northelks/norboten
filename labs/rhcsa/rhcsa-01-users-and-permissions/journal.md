---
title: The account that was almost on the team
topics: [users-permissions]
minutes: 35
---

Nothing in this lab is broken in an interesting way. An account was created, a directory was made,
a sudo rule was written, a umask was set during onboarding — and every one of those five ordinary
acts was done one character wrong. The result is a contractor who cannot write to the team's
directory, whose files nobody else can open, who is refused a command the team was promised, and
who can read things that are none of their business.

This is what permission problems actually look like. They are rarely a mystery; they are a
mismatch between four separate mechanisms that all have to agree: who the kernel thinks you are,
what the directory allows, what mask your shell applies to new files, and what sudo was told. This
journal is those four mechanisms, and how to interrogate each one instead of guessing.

## What you should be able to do after this

- Say what a process's identity actually consists of, and why adding someone to a group does not
  change the session they are already in.
- Choose between `usermod -G` and `usermod -aG` deliberately, knowing which one destroys
  membership.
- Read a directory's mode and predict who can create, delete and rename files in it — including
  what the three special bits do, and which of them only makes sense on a directory.
- Build a shared directory that hands its group to every file created in it, and explain why
  group-write alone is not enough.
- Work out where a login shell's umask came from, and change it so it survives the next login.
- Grant one exact command to a group with a sudoers drop-in, verify it without becoming the user,
  and never lock yourself out doing it.

## The mechanism

### Identity is a snapshot, not a lookup

A running process carries its identity as numbers: a real and effective UID, a primary GID, and a
list of supplementary GIDs. Those are set once, when the session is created, from the account
databases — and then nothing re-reads them. The kernel never asks `/etc/group` whether you are
still in `devops`; it compares the GID list it is already holding.

```console
$ id kmorris
uid=1002(kmorris) gid=1006(kmorris) groups=1006(kmorris),1002(developers)

$ id -nG kmorris
kmorris developers
```

Two things to read out of that. First, `gid=1006(kmorris)` is the **primary** group — its own
private group, the RHEL default, and the group new files get when nothing else decides. Everything
after it is **supplementary**. Second, `id kmorris` asks the databases, while plain `id` inside
kmorris's shell reports the snapshot that shell is holding. That is the whole explanation for the
most common support ticket in this area: *"I added them to the group and it still does not work."*
The databases changed; the session did not. Log out and in, or start one shell with the new group:

```console
$ newgrp devops           # new shell, group added, primary group switched
$ sg devops -c 'command'  # one command with that group
```

`getent` is the honest way to read the databases, because it goes through NSS and therefore sees
LDAP, SSSD and anything else configured — where `grep devops /etc/group` sees only the local file:

```console
$ getent group devops
devops:x:1001:apatel
```

### `-G` replaces, `-aG` appends

The single most destructive command in this area is `usermod -G`:

```console
# usermod -G devops kmorris      # kmorris is now in devops ONLY
# usermod -aG devops kmorris     # kmorris is in devops IN ADDITION
```

`-G` sets the complete supplementary list. Run it on a user who was in `wheel` and you have just
removed their sudo access, silently, with a command that looks like it adds something. The muscle
memory to build is `-aG`, always, unless you have consciously decided to replace the list — which
is exactly what this lab needs, because the briefing asks for devops **and no other team**. The
`developers` membership is not an oversight to leave behind; it is why kmorris can read other
teams' files.

Adjacent flags worth knowing: `-g` changes the *primary* group, `-G ''` empties the supplementary
list, and `gpasswd -d kmorris developers` removes one membership without touching the others.

### The bits on a directory mean something different

On a file, `r` is read, `w` is write, `x` is execute. On a directory they are not analogous, and
the difference is where most permission confusion lives:

| bit | on a file | on a directory |
|---|---|---|
| `r` | read the contents | list the names in it |
| `w` | change the contents | **create, delete and rename** entries |
| `x` | run it | traverse it — reach anything inside, by name |

So the right to delete a file has nothing to do with the file's own permissions: it belongs to
whoever can write to the directory holding it. And a directory with `x` but no `r` is perfectly
usable if you already know the filenames — that is how `/srv` and home directories are often
arranged.

Above those nine bits sit three more:

```
      4000  setuid   run the file as its owner            (meaningless on a directory)
      2000  setgid   on a file: run as its group
                     on a directory: NEW ENTRIES INHERIT THE DIRECTORY'S GROUP
      1000  sticky   on a directory: only the owner may delete their own entries (/tmp)
```

The middle one is the point of this lab. Without it, a file created in `/srv/project` gets the
creator's primary group — `kmorris:kmorris` — and the rest of the team cannot touch it no matter
how generous the directory's bits are. With it, the directory's group is stamped on everything
created inside, and on subdirectories the bit itself is inherited too, so the behaviour continues
all the way down.

```console
# chmod 2770 /srv/project          # rwxrws---
# chmod g+s /srv/project           # the same thing, symbolically
$ ls -ld /srv/project
drwxrws---. 2 root devops 37 Sep 13 04:40 /srv/project
```

That `s` sits where the group's `x` would be. Lower case `s` means setgid **and** group-execute;
an upper case `S` means setgid was set while group-execute was not — which is almost always a
mistake, because a directory nobody can traverse is not shared with anyone.

Three bits have to agree for a shared workspace, and it is worth stating them separately because
failing any one produces a different symptom:

1. the directory's **group** is the team's group — otherwise the group bits grant nothing to them;
2. the group has **`rwx`** — `w` to create, `x` to enter;
3. **setgid** is on — otherwise each file arrives owned by a group of one.

Note what this does *not* fix: files that already exist. `/srv/project/README` was created before
the bit was set and keeps whatever group and mode it had. `chgrp -R devops /srv/project` and
`chmod -R g+w` clean up history; setgid only governs the future.

### umask decides what "new" means

A program asks for a mode when it creates a file — `0666` for a regular file, `0777` for a
directory, by near-universal convention — and the kernel removes the bits in the process's umask:

```
requested 666   rw- rw- rw-
umask     022   --- -w- -w-        →  644   rw- r-- r--
umask     002   --- --- -w-        →  664   rw- rw- r--
umask     077   --- rwx rwx        →  600   rw- --- ---
```

So `002` is the collaborative mask: the group keeps write, only outsiders lose it. `022` is the
default for ordinary users on many systems and is *not* enough for a shared directory — it strips
the group's write bit, and a setgid directory then gives your teammates files they can read and
not edit. And `077`, the value set during kmorris's onboarding, removes everything for everybody
else. Note that umask can only ever take permissions away; it cannot grant the execute bit that
`0666` never asked for, which is why new files are not executable.

Where does the value come from? In order, last one wins:

```
/etc/login.defs        UMASK 022        — used by pam_umask, and by useradd for home directories
/etc/profile           often sets 002 for UID >= 1000 with a private group, 022 otherwise
/etc/profile.d/*.sh
~/.bash_profile        the user's own, read only by a LOGIN shell
~/.bashrc              read by interactive non-login shells (and sourced by the default
                       ~/.bash_profile on RHEL-family systems)
```

That login/non-login split matters here. `su kmorris` gives a shell that does not read
`.bash_profile`; `su - kmorris` gives a login shell that does. If you test with the first and the
problem lives in the second, you will conclude the umask is fine. Check it the way the grader
does, the way a real login does:

```console
# su - kmorris -c umask
0077
```

The fix belongs in the same file that broke it, because a `umask` typed into a running shell dies
with that shell. And if you add a line without removing the old one, remember the rule: the file
is a script, it runs top to bottom, and the last `umask` executed is the one you get.

### sudo grants commands, not trust

`sudo` reads `/etc/sudoers`, which on any modern system ends with an include of a directory:

```
@includedir /etc/sudoers.d
```

Drop-in files are how you add rules without ever editing the main file — smaller blast radius,
and easy to remove. Two rules about those files: mode `0440` and owned by root (sudo *ignores* a
file that is group- or world-writable, without saying so out loud), and no dot or tilde in the
filename, or the include skips it. A rule reads:

```
%devops   ALL=(root)   NOPASSWD: /usr/bin/systemctl restart nginx
└─ who    └─ on which  └─ as     └─ no       └─ exactly this command, with these arguments
   (% = a    hosts        whom      password
    group)
```

The leading `%` is the difference between a group and a user — `ops` and `%ops` are not the same
rule, and one of them refers to an account that may not exist. The command is matched **with its
arguments**: this rule permits `systemctl restart nginx` and refuses `systemctl restart sshd` and
`systemctl stop nginx`. Write it as an absolute path, because sudo matches on the path, and a bare
`systemctl` would match nothing.

Edit these files with `visudo`, which syntax-checks before it saves:

```console
# visudo -f /etc/sudoers.d/devops     # edit with a check on save
# visudo -c                           # verify everything, including the drop-ins
# visudo -cf /etc/sudoers.d/devops    # verify one file
```

A syntax error in a sudoers file is the one mistake in this lab that can genuinely lock you out:
sudo refuses to run at all rather than guess, and if sudo was your only route to root you now need
the console and single-user mode. Keep a second root shell open while you edit, or use `visudo`
and let it stop you.

To ask what sudo would allow, ask sudo — do not try to become the user:

```console
$ sudo -l -U kmorris
Matching Defaults entries for kmorris on lima-nb-rhcsa-01:
    !visiblepw, always_set_home, match_group_by_gid, … secure_path=/sbin\:/bin\:/usr/sbin\:/usr/bin

User kmorris may run the following commands on lima-nb-rhcsa-01:
    (root) NOPASSWD: /usr/bin/systemctl restart nginx

$ sudo -l -U kmorris /usr/bin/systemctl restart nginx    # exit status 0 if permitted
/usr/bin/systemctl restart nginx
```

The `Defaults` block comes first and is worth one glance — `secure_path` is the `PATH` sudo gives the
command, which is why a rule must name `/usr/bin/systemctl` and not rely on your own `PATH`.

That second form is a yes/no question about one command, and it does not run it. It is also what
the grader uses, which means the rule has to be genuinely correct rather than merely present.

### Which of these survives a reboot

All five, if you did them in the right place, and that is the point of grading after a reboot.
Group membership lives in `/etc/group`; modes and the setgid bit live in the filesystem's inodes;
the umask lives in a profile file; the sudo rule lives in `/etc/sudoers.d`. The failures are the
ones done in memory: `newgrp` in a shell, `umask 002` typed at a prompt, a `chmod` on a tmpfs, an
`export` that was never written down. If your fix was a command you typed rather than a file you
changed, ask where it was saved.

## A failure, walked through

The briefing says kmorris cannot write to `/srv/project`. Start there, but start by asking who
kmorris is.

**1. The identity.**

```console
$ id -nG kmorris
kmorris developers
```

Two problems in one line: `devops` is absent, so nothing the team's group permits applies to
kmorris; and `developers` is present, which is how kmorris can see other teams' files. The
briefing asks for devops and nothing else, so this is a replacement, not an addition:

```console
$ sudo usermod -G devops kmorris
$ id -nG kmorris
kmorris devops
```

**2. The directory.** Look at the directory itself, not its contents — `-d` is the flag people
forget:

```console
$ ls -ld /srv/project
drwxr-x---. 2 root devops 37 Sep 13 04:40 /srv/project
```

The group is right, and the group has `r-x`: read the names, enter the directory, create nothing.
And there is no `s` in the group triad, so even once writing works, new files will belong to their
creator. Both problems, one command:

```console
$ sudo chmod 2770 /srv/project
$ ls -ld /srv/project
drwxrws---. 2 root devops 37 Sep 13 04:40 /srv/project
```

**3. Prove it as the user, not as yourself.** Root ignores permission bits, so testing as root
proves nothing at all:

```console
$ sudo su - kmorris -c 'touch /srv/project/probe && stat -c %U:%G /srv/project/probe'
kmorris:devops
```

`kmorris:devops` — the setgid bit did its job. Had the group come back as `kmorris`, the bit is
missing; had `touch` failed with *Permission denied*, either the group write bit is missing or the
session does not have the group yet.

**4. The mask the file arrives with.** The file exists and belongs to the right group; can the
team edit it?

```console
$ sudo su - kmorris -c 'umask; stat -c %A /srv/project/probe'
0077
-rw-------
```

There it is: mode `600`, nobody but kmorris. A umask of `077` came from somewhere in the login
path, and since the system-wide files are shared with everyone, look in the account's own:

```console
$ sudo tail -3 /home/kmorris/.bash_profile
# set during onboarding
umask 077
```

Change it in place rather than appending a second line, so the file has one answer:

```console
$ sudo sed -i 's/^umask 077$/umask 002/' /home/kmorris/.bash_profile
$ sudo su - kmorris -c umask
0002
```

**5. The sudo rule.** Ask sudo, then read the file it is reading:

```console
$ sudo -l -U kmorris
User kmorris is not allowed to run sudo on lima-nb-rhcsa-01.

$ sudo cat /etc/sudoers.d/devops
%ops ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx
```

The rule is for `%ops` — a real group, with rsingh in it, and no kmorris. One word wrong:

```console
$ sudo visudo -f /etc/sudoers.d/devops      # %ops → %devops
$ sudo visudo -c
/etc/sudoers: parsed OK
/etc/sudoers.d/00-norboten-grader: parsed OK
/etc/sudoers.d/90-cloud-init-users: parsed OK
/etc/sudoers.d/devops: parsed OK
$ sudo -l -U kmorris | tail -2
User kmorris may run the following commands on lima-nb-rhcsa-01:
    (root) NOPASSWD: /usr/bin/systemctl restart nginx
```

**6. Reboot, then check the same six things again.** Every fix above was written to a file, so it
should all hold — but "should" is not a grade:

```console
$ sudo reboot
$ id -nG kmorris; ls -ld /srv/project; sudo su - kmorris -c umask; sudo -l -U kmorris
```

## Common wrong turns

**`usermod -aG devops kmorris`.** The reflex is correct in general and wrong here: it leaves
`developers` in place, which the briefing explicitly rules out and which is the reason kmorris can
read other teams' files. Read the requirement — *devops and no other team* — and replace the list.

**`chmod 770` without the setgid bit.** Now kmorris can create files, and each one arrives owned
by group `kmorris`. The symptom moves from "cannot write" to "nobody else can open what I wrote",
which feels like a new problem and is the same one.

**`chown -R kmorris:devops /srv/project` and calling it done.** That fixes every file that exists
right now and nothing created after. The setgid bit is the mechanism; chowning is the cleanup.

**Testing as root.** `sudo touch /srv/project/x` succeeds on a directory nobody else can write to,
because root is exempt from the checks. Every permission test has to run as the user in question —
`su - user -c '…'` — or it tests nothing.

**Fixing the umask with `umask 002` at a prompt.** It works for exactly as long as that shell
lives. The graded question is what a *login* gets, which means a file in the login path.

**Putting the umask in `~/.bashrc` and leaving `.bash_profile` alone.** On RHEL-family systems the
default `.bash_profile` sources `.bashrc` near the top — and the broken `umask 077` is appended at
the bottom, so it runs last and wins. Two `umask` lines in the login path is one too many; fix the
line that is wrong.

**Editing sudoers with `vi`.** It usually works, and the once it does not you have a machine where
`sudo` refuses every command, including the one that would fix the file. `visudo` costs nothing
and checks the syntax before saving.

**Writing `ops` instead of `%ops`, or a relative command path.** Without the `%` the rule names a
user; without the absolute path the command matches nothing. Both produce a rule that parses
cleanly and grants nothing, which is the worst kind.

**Granting `%devops ALL=(ALL) ALL` because it definitely works.** It does, and it hands a
contractor full root to satisfy a requirement for one command. The check would pass; the review
would not.

**Forgetting that an open session keeps its old groups.** After `usermod`, kmorris's existing SSH
session still cannot write. Nothing is wrong — log in again. `id` inside the old session and
`id kmorris` from outside disagreeing is the tell.

## Cheat sheet

```console
# identity
id [user]                       # uid, primary gid, supplementary groups
id -nG user                     # just the group names
getent passwd user              # through NSS, so LDAP/SSSD are included
getent group devops             # who is in the group
groups user                     # the same, shorter
newgrp devops                   # a new shell with the group, without logging out

# membership
usermod -aG devops user         # ADD a supplementary group   ← the safe one
usermod -G devops user          # REPLACE the whole list      ← the destructive one
usermod -g devops user          # change the primary group
gpasswd -d user developers      # remove one membership
useradd -m -s /bin/bash user    # with a home and a real shell

# permissions
ls -ld /srv/project             # the directory itself, not its contents
stat -c '%A %a %U:%G' PATH      # symbolic mode, octal mode, owner:group
chmod 2770 DIR                  # rwxrws--- : group may create, files inherit the group
chmod g+s DIR                   # setgid, symbolically
chmod 1777 DIR                  # sticky: only the owner deletes their own (like /tmp)
chgrp -R devops DIR             # fix the files that already exist
chmod -R g+w DIR                # …and their modes
find DIR \! -group devops       # what setgid did not catch

# umask
umask                           # the mask in this shell
su - user -c umask              # the mask a LOGIN shell gets  ← what matters
umask 002                       # files 664, dirs 775 (collaborative)
umask 022                       # files 644, dirs 755 (default; no group write)
grep -r umask /etc/profile /etc/profile.d/ /etc/login.defs ~/.bash_profile ~/.bashrc

# sudo
sudo -l -U user                 # what sudo would allow that user
sudo -l -U user /usr/bin/cmd    # one exact command: exit 0 if permitted
visudo -f /etc/sudoers.d/devops # edit a drop-in, checked on save
visudo -c                       # verify sudoers and every drop-in
sudo ls -l /etc/sudoers.d/      # must be 0440 root:root, no dots in the name (the dir itself is 0750)
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *A folder is shared by its group, not by its permissions alone* (lab journal `linux-05-shared-folder-locks-people-out`) — Directories: read lists, write changes, execute enters
- *A folder is shared by its group, not by its permissions alone* (lab journal `linux-05-shared-folder-locks-people-out`) — What decides a new file's mode

Manual pages: `man 1 id`, `man 8 usermod`, `man 1 chmod`, `man 8 pam_umask`, `man 5 sudoers`, `man 8 sudo`.

## Review

1. `usermod -G devops kmorris` and `usermod -aG devops kmorris` differ by one letter. What does
   each do to a user who is currently in `wheel` and `developers`?

   > `-aG` appends: the user ends up in wheel, developers and devops. `-G` replaces the entire
   > supplementary list: the user ends up in devops alone, having silently lost wheel — and with
   > it, sudo.

2. You added a user to a group and their open SSH session still cannot write to the group's
   directory. What is wrong, and what is the cheapest fix?

   > Nothing is wrong. A process's supplementary groups are a snapshot taken when the session
   > started, and nothing re-reads `/etc/group`. Log in again, or run `newgrp devops` for a new
   > shell. No reboot is involved.

3. A shared directory is `drwxrwx---  root devops`. Group members can create files, but nobody
   else on the team can edit what they create. Which bit is missing, and what exactly does it do?

   > The setgid bit (`chmod g+s`, or `2770`). On a directory it makes new entries take the
   > directory's group instead of the creator's primary group — and subdirectories inherit the bit
   > as well. Files that already exist are unaffected; those need `chgrp`.

4. Why is `umask 022` the wrong mask for a shared directory, and what does `002` give you?

   > `022` removes the group's write bit, so new files come out `644`: your teammates can read your
   > files and not change them. `002` removes only other's write bit — files `664`, directories
   > `775` — which is read and write for the group.

5. You fix a umask by typing `umask 002`, and the check still fails after a reboot. Where should it
   have gone, and how do you test it the way the grader does?

   > Into a file the login path reads — here `~/.bash_profile`, whose existing `umask 077` line is
   > the cause. Test with `su - user -c umask`: the `-` makes it a login shell, which is the only
   > kind that reads `.bash_profile`.

6. `sudo -l -U kmorris` shows no rules, yet `/etc/sudoers.d/devops` clearly contains a rule for
   restarting nginx. Name three separate reasons sudo might be ignoring it.

   > The rule names the wrong principal (`%ops` rather than `%devops`, or `ops` with no `%` at all,
   > which means a user); the file's permissions are wrong, since sudo silently skips a drop-in
   > that is not `0440 root:root`; or the filename contains a dot or tilde, which `@includedir`
   > skips. A syntax error is the fourth, but that one breaks sudo loudly.

7. What makes `vi /etc/sudoers` a materially riskier command than `visudo`, on a machine whose only
   root access is through sudo?

   > A syntax error makes sudo refuse every invocation rather than guess — including the one you
   > would use to repair the file. Recovery then needs the console and single-user mode. `visudo`
   > parses before it saves and hands the file back to you instead.

8. You are asked to let a group restart nginx. Why is `%devops ALL=(ALL) ALL` the wrong way to
   satisfy that, even though it works?

   > It grants unrestricted root to everyone in the group in order to permit one command. The rule
   > should name the exact command with its arguments and an absolute path —
   > `%devops ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx` — which permits that and
   > nothing adjacent, not even `systemctl stop nginx`.
