---
title: A folder is shared by its group, not by its permissions alone
topics: [users-permissions, linux-basics]
minutes: 30
---

Three people share a folder and none of them can work in it. It is tempting to see one fault — "the
permissions are wrong" — and one fix, `chmod -R 777`. There are really four separate questions, and
each has its own answer in a different place: **who is in the group** (`/etc/group`), **what the files
that already exist allow** (their owner, group and mode bits), **what files created tomorrow will
allow** (the directory's setgid bit, the author's umask, default ACLs), and **what everyone else can
reach** (the "other" bits — on the directory as much as on the files).

The lab's folder gets every one of them wrong, and a previous admin's hardening makes the third worse:
every login runs `umask 077`, so anything anyone writes is private to its author the moment it is
saved. Fixing today's files with `chmod` without touching the third question gives a folder that
works this afternoon and is broken again tomorrow morning.

## What you should be able to do after this

- Say how the kernel picks *one* of owner, group or other for a given user and file, and why the
  choice is not cumulative.
- Explain what read, write and execute mean on a directory, and why a file can be unreachable even
  when its own bits allow reading.
- Add a user to a supplementary group without removing their other groups, and know when the change
  takes effect.
- Give a group access to an existing tree with `chgrp -R` and `chmod -R g+rwX,o-rwx`, and say what the
  capital `X` is for.
- Use the setgid bit on a directory so new files inherit its group.
- Read a umask and predict the mode of a file created under it; find where a login sets it.
- Use default ACLs to keep group access on new files regardless of the author's umask, and read the
  `mask` and `#effective` lines `getfacl` prints.

## The mechanism

### One class, chosen once

Every file has an owner, a group and nine mode bits: `rwx` for the owner, `rwx` for the group, `rwx`
for everyone else. When a process opens the file, the kernel does not add these up. It picks exactly
one class and uses only its bits:

1. If the process's user **is the owner**, the owner bits decide — even if they allow less than the
   group bits would.
2. Otherwise, if the owning group is the process's primary group **or any of its supplementary
   groups**, the group bits decide.
3. Otherwise the other bits decide.

root skips the check for reading and writing. That is why the grader, and you with `sudo`, see
everything, and why you must look at the folder through the users' own eyes — `su - bob` — to see
what bob sees.

In the broken folder, `budget.csv` is `-rw-r--r-- bob bob`. bob is its owner and may write. alice is
not bob and not in the group `bob`, so the other bits apply: read only. dave is in the same position
as alice — which is exactly the problem, because dave is not on the team.

### Directories: read lists, write changes, execute enters

On a directory the same bits mean different things:

| bit | on a file | on a directory |
|---|---|---|
| `r` | read the contents | list the names in it |
| `w` | change the contents | create, rename and delete entries in it (with `x`) |
| `x` | run it | enter it: reach anything inside by name |

Two consequences matter here. A file is reachable only if you have `x` on **every directory on the
path** to it, so taking `x` away from others on `/srv/reports` locks dave out of every file inside,
whatever those files' own bits say. And deleting a file needs write on the *directory*, not on the
file: anyone with `w` and `x` on a shared folder can delete anyone else's report. (The sticky bit,
`chmod +t`, restricts deletion to the file's owner; `/tmp` uses it. A team that edits each other's
files usually does not want it, but it is the answer when they should only add.)

### Groups: membership is read at login

A user's groups are listed in `/etc/group`. `usermod -aG reports carol` appends `reports` to carol's
supplementary groups; without `-a`, `-G` *replaces* them and silently removes every other group she
had. The change is recorded at once, but a process's groups are fixed when it is created, so a
session that was already open keeps its old list. `su - carol`, a new SSH login or `newgrp reports`
picks up the new one. This is the most common reason a correct fix "does not work" until someone logs
out.

### What decides a new file's mode

A program that creates a file asks for a mode — usually `0666` for files and `0777` for directories —
and the kernel removes the bits set in the process's **umask**. With the usual `022`, files come out
`0644` and directories `0755`. With `002` — Ubuntu's default for users who have their own private
group, applied by `pam_umask` — they come out `0664` and `0775`. With the hardening in this lab,
`077`, they come out `0600` and `0700`: nobody but the author can do anything.

A umask is inherited by child processes, and it is set in more than one place: `/etc/login.defs`
(`UMASK`, read by `pam_umask`), `/etc/profile` and `/etc/profile.d/*.sh` for login shells, and a
user's own `~/.profile` or `~/.bashrc`. The last one to run wins. Here it is
`/etc/profile.d/00-hardening.sh`.

The new file's **group** is decided separately. Normally it is the creator's primary group — alice's
files get the group `alice`. If the directory has the **setgid** bit (`chmod g+s`, shown as `s` in the
group execute position), new entries get the directory's group instead, and new subdirectories inherit
the setgid bit, so the rule propagates down the tree.

### Default ACLs: group access the umask cannot remove

POSIX ACLs add entries beyond the three classes: `group:reports:rwx` grants that named group access
whether or not it owns the file. An ACL on a directory can also carry **default** entries, which are
copied onto every file and directory created inside it.

Default ACLs change how the umask applies: when the parent directory has a default ACL, the umask is
not used at all. The new file's ACL comes from the defaults, limited only by the mode the program
asked for. So a default `group:reports:rwx` gives every new file group read and write even under
`umask 077` — which is why the reference solution uses it.

One more entry appears whenever named entries exist: the **mask**. It is the maximum any named user,
named group or the owning group can get, and it is what `ls -l` shows in the group position. A file
created with mode `0666` gets a mask of `rw-`, so `getfacl` prints `group:reports:rwx #effective:rw-`:
the entry says `rwx`, the mask cuts it to `rw-`. A later `chmod g-w` lowers the mask, and with it every
named entry at once — a frequent surprise.

## A failure, walked through

The roster names three people. The group has two:

```console
$ cat /srv/reports/TEAM.txt
reports team: alice bob carol
$ getent group reports
reports:x:1001:alice,bob
$ id carol ; id dave
uid=1003(carol) gid=1004(carol) groups=1004(carol)
uid=1004(dave) gid=1005(dave) groups=1005(dave)
```

**1. Look at the folder as a listing, then as the people who use it.**

```console
$ ls -la /srv/reports /srv/reports/drafts
/srv/reports:
drwxr-xr-x 3 alice alice 4096 Sep 14 09:57 .
-rw------- 1 alice alice   31 Sep 14 09:57 2026-q3-summary.txt
-rw-r--r-- 1 alice root    30 Sep 14 09:57 TEAM.txt
-rw-r--r-- 1 bob   bob     38 Sep 14 09:57 budget.csv
drwxr-xr-x 2 bob   bob   4096 Sep 14 09:57 drafts

/srv/reports/drafts:
-rw------- 1 bob   bob     21 Sep 14 09:57 q4-outline.txt
$ sudo su - bob -c 'cat /srv/reports/2026-q3-summary.txt'
cat: /srv/reports/2026-q3-summary.txt: Permission denied
$ sudo su - dave -c 'cat /srv/reports/budget.csv'
item,amount
servers,1200
licences,300
```

Every file belongs to its author's private group, so the group bits never apply to a teammate, and the
folder is `755` — open to everyone for reading.

**2. Find out what tomorrow's files will look like.**

```console
$ sudo su - alice -c 'umask; touch /srv/reports/scratch.txt; ls -l /srv/reports/scratch.txt'
0077
-rw------- 1 alice alice 0 Sep 14 09:57 /srv/reports/scratch.txt
$ grep -rn umask /etc/profile /etc/profile.d/ /etc/login.defs /etc/pam.d/common-session | grep -v ':#'
/etc/profile.d/00-hardening.sh:2:umask 077
/etc/pam.d/common-session:23:session optional			pam_umask.so
```

`pam_umask` would give `002`; the profile snippet runs later and wins.

**3. Fix the group, then the existing tree.**

```console
$ sudo usermod -aG reports carol
$ id carol
uid=1003(carol) gid=1004(carol) groups=1004(carol),1001(reports)
$ sudo chgrp -R reports /srv/reports
$ sudo chmod -R g+rwX,o-rwx /srv/reports
$ sudo find /srv/reports -type d -exec chmod g+s {} +
$ ls -ld /srv/reports ; sudo ls -la /srv/reports
drwxrws--- 3 alice reports 4096 Sep 14 09:57 /srv/reports
drwxrws--- 3 alice reports 4096 Sep 14 09:57 .
-rw-rw---- 1 alice reports   31 Sep 14 09:57 2026-q3-summary.txt
-rw-rw---- 1 alice reports   30 Sep 14 09:57 TEAM.txt
-rw-rw---- 1 bob   reports   38 Sep 14 09:57 budget.csv
drwxrws--- 2 bob   reports 4096 Sep 14 09:57 drafts
```

`g+rwX` gives the group read and write, and execute only where it makes sense: on directories, and on
files that were already executable for someone. A lowercase `x` would have marked every report as a
program. Note that the plain `ls` of the folder, as `learner`, would now be refused: you are not on the
team either.

**4. Check tomorrow, not just today.** The setgid bit got the group right; the umask still wins:

```console
$ sudo su - alice -c 'echo "first draft" > /srv/reports/q4-plan.txt'
$ sudo ls -l /srv/reports/q4-plan.txt
-rw------- 1 alice reports 12 Sep 14 09:57 /srv/reports/q4-plan.txt
$ sudo su - bob -c 'echo "bob was here" >> /srv/reports/q4-plan.txt'
-bash: line 1: /srv/reports/q4-plan.txt: Permission denied
```

**5. Give the group a default ACL.** `-m` sets the entry on what exists; `-d -m` sets the default for
what will be created:

```console
$ sudo setfacl -R -m g:reports:rwX /srv/reports
$ sudo setfacl -R -d -m g:reports:rwX /srv/reports
$ getfacl -p /srv/reports
# file: /srv/reports
# owner: alice
# group: reports
# flags: -s-
user::rwx
group::rwx
group:reports:rwx
mask::rwx
other::---
default:user::rwx
default:group::rwx
default:group:reports:rwx
default:mask::rwx
default:other::---
$ sudo su - alice -c 'echo "second draft" > /srv/reports/q4-plan-v2.txt'
$ sudo getfacl -p /srv/reports/q4-plan-v2.txt
# file: /srv/reports/q4-plan-v2.txt
# owner: alice
# group: reports
user::rw-
group::rwx	#effective:rw-
group:reports:rwx	#effective:rw-
mask::rw-
other::---
$ sudo su - bob -c 'echo "bob was here" >> /srv/reports/q4-plan-v2.txt && tail -1 /srv/reports/q4-plan-v2.txt'
bob was here
$ sudo su - carol -c 'mkdir /srv/reports/carol-notes && ls -ld /srv/reports/carol-notes'
drwxrws---+ 2 carol reports 4096 Sep 14 09:57 /srv/reports/carol-notes
$ sudo su - dave -c 'ls /srv/reports'
ls: cannot open directory '/srv/reports': Permission denied
```

The `+` after the mode is `ls` saying "there is an ACL; the nine bits are not the whole story".
carol's new directory is group `reports`, setgid, and carries the defaults on. With the test files
removed, the grader passed all four checks.

The same result is available without ACLs: keep the setgid directories and give the team a umask that
keeps group write (`umask 007`) where their logins set it. That depends on every program the team uses
honouring a login umask — an editor started from a desktop session or a file copied in by a service
may not — which is the argument for the ACL.

## Common wrong turns

**`chmod -R 777`.** Everyone can do everything, including dave, including deleting the whole folder.
It also stops working tomorrow: new files are still created under `umask 077`.

**`usermod -G reports carol`.** Without `-a`, carol loses every other supplementary group she had —
`sudo`, perhaps. Always `-aG`, or `gpasswd -a carol reports`.

**Testing as yourself with `sudo`.** root is not subject to the permission check for reading and
writing, so everything "works". Test as the people concerned: `su - bob -c '…'`.

**Testing in a session that was already open.** Group membership is read when a process starts. A
shell opened before `usermod` still does not have the group; log in again, or use `su -`.

**Fixing the files and not the directories.** Without `x` on `drafts`, nobody reaches the files in
it however open they are. And without `w` on a directory, nobody can create or rename anything in it.

**`chmod -R g+x`** instead of `g+X`. Every report becomes executable. Harmless until someone runs one.

**Removing the hardening snippet.** It works in this folder, and it also makes every file every user
creates anywhere group-readable. The hardening had a purpose; the team folder needed an exception, not
the removal of the rule.

**Setting only access ACLs (`setfacl -m`) without defaults (`-d -m`).** Today's files work, tomorrow's
do not — the same trap as `chmod`, with more typing.

**`chmod g-w` on an ACL'd file to "tidy up".** It lowers the mask, and every named entry loses write
with it; `getfacl` shows `#effective:r--` and bob is locked out again.

**Copying files in with `cp -p` or `rsync -a` from elsewhere.** Preserving modes and groups preserves
the old private ones. Copy without preserving, or fix the group afterwards.

## Cheat sheet

```bash
# who, and in which groups
id alice ; id -nG alice              # groups by name
getent group reports                 # the group's members
sudo usermod -aG reports carol       # append (-a!) a supplementary group
sudo gpasswd -a carol reports        # the same; gpasswd -d removes
newgrp reports                       # a shell with the new group, without logging out

# what is there
ls -la /srv/reports ; stat -c '%A %U:%G %n' /srv/reports/*
namei -l /srv/reports/drafts/q4-outline.txt   # every directory on the path, with its bits
sudo su - bob -c 'test -w /srv/reports/budget.csv && echo writable'

# existing files
sudo chgrp -R reports /srv/reports
sudo chmod -R g+rwX,o-rwx /srv/reports        # X: execute only for dirs (and already-executables)
sudo find /srv/reports -type d -exec chmod g+s {} +   # setgid: new entries get the dir's group
chmod +t /srv/drop                            # sticky: only the owner may delete their file

# new files
umask                                # 0022 → 644/755, 0002 → 664/775, 0077 → 600/700
grep -rn umask /etc/profile /etc/profile.d /etc/login.defs ~/.profile ~/.bashrc
# default ACLs ignore the umask:
sudo setfacl -R  -m g:reports:rwX /srv/reports   # what exists
sudo setfacl -R -d -m g:reports:rwX /srv/reports # what will be created
getfacl -p /srv/reports              # mask:: caps named entries; #effective: shows the result
sudo setfacl -R -b /srv/reports      # remove all ACL entries
# ls -l shows '+' when a file has an ACL; the group bits it shows are the mask
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Nine letters and a refusal* (lab journal `hello`) — How the kernel picks a triad

Manual pages: `man 1 id`, `man 1 getent`, `man 1 chmod`, `man 5 login.defs`, `man 5 acl`.

## Review

1. alice owns `plan.txt`, mode `0460` (`r--rw----`), group `reports`, and alice is in `reports`. Can
   alice write to it?

   > No. The owner class is chosen first and only its bits count: `r--`. Being in the group does not
   > add the group's `rw-`. The kernel picks one class, it does not combine them.

2. `budget.csv` is `-rw-rw-rw-` but dave cannot read it. What could stop him?

   > A directory on the path. Reaching a file needs execute on every directory leading to it; with
   > `/srv/reports` at `drwxrws---`, dave, as "other", cannot enter it, so the file's own bits are
   > never consulted.

3. After `sudo usermod -aG reports carol`, carol's already-open terminal still cannot write to the
   folder. Why, and what are two ways to get the group without a reboot?

   > A process's groups are set when it starts; the shell that was open before the change keeps its
   > old list. A new login (`su - carol`, a new SSH session) reads the new membership; `newgrp reports`
   > starts a shell with it.

4. With `umask 077`, a program creates a file asking for mode `0666` in a directory that has no ACL.
   What mode does the file get, and which group?

   > `0600`: the umask removes group and other bits. The group is the creator's primary group — unless
   > the directory is setgid, in which case it is the directory's group.

5. What does the setgid bit do on a directory, and what does it not do?

   > New files and subdirectories get the directory's group instead of the creator's primary group,
   > and new subdirectories inherit setgid. It does not change any permission bits: under a `077`
   > umask the file has the right group and still no group access.

6. Why does a default ACL entry `group:reports:rwx` give group write to new files even under
   `umask 077`?

   > When the parent directory has a default ACL, the umask is not applied. The new file's ACL is
   > copied from the defaults and limited only by the mode the program requested (`0666` for a file),
   > so the named group gets `rw-`.

7. `getfacl` shows `group:reports:rwx #effective:r--`. What is limiting the group, and what command
   typically causes it?

   > The mask entry, which caps named users, named groups and the owning group; here it is `r--`.
   > A `chmod g-w` (or any chmod of the group bits) on a file with an ACL sets the mask.

8. Why is `chmod -R g+rwX` better than `chmod -R g+rwx` for a folder of documents?

   > Capital `X` adds execute only to directories, which need it to be entered, and to files that are
   > already executable for someone. Lowercase `x` marks every document as a program.
