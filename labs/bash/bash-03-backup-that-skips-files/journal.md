---
title: A file name is any byte but slash and NUL — a backup has to believe it
topics: [bash, linux-basics]
minutes: 30
---

`backup-docs` looks like the most boring script on the machine: find every file, make its directory
in the backup, copy it, count it, say how many. It ran every night for months and systemd marked
every run as a success. It had also been copying almost nothing, because the loop that reads the file
names takes them apart three different ways before `cp` ever sees them, and the one number it reports
is lost on the way out of a subshell.

The lesson is not "quote your variables", although you should. It is that a shell script which
handles file names has to treat a name as opaque data from the moment it is produced to the moment it
is used, and that every convenience in between — word splitting, `read`'s trimming, a pipeline — is
a transformation you did not ask for.

## What you should be able to do after this

- Say which bytes a Linux file name may contain, and why newline-separated lists of names are unsafe.
- Walk a tree with `find -print0` and `read -r -d ''`, and explain each part of that incantation.
- Recognise the three things that mangle a name in a naive loop: `read` without `-r`, `read` without
  `IFS=`, and an unquoted expansion.
- Explain why a variable changed inside `cmd | while …` is unchanged after the loop, and fix it with
  process substitution.
- Use `--` so that a name beginning with a dash is never taken for an option.
- Make a partial failure visible: a message on standard error and a non-zero exit status.
- Tell a oneshot service that succeeded from one that did its job.

## The mechanism

### What a file name can be

To the kernel a file name is a string of bytes. The only bytes it refuses are `/`, which separates
path components, and NUL, which ends a C string. Spaces, tabs, a leading dash, a backslash, quotes,
and a newline are all legal, and all of them turn up in real directories: documents saved by people,
files unpacked from archives made on other systems, uploads.

Any format that separates names with a byte a name can contain is therefore ambiguous. `find`'s
default output separates names with newlines. NUL is the one separator that cannot be ambiguous, which
is why `find -print0`, `xargs -0`, `sort -z` and `read -d ''` exist.

### What `read` does to a line

`while read f` is the loop everyone writes first. Without options, `read`:

1. treats a backslash as an escape character and removes it (`Q3\forecast.csv` becomes
   `Q3forecast.csv`) — `-r` turns that off;
2. strips leading and trailing characters that are in `IFS`, spaces and tabs by default —
   `IFS=` for that one command turns that off;
3. stops at a newline, so a name that contains one arrives as two "names" — only `-d ''` (read up to
   a NUL) fixes that, together with `find -print0`.

`while IFS= read -r -d '' f` is not ritual: each of the three parts undoes one of those.

### What an unquoted expansion does

After `read` hands over the name, `cp $f $dest/$rel` expands the variables **unquoted**. The shell
then splits each expansion into words at spaces, tabs and newlines, and expands any `*`, `?` or `[`
in the pieces as glob patterns. `Contract - ACME.pdf` becomes three arguments. With more than two
arguments, `cp` expects the last one to be a directory, so it fails with a message about a target it
cannot find. Double quotes — `"$f"` — keep an expansion as exactly one argument, whatever it holds.

### A name that looks like an option

A relative name such as `-rf.txt` is read by most commands as options. `cp -rf.txt copy.txt` does
not copy anything: `cp` parses `-r`, `-f`, then chokes on `.`. The end-of-options marker `--` tells
the command that everything after it is an operand. In this backup the names from `find` are
absolute (`/srv/docs/hr/-onboarding.md`), so the dash is harmless there — but the script builds
relative names too, and the habit costs two characters.

### Why the count is always zero

In `find … | while read f; do count=$((count + 1)); done`, each side of the pipe runs in its own
subshell: a separate process with a copy of the variables. The loop counts faithfully in its copy,
and that copy disappears when the loop ends. The parent shell's `count` was never touched, so
`echo "backed up $count files"` prints the value from before the loop.

Feeding the loop from a **process substitution** — `done < <(find … -print0)` — keeps the loop in
the current shell, so its variables survive. (Bash's `shopt -s lastpipe` does the same for the last
command of a pipeline in a non-interactive shell; the redirection form works everywhere and says what
it means.)

### Failures that nobody hears about

The loop ignores `cp`'s exit status, and the script's last command is an `echo`, which succeeds. A
script's exit status is the status of its last command unless it chooses otherwise, so a backup that
copied two files out of six exits 0, and a oneshot unit whose process exits 0 is `Result=success`.
To make a partial backup visible, count the failures, name each one on standard error, and end with
a status that says whether there were any.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, GNU bash 5.3.9, before any change.

Running the backup by hand shows everything that goes wrong, in order:

```console
$ sudo /usr/local/bin/backup-docs 2>&1; echo "exit status: $?"
cp: cannot stat '/srv/docs/finance/Q3forecast.csv': No such file or directory
cp: target 'board.txt': No such file or directory
cp: target 'agenda.txt': No such file or directory
cp: target 'ACME.pdf': No such file or directory
backed up 0 files
exit status: 0
```

Four errors, a count of zero, and a successful exit. The first error has already lost the backslash.
Looking at exactly what the loop receives — each name between brackets — shows where:

```console
$ find /srv/docs -type f | while read f; do printf '[%s]\n' "$f"; done
[/srv/docs/finance/Q3forecast.csv]
[/srv/docs/minutes/2026-09-01 board.txt]
[/srv/docs/minutes/  draft agenda.txt]
[/srv/docs/hr/-onboarding.md]
[/srv/docs/Contract - ACME.pdf]
[/srv/docs/notes/readme.txt]
```

`read` removed the backslash; the rest survived the read. The spaces are lost in the next step, the
unquoted expansion:

```console
$ f='/srv/docs/Contract - ACME.pdf'; printf '<%s> ' $f; echo
</srv/docs/Contract> <-> <ACME.pdf>
```

Three arguments for `cp`, which is why it complained about a target called `ACME.pdf`. Two files did
copy — `-onboarding.md` and `readme.txt` — and the script still reported zero. The subshell explains
that, and a two-line experiment proves it:

```console
$ count=0; printf 'a\nb\n' | while read x; do count=$((count+1)); done; echo "count=$count"
count=0
$ count=0; while read x; do count=$((count+1)); done < <(printf 'a\nb\n'); echo "count=$count"
count=2
```

A relative name with a leading dash fails differently, as an option:

```console
$ cd /tmp && printf x > '-rf.txt' && cp -rf.txt copy.txt 2>&1; echo "exit status: $?"; cp -- -rf.txt copy.txt && ls -- copy.txt
cp: invalid option -- '.'
Try 'cp --help' for more information.
exit status: 1
copy.txt
```

After rewriting the loop — NUL-separated names read by `IFS= read -r -d ''` in the current shell,
every expansion quoted, `--` before operands, failures counted and reported — the same run copies
all six documents and the timer's service reports a real success:

```console
$ sudo /usr/local/bin/backup-docs 2>&1; echo "exit status: $?"
backed up 6 files
exit status: 0
$ sudo find /var/backups/docs -type f
/var/backups/docs/2026-09-16/finance/Q3\forecast.csv
/var/backups/docs/2026-09-16/minutes/2026-09-01 board.txt
/var/backups/docs/2026-09-16/minutes/  draft agenda.txt
/var/backups/docs/2026-09-16/hr/-onboarding.md
/var/backups/docs/2026-09-16/Contract - ACME.pdf
/var/backups/docs/2026-09-16/notes/readme.txt
$ systemctl show backup-docs.service -p Result -p ExecMainStatus
Result=success
ExecMainStatus=0
```

The backslash, the two leading blanks and the spaces are all intact.

## Common wrong turns

- **Quoting the variables and stopping.** Quotes fix the spaces. The backslash is already gone by
  then, a newline still splits a name in two, and the count is still zero.
- **`for f in $(find …)`.** The command substitution is split into words exactly like an unquoted
  variable, so every name with a space breaks, and the whole list is built in memory first.
- **Setting `IFS=$'\n'`.** Handles spaces, not newlines in names, and changes word splitting for
  every other command in the script.
- **Making the count a file** (`echo >> /tmp/count`). It works around the subshell by adding shared
  state, a temporary file, and a new way to fail. Keep the loop in the current shell instead.
- **`set -e` as the error handling.** A failing `cp` inside `if` or `&&` does not stop the script,
  and one that does stop it leaves the rest of the documents uncopied. A backup wants every file it
  can get, and a list of the ones it could not.
- **Checking that the unit succeeded.** systemd knows the exit status and nothing else. Compare the
  backup with the source.

## Cheat sheet

```bash
# every file, whatever its name, read in the current shell
while IFS= read -r -d '' f; do
    rel=${f#"$DOCS_DIR"/}                         # quoted pattern: taken literally
    mkdir -p -- "$dest/$(dirname -- "$rel")"
    cp -p -- "$f" "$dest/$rel" || echo "could not copy $rel" >&2
done < <(find "$DOCS_DIR" -type f -print0)

printf '[%s]\n' "$name"            # see exactly what a variable holds
cmd | while …; done                # the loop's variables vanish afterwards
while …; done < <(cmd)             # they survive
cp -- "$f" "$dest"                  # names starting with - are operands
find "$dir" -type f -print0 | xargs -0 cmd      # NUL-separated all the way
[ "$failed" -eq 0 ]                # last command = the script's exit status
systemctl show unit -p Result -p ExecMainStatus
```

## Going deeper

- `man 1 bash`, *Word Splitting*, *Pathname Expansion* and the `read` builtin, for the three
  transformations this lab turns off.
- `man 1 find`, `-print0`, and `man 1 xargs`, `-0`, for passing names between programs.
- The monitoring journal, [a check is an exit status](../../journals/monitoring/index.html#a-check-is-an-exit-status),
  for why a script that exits 0 is a script that reports success.
- David A. Wheeler, *Filenames and Pathnames in Shell: How to do it Correctly*, for the long list of
  cases this lab only samples.

## Review

1. Which two bytes can never appear in a Linux file name component, and which one of them makes a
   safe separator for a list of names?

   > `/` and NUL. NUL is the safe separator, because `/` separates path components inside a name.

2. What does `read` without `-r` do to `Q3\forecast.csv`?

   > It treats the backslash as an escape and removes it, so the name becomes `Q3forecast.csv`.

3. Why does `count` stay 0 after `find … | while read f; do count=$((count+1)); done`?

   > The loop is part of a pipeline and runs in a subshell, which increments its own copy of the
   > variable; the parent shell's copy is untouched.

4. What does `cp $f dest/` do when `f` is `Contract - ACME.pdf`?

   > The unquoted expansion is split into three words, so `cp` receives three source operands and a
   > target, and tries to copy files called `Contract`, `-` and `ACME.pdf`.

5. A backup copied four files of six and printed an error for the other two. What exit status should
   it have, and why does it matter to systemd?

   > Non-zero. systemd's `Result=success` means only that the main process exited 0; a non-zero
   > status is how the failed unit, and any alert on it, finds out.

6. When is `--` needed before a file name?

   > When the name could begin with a dash, which is always possible for a relative name taken from
   > data; `--` ends option parsing so the name is an operand.
