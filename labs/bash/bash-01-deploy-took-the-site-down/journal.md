---
title: A deploy script is a transaction, or it is a hazard
topics: [bash, linux-basics]
minutes: 35
---

`deploy-site` is eight lines long and does what every deploy script does: make a directory, unpack a
release into it, point the live link at it, say so. On a good day it works, and it worked on every
good day for months. The incident did not happen on a good day. A release archive arrived cut short;
tar complained, the script paid no attention, replaced the live link with a directory holding one
empty file, and printed `deployed`. The site served nothing until someone looked.

It is tempting to call that a quoting bug, or an error-handling bug, and fix the one line. The better
reading is that the script was written as a **list of steps**, and a deploy is not a list of steps. It
is a **transaction**: either the new release is fully in place and live, or nothing visible has
changed. Everything in this lab — stopping at the first failure, checking the argument, quoting paths,
unique release directories, the atomic switch — is one of the things a shell script has to do by hand
to behave like a transaction, because the shell will not do any of it for you.

## What you should be able to do after this

- Read a shell script and say, for each command, what happens to the rest of the script when that
  command fails.
- Use `set -euo pipefail` and explicit checks together, and know which failures each one catches.
- Validate arguments before touching anything, and report misuse with a usage message on stderr and a
  distinct exit status.
- Quote every expansion of a path, and explain what an unquoted one does in a directory whose name
  contains a space.
- Give every release its own directory, and replace a live symlink atomically with `ln -sfn` and
  `mv -T`.
- Clean up what a failed run created, so a failure leaves the system as it found it.
- Test the failure paths of a script against throwaway directories instead of the live site.

## The mechanism

### The script, line by line

```bash
SITE_ROOT=${SITE_ROOT:-/srv/www}
tarball=$1
stamp=$(date +%Y%m%d%H%M%S)
release=$SITE_ROOT/releases/$stamp

mkdir -p $release
tar -xzf $tarball -C $release
rm -f $SITE_ROOT/current
ln -s $release $SITE_ROOT/current
echo "deployed $stamp"
```

Take each line and ask "and if this fails?":

1. `tarball=$1` — if no argument was given, `tarball` is empty and nothing complains.
2. `mkdir -p $release` — `-p` also means "and do not complain if it already exists", so a second
   deploy in the same second silently reuses the first one's directory.
3. `tar -xzf $tarball -C $release` — tar prints an error and exits non-zero. The script does not look.
4. `rm -f $SITE_ROOT/current` — the live link is gone. From here until the next line, the site has no
   content at all.
5. `ln -s $release $SITE_ROOT/current` — the link now points at whatever step 3 left behind.
6. `echo "deployed $stamp"` — always succeeds, so the script's exit status is always 0.

Every one of those is ordinary shell behaviour. A shell script does not stop when a command fails;
the exit status of a script is the exit status of its **last** command; and nothing is undone. That is
the whole story of the incident.

### Exit status is the only channel a caller has

Whoever runs a deploy — a person, a CI job, a configuration tool — learns whether it worked from the
exit status. `0` means success, anything else means failure, and by convention `2` means "you called
me wrong". Standard output is for data; diagnostics go to **standard error**, so that
`deploy-site x.tar.gz > /dev/null` can stay quiet on success and still show a failure.

The last-command rule is what makes a script lie. A script that ends with `echo` returns `echo`'s
status, and `echo` does not fail. The fix is not "exit 1 at the end"; it is making sure that no
failing command is followed by more steps.

### `set -euo pipefail`: a net with holes

```bash
set -euo pipefail
```

- `-e` exits when a command returns non-zero.
- `-u` treats an unset variable as an error, so `$1` without an argument stops the script instead of
  expanding to nothing.
- `-o pipefail` makes a pipeline fail if any stage fails, not only the last.

`-e` has well-known exemptions, and they matter in deploy scripts because deploy scripts are full of
conditions:

```bash
if tar -xzf "$tarball" -C "$release"; then …   # a condition: -e does not fire, by design
tar … || echo "warning"                         # the || handled it: no exit
f() { tar …; ln …; }; f || rollback            # -e is off inside f for the whole call
count=$(grep -c x file)                         # -e does fire: the assignment has cmd's status
local out=$(cmd)                                # but not here: the status is local's, which is 0
```

So `set -e` catches the commands you forgot to check, and explicit checks handle the commands whose
failure needs a specific response. In this script, tar's failure needs one — delete the half-unpacked
directory and leave the live link alone — so tar gets an explicit `if !`, and `-e` guards the rest.

### Arguments first

Validating input before doing anything is the cheapest transaction logic there is: nothing has
changed yet, so there is nothing to undo.

```bash
if [ "$#" -ne 1 ]; then
    echo "usage: deploy-site <release.tar.gz>" >&2
    exit 2
fi
tarball=$1
if [ ! -f "$tarball" ]; then
    echo "deploy-site: $tarball: no such file" >&2
    exit 1
fi
```

`$#` is the number of positional parameters. Note what the broken script did without this: with no
argument, `tar -xzf $tarball -C $release` became `tar -xzf -C /srv/www/releases/…`, and `-f` took
`-C` as the name of the archive. The error message — `-C: Cannot open` — is baffling unless you
know that the argument vanished.

### Word splitting, again, because paths have spaces

An unquoted `$release` is split at spaces, tabs and newlines, and each piece is then glob-expanded.
With `SITE_ROOT="/srv/web root"`:

```
mkdir -p $release   →   mkdir -p /srv/web root/releases/20260913…
                         two arguments: "/srv/web" and "root/releases/20260913…"
```

The second argument is a **relative** path, so it is created in the current directory — wherever the
script was started from. The same happens to `rm` and `ln`. A deploy script that splits paths does
not merely fail; it scatters directories and links across the filesystem. The rule is simple: quote
every expansion (`"$release"`, `"$SITE_ROOT/current"`), always.

`shellcheck` catches this class of bug mechanically, and every shell script worth keeping should pass
it. It does **not** catch missing error handling: the original script produces only quoting warnings,
and a script with perfect quoting can still end in `echo` and lie.

### Unique release directories

A timestamp with one-second resolution is not an identifier. Two deploys in the same second — a
retry, a pipeline that runs twice — get the same name, and `mkdir -p` happily reuses the directory, so
the second release is unpacked over the first. Files that exist only in the first release remain.

`mktemp -d` creates a directory that did not exist before, atomically, with a unique suffix:

```bash
release=$(mktemp -d "$SITE_ROOT/releases/$(date +%Y%m%d%H%M%S).XXXXXX")
chmod 755 "$release"     # mktemp creates it 0700
```

The timestamp prefix keeps the names roughly chronological; the random suffix makes them unique. The
suffix is random, so two releases from the same second do not sort in creation order — something to
remember if another tool picks "the newest" release by name. When that matters, use nanoseconds
(`date +%Y%m%d%H%M%S%N`) or a counter.

### Replacing a symlink atomically

The live link has to go from the old release to the new one with **no moment in between** when it is
missing or wrong. `rm` then `ln` has such a moment. `ln -sf new current` looks like it replaces the
link, but when `current` is a symlink to a directory, `ln` dereferences it and creates the new link
**inside** the old release directory instead. `-n` (`--no-dereference`) stops that:

```bash
ln -sfn "$release" "$SITE_ROOT/current"
```

`ln -sfn` still works by unlinking and re-creating, which is a very short gap but a gap. The
fully atomic way is to create the new link under a temporary name and rename it over the old one,
because `rename(2)` on the same filesystem replaces the destination in a single step:

```bash
ln -sfn "$release" "$SITE_ROOT/.current.new"
mv -Tf "$SITE_ROOT/.current.new" "$SITE_ROOT/current"
```

`mv -T` (`--no-target-directory`) matters for the same reason as `ln -n`: without it, `mv` would move
the new link *into* the directory `current` points to. Both flags are GNU extensions; on BSD and macOS
the equivalents are `ln -sfh` and `mv -h`.

### Cleaning up after a failure

A failed extraction leaves a directory that looks like a release. Leave it there and the next
"keep the five newest releases" job will count it, or someone will point `current` at it by hand. The
failure branch removes what the run created:

```bash
if ! tar -xzf "$tarball" -C "$release"; then
    rm -rf -- "$release"
    echo "deploy-site: cannot unpack $tarball; the live release is unchanged" >&2
    exit 1
fi
```

`--` ends option parsing, so a path that starts with `-` cannot be taken as an option. For scripts
with several resources to clean, a `trap` on `EXIT` (or `ERR`) does the same job in one place:

```bash
cleanup() { [ -n "${release:-}" ] && [ "${done:-}" != 1 ] && rm -rf -- "$release"; }
trap cleanup EXIT
```

### Testing failure paths without touching the site

`deploy-site` already reads `SITE_ROOT`, which makes it testable: point it at `/tmp`, build a fake
current release there, and try every outcome — a good archive, a truncated one, a missing one, no
argument, a root with spaces, two deploys in a row. `bash -x` prints every command after expansion,
which is where splitting and empty variables become visible. That is exactly how the grader tests
the script, and exactly how you should test it before you trust it.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. See what is live, then read the script.** Before anything runs, know what a good state looks like.

```console
$ ls -l /srv/www /srv/www/releases
/srv/www:
total 4
lrwxrwxrwx 1 root root   32 Sep 14 03:24 current -> /srv/www/releases/20260912083000
drwxr-xr-x 3 root root 4096 Sep 14 03:24 releases

/srv/www/releases:
total 4
drwxr-xr-x 2 root root 4096 Sep 14 03:24 20260912083000
$ cat /usr/local/bin/deploy-site
#!/bin/bash
# deploy-site <release.tar.gz> — unpack a release and make it the live site

SITE_ROOT=${SITE_ROOT:-/srv/www}
tarball=$1
stamp=$(date +%Y%m%d%H%M%S)
release=$SITE_ROOT/releases/$stamp

mkdir -p $release
tar -xzf $tarball -C $release
rm -f $SITE_ROOT/current
ln -s $release $SITE_ROOT/current
echo "deployed $stamp"
```

No `set -e`, no check after tar, no argument check, and `echo` last. The incident is already
explained; the rest is confirmation.

**2. Reproduce the truncated archive in a sandbox**, never on the live site. A fake web root in `/tmp`,
and the first 200 bytes of a real release:

```console
$ mkdir -p /tmp/t/www/releases/old && echo old > /tmp/t/www/releases/old/index.html && ln -sfn /tmp/t/www/releases/old /tmp/t/www/current
$ sudo head -c 200 /root/release-2026-09-13.tar.gz > /tmp/t/truncated.tar.gz; ls -l /tmp/t/truncated.tar.gz
-rw-rw-r-- 1 northelks northelks 200 Sep 14 03:25 /tmp/t/truncated.tar.gz
$ SITE_ROOT=/tmp/t/www bash -x /usr/local/bin/deploy-site /tmp/t/truncated.tar.gz; echo "exit=$?"
+ SITE_ROOT=/tmp/t/www
+ tarball=/tmp/t/truncated.tar.gz
++ date +%Y%m%d%H%M%S
+ stamp=20260914032509
+ release=/tmp/t/www/releases/20260914032509
+ mkdir -p /tmp/t/www/releases/20260914032509
+ tar -xzf /tmp/t/truncated.tar.gz -C /tmp/t/www/releases/20260914032509

gzip: stdin: unexpected end of file
tar: Unexpected EOF in archive
tar: Unexpected EOF in archive
tar: Error is not recoverable: exiting now
+ rm -f /tmp/t/www/current
+ ln -s /tmp/t/www/releases/20260914032509 /tmp/t/www/current
+ echo 'deployed 20260914032509'
deployed 20260914032509
exit=0
$ readlink /tmp/t/www/current; ls -la /tmp/t/www/current/
/tmp/t/www/releases/20260914032509
total 0
drwxrwxr-x 2 northelks northelks 60 Sep 14 03:25 .
drwxrwxr-x 4 northelks northelks 80 Sep 14 03:25 ..
-rw-r--r-- 1 northelks northelks  0 Sep 14 03:25 index.html
```

That is the incident, exactly: tar failed loudly, the script carried on, and `current` now points at
a release whose `index.html` is zero bytes — the part of the file tar managed to create before the
archive ran out.

**3. Call it with no argument.**

```console
$ SITE_ROOT=/tmp/t/www deploy-site; echo "exit=$?"; readlink /tmp/t/www/current
tar (child): -C: Cannot open: No such file or directory
tar (child): Error is not recoverable: exiting now
tar: Child returned status 2
tar: Error is not recoverable: exiting now
deployed 20260914032509
exit=0
/tmp/t/www/releases/20260914032509
```

`-C: Cannot open` is tar trying to open an archive called `-C`: the empty `$tarball` disappeared and
`-f` took the next word. The script reported success anyway.

**4. A web root with a space.** Started from `/tmp/t`, so any stray relative path lands somewhere
visible:

```console
$ mkdir -p "/tmp/t/web root/releases/old" && echo old > "/tmp/t/web root/releases/old/index.html" && ln -sfn "/tmp/t/web root/releases/old" "/tmp/t/web root/current"
$ sudo cp /root/release-2026-09-13.tar.gz /tmp/t/good.tar.gz && sudo chown "$(id -un)" /tmp/t/good.tar.gz
$ cd /tmp/t && SITE_ROOT="/tmp/t/web root" deploy-site /tmp/t/good.tar.gz; echo "exit=$?"; ls /tmp/t
tar: root/releases/20260914032509: Not found in archive
tar: Exiting with failure status due to previous errors
rm: cannot remove '/tmp/t/web': Is a directory
ln: target 'root/current': No such file or directory
deployed 20260914032509
exit=0
good.tar.gz
root
truncated.tar.gz
web
web root
www
```

Read the listing: `mkdir -p` made two directories, `/tmp/t/web` and a relative `root/…` in the
current directory. tar took `root/releases/…` as a member name to extract; `rm` tried to delete
`/tmp/t/web`; `ln` looked for a directory called `root/current`. Four commands, four different
misreadings of one path — and `deployed`, exit 0.

**5. Two deploys in the same second.**

```console
$ SITE_ROOT=/tmp/t/www deploy-site /tmp/t/good.tar.gz && SITE_ROOT=/tmp/t/www deploy-site /tmp/t/good.tar.gz; ls /tmp/t/www/releases
deployed 20260914032509
deployed 20260914032509
20260914032509
old
```

Two "deployed" lines, one directory. With two different archives, the second would have been unpacked
on top of the first.

**6. Learn how `ln` treats a link to a directory**, before writing the switch:

```console
$ mkdir -p /tmp/t/ln/a /tmp/t/ln/b && ln -s /tmp/t/ln/a /tmp/t/ln/current && ln -sf /tmp/t/ln/b /tmp/t/ln/current; ls -l /tmp/t/ln/current /tmp/t/ln/a
lrwxrwxrwx 1 northelks northelks 11 Sep 14 03:25 /tmp/t/ln/current -> /tmp/t/ln/a

/tmp/t/ln/a:
total 0
lrwxrwxrwx 1 northelks northelks 11 Sep 14 03:25 b -> /tmp/t/ln/b
$ ln -sfn /tmp/t/ln/b /tmp/t/ln/current; ls -l /tmp/t/ln/current
lrwxrwxrwx 1 northelks northelks 11 Sep 14 03:25 /tmp/t/ln/current -> /tmp/t/ln/b
```

`ln -sf` left `current` pointing at `a` and quietly created `a/b`. `ln -sfn` replaced the link itself.

**7. Rewrite the script.** Each change answers one of the failures above:

```bash
#!/bin/bash
# deploy-site <release.tar.gz> — unpack a release and make it the live site
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: deploy-site <release.tar.gz>" >&2
    exit 2
fi
tarball=$1
SITE_ROOT=${SITE_ROOT:-/srv/www}
if [ ! -f "$tarball" ]; then
    echo "deploy-site: $tarball: no such file" >&2
    exit 1
fi

mkdir -p "$SITE_ROOT/releases"
release=$(mktemp -d "$SITE_ROOT/releases/$(date +%Y%m%d%H%M%S).XXXXXX")
if ! tar -xzf "$tarball" -C "$release"; then
    rm -rf -- "$release"
    echo "deploy-site: cannot unpack $tarball; the live release is unchanged" >&2
    exit 1
fi
chmod 755 "$release"

ln -sfn "$release" "$SITE_ROOT/.current.new"
mv -Tf "$SITE_ROOT/.current.new" "$SITE_ROOT/current"
echo "deployed ${release##*/}"
```

It was written with `sudo tee /usr/local/bin/deploy-site > /dev/null <<'SCRIPT' … SCRIPT`; the quoted
delimiter keeps `$1` and `$#` from being expanded while the file is written.

```console
$ shellcheck /usr/local/bin/deploy-site && echo "shellcheck: clean"
shellcheck: clean
```

**8. Test every outcome again**, on a fresh sandbox:

```console
$ SITE_ROOT=/tmp/t/www deploy-site /tmp/t/truncated.tar.gz; echo "exit=$?"; readlink /tmp/t/www/current; ls /tmp/t/www/releases

gzip: stdin: unexpected end of file
tar: Unexpected EOF in archive
tar: Unexpected EOF in archive
tar: Error is not recoverable: exiting now
deploy-site: cannot unpack /tmp/t/truncated.tar.gz; the live release is unchanged
exit=1
/tmp/t/www/releases/old
old
$ SITE_ROOT=/tmp/t/www deploy-site; echo "exit=$?"
usage: deploy-site <release.tar.gz>
exit=2
$ SITE_ROOT=/tmp/t/www deploy-site /tmp/t/good.tar.gz && SITE_ROOT=/tmp/t/www deploy-site /tmp/t/good.tar.gz; ls /tmp/t/www/releases; readlink /tmp/t/www/current
deployed 20260914032510.KBlxi3
deployed 20260914032510.Ir3FNO
20260914032510.Ir3FNO
20260914032510.KBlxi3
old
/tmp/t/www/releases/20260914032510.Ir3FNO
$ SITE_ROOT="/tmp/t/web root" deploy-site /tmp/t/good.tar.gz; cat "/tmp/t/web root/current/index.html"
deployed 20260914032510.RNFOkK
<h1>Shop</h1>
<p>Release 2026-09-13</p>
```

The truncated archive changes nothing and exits 1; no argument exits 2 with a usage line; two quick
deploys make two directories, and `current` is the second. Notice the ordering in `ls`: `Ir3FNO` was created
second but sorts first, because the random suffix decides the order within a second.

**9. Grade.** `c` on the lab's screen ran the checks, rebooted, and ran them again: all four passed in
both passes, 100%.

## Common wrong turns

**Adding `exit 1` at the end, or `|| exit 1` after `echo`.** The script then fails every time, or never
— the problem is not the last line, it is the lines that run after a failure.

**`set -e` alone.** It does stop at a failing tar, but it leaves the half-unpacked release behind,
and it gives the user tar's message with no statement of what state the site is in. Worse, the moment
someone wraps the extraction in an `if` or a function called with `||`, `-e` stops applying. Use it as
a net under explicit checks, not instead of them.

**Checking tar with `$?` on the next line, after something else ran.** `tar …; echo "extracted";
if [ $? -ne 0 ]` tests `echo`. Test the command directly: `if ! tar …; then`.

**Quoting only the variables that "might" contain spaces.** Paths come from environment variables,
configuration files and other people's machines. Quote all of them; it costs nothing, and
`shellcheck` will stop reminding you.

**`ln -sf` to replace the link.** On a link to a directory it creates a link inside the old release
and leaves `current` unchanged, which looks like a deploy that "did not take".

**`rm -rf "$SITE_ROOT/releases/$stamp"` in the failure branch with the timestamp recomputed.** A
second call to `date` can return a different second. Remember the exact path the run created and delete
that — which is what keeping `$release` from `mktemp` gives you.

**Testing on `/srv/www`.** Every experiment in the walkthrough ran against `/tmp`. A deploy script
that has not been seen failing has not been tested, and the live site is the wrong place to watch it
fail.

**Making names unique and then sorting them by name.** A random suffix fixes collisions but breaks
strict chronological order within a second. If a cleanup job keeps "the newest N by name", either use
a sortable unique name (nanoseconds, a counter) or have that job sort by the timestamp prefix only.

## Cheat sheet

```bash
set -euo pipefail                        # stop on errors, unset variables, failed pipeline stages
[ "$#" -eq 1 ] || { echo "usage: …" >&2; exit 2; }      # argument count, usage on stderr
[ -f "$file" ] || { echo "…: no such file" >&2; exit 1; }
if ! cmd; then cleanup; exit 1; fi       # a failure that needs its own response
echo "message" >&2                       # diagnostics to stderr
"$var"  "$dir/$name"  "$(cmd)"  "$@"    # quote every expansion
dir=$(mktemp -d "/path/prefix.XXXXXX")  # a new, unique directory (mode 0700)
rm -rf -- "$dir"                         # -- : no option parsing after this
ln -sfn target link                      # replace a link, do not follow a link to a directory
ln -sfn target .link.new && mv -Tf .link.new link   # atomic switch (same filesystem)
readlink -f link                         # where a link finally points
trap 'cleanup' EXIT                      # run cleanup whenever the script exits
bash -x script args                      # trace each command after expansion
shellcheck script                        # static analysis: quoting, common traps
VAR=/tmp/sandbox script args; echo "exit=$?"   # test against a throwaway root
```

| Exit status | Conventional meaning |
|---|---|
| 0 | success |
| 1 | general failure |
| 2 | misuse: wrong arguments, usage error |
| 126 / 127 | found but not executable / command not found |
| 128 + n | killed by signal n (130 = Ctrl-C, 137 = SIGKILL) |

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Active, green, and not working* (topic journal `monitoring`) — A check is an exit status
- *Counting things, and the specification is the test* (lab journal `linux-04-write-the-report`) — Validating, and the three exit statuses

Manual pages: `man 1 bash`, `man 1 ln`, `man 1 mktemp`.

## Review

1. A script's last command is `echo "done"`. What is its exit status when the command before it failed?

   > 0 — a script's exit status is that of its last command, and `echo` succeeds. The earlier failure is lost unless something stopped the script or checked it.

2. Why did calling the old `deploy-site` with no argument produce the error `-C: Cannot open`?

   > The unquoted, empty `$tarball` vanished from the command line, so `tar -xzf $tarball -C dir` became `tar -xzf -C dir` and `-f` took `-C` as the archive's name.

3. Name two situations in which `set -e` does not stop a script after a failing command.

   > When the command is part of a condition (`if cmd`, `while cmd`, `cmd || …`, `cmd && …` except the last), and inside a function called in such a context; also the status of `local x=$(cmd)` is `local`'s, not the substitution's.

4. With `SITE_ROOT="/srv/web root"`, what does `mkdir -p $SITE_ROOT/releases/x` create?

   > Two paths: `/srv/web` and the relative `root/releases/x` inside the current directory, because the unquoted expansion is split at the space.

5. What does `ln -sf new current` do when `current` is already a symlink to a directory, and which flag fixes it?

   > It follows the link and creates `new`'s link inside the directory `current` points to, leaving `current` unchanged. `-n` (`--no-dereference`) makes `ln` replace the link itself.

6. Why is `ln -sfn new .current.new && mv -Tf .current.new current` better than `rm current && ln -s new current`?

   > `rename(2)` replaces `current` in a single step, so there is never a moment without a live link; `rm` then `ln` leaves a gap, and if `ln` fails the site has no link at all. `-T` keeps `mv` from moving the new link into the old directory.

7. Why does `mktemp -d` solve the two-deploys-in-one-second problem, and what new property must you keep in mind?

   > It creates a directory that did not exist before, with a unique random suffix, atomically — so concurrent or rapid runs never share a directory. The random suffix means names created in the same second no longer sort in creation order.

8. What should a failed extraction leave behind, and why does it matter to other tools?

   > Nothing: the half-unpacked directory should be removed. Otherwise it looks like a release — a cleanup job may count it as one of the newest, or someone may point `current` at it.
