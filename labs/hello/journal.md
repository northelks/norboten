---
title: Nine letters and a refusal
topics: [linux-basics, users-permissions]
minutes: 20
---

The first lab is five minutes long and has two tasks: make a file readable, and write a word into
another file. It is small on purpose. It is also, in miniature, every lab that follows: something is
refused, the system will tell you exactly why if you ask it the right way, and the fix is one command
that has to still be true after a reboot.

It is worth doing slowly, because the ten characters at the start of `ls -l` are read in every
journal after this one, and because the second task hides the most common beginner trap on a Unix
system — a `sudo` that does not apply to the part of the command you think it does.

## What you should be able to do after this

- Read the permission string in `ls -l` and say who may do what with a file.
- Explain how the kernel decides which of the three permission groups applies to you, and why it stops
  at the first match.
- Change permissions with `chmod`, in both symbolic and octal form, choosing the smallest change that
  meets the requirement.
- Say what `sudo` elevates and what it does not — in particular, redirections.
- Write a file containing exactly one word, and check that it contains nothing else.
- Explain why a fix made with `chmod` survives a reboot.

## The mechanism

### Ten characters

```console
$ ls -l /srv/hello/message.txt
-rw------- 1 root root 168 Sep 12 09:02 /srv/hello/message.txt
```

The first column is a type and three triads:

```
 -    rw-    ---    ---
 │    │      │      └─ others: everyone who is neither the owner nor in the group
 │    │      └─ group: members of the file's group (here "root")
 │    └─ owner: the user named in the third column (here "root")
 └─ type: - regular file, d directory, l symlink
```

Within a triad, `r` is read, `w` is write, `x` is execute, and `-` means that permission is absent. So
`rw-------` says: root may read and write this file, and nobody else may do anything with it. That is
the whole explanation for the refusal:

```console
$ cat /srv/hello/message.txt
cat: /srv/hello/message.txt: Permission denied
```

### How the kernel picks a triad

When you open a file, the kernel does not add up permissions. It picks **exactly one** triad and
checks only that one:

1. If you are the file's **owner**, the owner triad applies — and the check ends there.
2. Otherwise, if you are in the file's **group**, the group triad applies — and the check ends there.
3. Otherwise, the **others** triad applies.

(Root skips the check for reading and writing entirely, which is why `sudo` works.)

The "first match wins" rule has a surprising consequence worth knowing early: a file with mode
`---r--r--` cannot be read by its own owner, even though everybody else can read it. The owner matched
step 1, the owner triad says `---`, and the kernel never looks further. It is rare in practice and it is
a good test of whether the rule has sunk in.

To open a file, you also need to reach it: every directory on the path needs `x` (traverse) for
whichever triad applies to you. `/srv/hello` is `drwxr-xr-x`, so others can pass through it — the
directory is not the problem here, the file is.

### Changing it with `chmod`

The requirement is "readable by every user on the system". That is the others triad, and it needs `r`.
The smallest change that does it:

```console
$ sudo chmod o+r /srv/hello/message.txt
$ ls -l /srv/hello/message.txt
-rw----r-- 1 root root 168 Sep 12 09:02 /srv/hello/message.txt
```

Symbolic mode reads as *who*, *operation*, *what*: `u`/`g`/`o`/`a` (user, group, others, all), then `+`
to add, `-` to remove or `=` to set exactly, then the letters. `o+r` adds read for others and leaves
every other bit alone, which is why it is the right shape for "add one permission".

Octal mode sets all nine bits at once, one digit per triad, with `r=4`, `w=2`, `x=1` added together:

```
rw-  r--  r--
4+2  4    4     →  chmod 644
```

`chmod 644` is also a correct answer here, and it is what most people would type. The difference is
that octal *replaces* the whole mode — useful when you know exactly what you want, careless when you do
not know what was there before. On a file you have never looked at, symbolic mode is the safer habit.

The answer that is not correct, and is still the most typed permission command on the internet, is
`chmod 777`. It makes the file readable by everyone, and also writable and executable by everyone. The
requirement said *read*.

You need `sudo` for this, because only a file's owner (or root) may change its mode — the permission to
change permissions is not one of the nine bits, it belongs to ownership.

### What `sudo` covers, and what it does not

Now read the message and write the reply (the word is chosen per session, so yours will differ). The
obvious command works:

```console
$ tail -1 /srv/hello/message.txt
The secret word is: inode
$ echo inode > ~/reply.txt
```

The instinctive command *before* the `chmod` — while the file was still unreadable — is where the trap
lives:

```console
$ sudo cat /srv/hello/message.txt > ~/reply.txt       # works, but look at what ran as root
$ sudo echo inode > /root/reply.txt
-bash: /root/reply.txt: Permission denied
```

`sudo` runs *the command* as root. The `>` redirection is not part of the command — it is performed by
**your shell, as you, before `sudo` even starts**. So `sudo cat … > ~/reply.txt` reads the file as root
and writes the output as you (which is why that one happens to work), and `sudo echo … > /root/…` fails
because you, not root, are trying to open `/root/reply.txt`.

The two idioms for "write this file as root":

```console
$ echo inode | sudo tee /some/root/file >/dev/null   # tee opens the file, and tee runs as root
$ sudo sh -c 'echo inode > /some/root/file'          # the redirection happens inside root's shell
```

For this lab you want the reverse: `reply.txt` lives in *your* home, so it should belong to *you*.
Writing it with `sudo tee` would create a root-owned file in your home directory, which works today and
confuses you next week when you cannot edit it.

### "Alone"

The briefing says the word, alone. Check what you actually wrote, rather than what you think you
wrote:

```console
$ cat -A ~/reply.txt
inode$
```

`cat -A` shows the end of each line as `$` and makes tabs and other invisible characters visible. One
word, one newline: exactly right — `echo` adds a newline, and a line ending is not "extra" to anyone
reading a text file. What would be wrong is visible immediately: `The secret word is: inode$` (the
whole line), ` inode$` (a stray space), `inode^M$` (a Windows line ending from a pasted editor).

Cutting the word out of the line mechanically avoids all three:

```console
$ sed -n 's/^The secret word is: //p' /srv/hello/message.txt
inode
$ awk -F': ' '/secret word/ {print $2}' /srv/hello/message.txt
inode
```

`sed -n` prints nothing by default, `s/…//p` substitutes the prefix away and prints only lines where it
matched. `awk -F': '` splits each line at `": "` and prints the second field of the matching line.
Either becomes `… > ~/reply.txt`.

### Why the reboot does not undo any of this

Checking a lab (`c`) grades the machine, reboots it, and grades it again, and a check counts only if it
passed both times. Here both fixes survive trivially: a file's mode is stored in its **inode** on disk,
and `reply.txt` is a file on disk. Nothing about either lives in memory.

That will not stay true. In later labs the tempting fix is often one that changes the *running* system
and not its configuration — a service started but not enabled, an address added with `ip` rather than
NetworkManager, a firewall rule without `--permanent`. The reboot is how Norboten tells those apart, and
it is the same test a real server applies to you the next time it restarts at three in the morning.

## A failure, walked through

**1. Be refused, and read the refusal.**

```console
$ cat /srv/hello/message.txt
cat: /srv/hello/message.txt: Permission denied
```

"Permission denied" on an open is the kernel's answer, not the program's. So look at the permissions.

**2. Ask who owns it and what each group may do.**

```console
$ ls -l /srv/hello/message.txt
-rw------- 1 root root 168 Sep 12 09:02 /srv/hello/message.txt
$ id
uid=501(learner) gid=1000(learner) groups=1000(learner)
```

You are not `root` (step 1 of the rule does not match) and not in the group `root` (step 2 does not
match), so the others triad applies: `---`. Nothing permitted.

**3. Check the path, so you do not fix the wrong thing.**

```console
$ ls -ld /srv /srv/hello
drwxr-xr-x 3 root root 4096 Sep 12 09:02 /srv
drwxr-xr-x 2 root root 4096 Sep 12 09:02 /srv/hello
```

Both directories grant `x` to others. The file is the only obstacle.

**4. Make the smallest change that meets the requirement.**

```console
$ sudo chmod o+r /srv/hello/message.txt
$ ls -l /srv/hello/message.txt
-rw----r-- 1 root root 168 Sep 12 09:02 /srv/hello/message.txt
$ cat /srv/hello/message.txt
If you can read this, you found your way past a permission check.
Every lab here works like that: something is refused, and you find out why.
The secret word is: inode
```

"Every user", not "you": test it as someone other than yourself, too.

```console
$ sudo -u nobody cat /srv/hello/message.txt | tail -1
The secret word is: inode
```

**5. Write the reply as yourself, and inspect it.**

```console
$ sed -n 's/^The secret word is: //p' /srv/hello/message.txt > ~/reply.txt
$ cat -A ~/reply.txt
inode$
$ ls -l ~/reply.txt
-rw-rw-r-- 1 learner learner 6 Sep 12 09:05 /home/learner.guest/reply.txt
```

Owned by you, one word, one newline.

**6. Grade it.** Back in norboten, press **`c`** on the lab's screen: the checks table fills in
before the reboot and again after it.

## Common wrong turns

**`chmod 777`.** It makes the file readable by everyone and also writable and executable by everyone.
Change the one permission you were asked to change: `o+r`.

**`chmod u+r`.** Root already has read; the owner triad was never the problem. Read `ls -l` and
identify which triad applies to the people who are refused.

**Changing the file's owner to yourself.** `sudo chown learner /srv/hello/message.txt` lets *you* read
it and nobody else — the requirement was every user. Ownership decides which triad applies; it does not
widen access.

**Reading it with `sudo cat` and moving on.** You now know the word, and the message is still unreadable
for everyone else. Half the task is the machine's state, not your knowledge.

**`sudo echo word > somewhere`.** The redirection runs as you, not as root. Use `sudo tee` when the
destination needs root, and nothing when it does not.

**Writing `reply.txt` with `sudo tee`.** It works and leaves a root-owned file in your home directory,
which you then cannot edit without `sudo`. Files in your home should belong to you.

**Putting the whole line in the reply.** "The secret word is: inode" is not "inode". `cat -A` shows
exactly what is in the file.

**Writing `reply.txt` somewhere other than your home.** `~` is your home directory; `./reply.txt` is the
directory you happen to be in. `echo $HOME` if in doubt.

## Cheat sheet

```console
# reading permissions
ls -l FILE                   # type + owner/group/others triads, owner, group
ls -ld DIR                   # the directory itself, not its contents
stat -c '%A %a %U:%G' FILE   # symbolic mode, octal mode, owner:group
id                           # who you are, and your groups

# the rule: owner triad if you own it; else group triad if you are in the group; else others.
# first match wins — the kernel never combines triads. Root bypasses read/write checks.

# changing permissions
chmod o+r FILE               # add read for others (u g o a;  + - =;  r w x)
chmod go-w FILE              # remove write for group and others
chmod 644 FILE               # rw-r--r--   (r=4 w=2 x=1, one digit per triad; replaces all nine bits)
chmod 600 FILE               # rw-------
chmod 755 DIR                # rwxr-xr-x   (x on a directory = may pass through it)
sudo -u nobody cat FILE      # test as someone who is not you

# sudo and redirection
sudo cmd > file              # cmd runs as root; > is opened by YOUR shell, as you
echo x | sudo tee file       # write a file as root
sudo sh -c 'echo x > file'   # …or put the redirection inside root's shell

# getting exactly the right text
tail -1 FILE                                  # the last line
sed -n 's/^The secret word is: //p' FILE      # just the part after the prefix
awk -F': ' '/secret word/ {print $2}' FILE
cat -A FILE                                   # $ = end of line, ^I = tab, ^M = CR

# Norboten, on a lab's screen
c                            # grade, reboot, grade again
h                            # the next hint for the selected check
r                            # back to the broken state
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

Manual pages: `man 1 ls`, `man 1 chmod`, `man 1 cat`.

## Review

1. Decode `-rw-r-----  root  adm`. Who may read the file, and who may write it?

   > The owner, root, may read and write; members of the group `adm` may read; everyone else may do
   > nothing.

2. A file is `----r--r--` and owned by you. Can you read it? Explain using the order in which the kernel
   chooses a triad.

   > No. You are the owner, so the owner triad applies and the check stops there — and it grants nothing.
   > The kernel never falls through to the group or others triads, even though they allow reading.

3. `chmod o+r file` and `chmod 644 file` both made the message readable. When would they produce
   different results?

   > Whenever the file had other bits set. `o+r` adds one bit and leaves the rest alone; `644` replaces all
   > nine, so it would, for example, remove an execute bit or a group write permission that was there
   > before.

4. Why does `sudo echo hello > /root/note` fail with *Permission denied*?

   > The redirection is performed by your own shell, as you, before `sudo` runs; only `echo` runs as
   > root. You cannot open `/root/note`. Use `echo hello | sudo tee /root/note` or
   > `sudo sh -c 'echo hello > /root/note'`.

5. How do you check that a file contains a single word and nothing else — no stray spaces, no Windows
   line ending?

   > `cat -A file`: it marks line ends with `$` and shows tabs as `^I` and carriage returns as `^M`, so
   > `inode$` is right and ` inode$` or `inode^M$` are visibly wrong.

6. Why does a `chmod` survive the reboot that checking a lab (`c`) performs, and what kind of fix in
   later labs will not?

   > A file's mode is stored in its inode on disk. Fixes that change only the running system do not
   > survive — a service started but not enabled, an address added with `ip`, a firewall rule without
   > `--permanent`, a setting typed into a shell rather than written to a file.
