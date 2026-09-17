---
title: Counting things, and the specification is the test
topics: [bash, linux-basics]
minutes: 45
---

This lab does not break a machine. It hands you a specification — eleven lines of it — and grades
your script against logs you have not seen. That is a different skill from repair, and it is the one
most of the small tools on a server are made of: read text, count something, sort it, print it, and
behave correctly when the input or the arguments are wrong.

The counting part is a four-command pipeline that has been the same since the 1970s. The interesting
parts are the details the specification is quietly testing: what "order by address as plain text"
means when a locale is involved, which single space, what exit status, which stream the error goes
to. Almost every way to get this wrong produces a script that looks right on the sample log in
`/srv/logs/access.log` and fails on the fourth edge case.

## What you should be able to do after this

- Build a frequency count from a stream of text with `sort | uniq -c`, and explain why the first
  `sort` is mandatory.
- Order by one field numerically and break ties on another as bytes, with `sort`'s key syntax.
- Say what `LC_ALL=C` changes and why a byte-order requirement needs it.
- Parse options with `getopts`, validate them, and know what `shift $((OPTIND - 1))` is for.
- Pick exit statuses by convention — 0, 1 for a runtime failure, 2 for misuse — and put messages on
  stderr.
- Recognise the two ways `set -e`/`pipefail` sabotage a correct pipeline that ends in `head`, or
  greps a file with no matches.
- Read a specification as a list of test cases, and run all of them before believing the script.

## The mechanism

### Counting: `sort | uniq -c`

`uniq` collapses **adjacent** identical lines. It does not know anything about the rest of the file,
which is why the input must be sorted first — and why `sort | uniq -c` is one idiom rather than two
commands:

```console
$ awk '{print $1}' access.log | sort | uniq -c
     16 198.51.100.2
     79 203.0.113.10
    136 203.0.113.4
```

`uniq -c` prefixes each group with its count, **right-aligned in a field of width 7**. That padding
is a formatting decision from 1973 and it will fail this lab's "a single space between them"
requirement, so it has to be normalised. Any of these does it:

```console
… | uniq -c | awk '{print $1, $2}'      # rebuild the line from its fields  ← clearest
… | uniq -c | sed 's/^ *//'             # strip the leading padding only
… | uniq -c | tr -s ' ' | sed 's/^ //'  # squeeze runs of spaces, then the leading one
```

`awk '{print $1, $2}'` is the one to reach for, because awk splits on runs of whitespace and rebuilds
the line with a single `OFS`, which is exactly the transformation asked for.

For the extraction step, `awk '{print $1}'` beats `cut -d' ' -f1` in general: `cut` treats each
delimiter as significant, so two consecutive spaces give you an empty field, while awk's default
splitting handles any run of spaces or tabs. Both work on a well-formed access log; only one keeps
working on a scruffy one.

There is also a one-command version, which is what you would write for a large file since it makes a
single pass and needs no intermediate sort:

```console
$ awk '!/^#/ && NF { c[$1]++ } END { for (ip in c) print c[ip], ip }' access.log
```

An awk associative array *is* a frequency table. The filter `!/^#/ && NF` is the whole
"ignore comments and blank lines" requirement: skip lines starting with `#`, and skip lines with no
fields. Either route is legitimate here; the pipeline is easier to build incrementally at a prompt,
and that matters more than the performance on a file this size.

### Ordering: `sort` keys, and why one `-r` is wrong

The specification wants two different orderings at once: count descending, and — for equal counts —
address ascending as bytes. `sort -rn` cannot express that, because a single `-r` reverses
*everything*, putting `10.0.0.9` before `10.0.0.10` when the counts tie. Keys are how you say it:

```console
$ … | LC_ALL=C sort -k1,1nr -k2,2
7 172.16.0.1
4 10.0.0.10
4 10.0.0.2
4 10.0.0.9
1 192.168.1.1
```

Read `-k1,1nr` as: **start at field 1, end at field 1** (that is what `1,1` means — without the
second number the key runs to the end of the line), **n**umeric, **r**eversed. Then `-k2,2` is a
second key: field 2, default ordering, ascending. Per-key modifiers are the point — `-n` after `-k`
applies to that key only, whereas a global `-rn` applies to all of them.

That is also the answer to a question people ask about ties: `sort` is not stable by default (`-s`
makes it so, and the final comparison of whole lines is what breaks ties otherwise), so *specify* the
tie-break rather than hoping input order survives.

### `LC_ALL=C`, and what "plain text" means

The specification says byte order, and gives the example `10.0.0.10` before `10.0.0.9`. That is what
you get comparing bytes: `1` (0x31) is less than `9` (0x39) at the fourth position of
`10.0.0.1…`. But `sort` obeys the locale, and locale collation has other ideas: glibc's `en_US.UTF-8`
ignores punctuation on its first pass and folds case, so it compares `10.2.0.1` as though it were
`10201` and `101.0.0.1` as `101001` — and puts them in the opposite order from bytes. Measured on
Ubuntu 26.04, whose `sort` is uutils 0.8.0, with the locale generated (GNU `sort` agrees):

```console
$ printf '10.2.0.1\n101.0.0.1\n' | LC_ALL=C sort             # 10.2.0.1 then 101.0.0.1  ('.' < '1')
$ printf '10.2.0.1\n101.0.0.1\n' | LC_ALL=en_US.UTF-8 sort   # 101.0.0.1 then 10.2.0.1  (dots ignored)
$ printf 'a\nB\n' | LC_ALL=C sort                            # B then a  (uppercase bytes are smaller)
$ printf 'a\nB\n' | LC_ALL=en_US.UTF-8 sort                  # a then B
```

Note that the specification's own example, `10.0.0.10` before `10.0.0.9`, comes out the same in both —
which is exactly why a locale bug survives testing against the example. The lab machine itself runs
with `LANG=C.UTF-8`, which also compares code points, so you will not see the difference there at all;
the script that forgot `LC_ALL=C` fails on the next machine, with the next log.

So `LC_ALL=C` in front of `sort` is not superstition; it is the difference between a script that
produces the specified output and one that produces whatever the machine's locale feels like. The
same applies to `grep`'s character ranges and to `awk`'s comparisons. Whenever a program's output is
being *compared* rather than read by a human, pin the locale.

(`LC_ALL=C sort` sets it for that one command only, which is what you want — it does not affect the
rest of the script, and it does not depend on the caller's environment.)

### Filtering out comments and blanks

```console
$ grep -v -e '^#' -e '^[[:space:]]*$' -- "$file"
```

Three details in one short command. `-e` twice supplies two patterns to one `grep` (so does `grep
-E '^#|^[[:space:]]*$'`). `^#` anchors at the start, which matters — plain `grep -v '#'` would drop
any line *containing* a hash, and an access log is full of URLs with fragments. `^[[:space:]]*$`
catches a line that is empty *or* only whitespace, which is what "empty line" means in practice.

And `--` ends the option list, so a file named `-n` is treated as a filename rather than a flag. It
costs two characters and it is the difference between a robust script and a surprise.

### Options: `getopts`

```bash
n=5
while getopts ":n:" opt; do
    case $opt in
        n) n=$OPTARG ;;
        :) echo "top-talkers: invalid count" >&2; exit 2 ;;   # -n with no argument
        *) echo "top-talkers: unknown option -$OPTARG" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
```

The optstring is a small language: a letter means a flag, `letter:` means it takes an argument, and a
**leading `:`** switches off getopts' own error messages so you can print your own — which you want,
because the specification dictates the wording. With the leading colon, a missing argument arrives as
`opt=":"` and an unknown option as `opt="?"`, with the offending letter in `$OPTARG` either way.

`$OPTIND` is the index of the next unparsed argument, so `shift $((OPTIND - 1))` discards everything
getopts consumed and leaves `"$1"` as the first real operand. Forgetting that line is the classic
`getopts` bug: the script then treats `-n` as its filename.

One behaviour to know rather than fight: `getopts` stops at the first non-option argument, so
`top-talkers file -n 3` leaves `-n 3` as operands. That is POSIX behaviour (GNU tools permute
arguments; the shell does not), and the specification's `top-talkers [-n N] FILE` puts options first
precisely because that is the portable order.

### Validating, and the three exit statuses

Accepting `-n` is not the same as accepting a count. The specification says a positive whole number,
and lists the rejections: `0`, `-3`, `abc`, `2.5`, and the empty string.

```bash
[[ $n =~ ^[1-9][0-9]*$ ]] || { echo "top-talkers: invalid count" >&2; exit 2; }
```

`[[ … =~ … ]]` is bash's regex match; the pattern is unquoted (quoting it would make it a literal
string), `^[1-9]` excludes `0` and anything starting with a sign, `[0-9]*$` allows more digits and
nothing else — so no decimal point, no letters, and the empty string fails because `[1-9]` must match
once.

Then the file, checked before use rather than by letting a later command fail:

```bash
file=${1:-}
[[ -n $file && -f $file && -r $file ]] || { echo "top-talkers: cannot read $file" >&2; exit 1; }
```

`-f` is "exists and is a regular file", `-r` is "readable by me". Both, because a directory is
readable and is not a log, and because a file you cannot read exists.

The statuses follow a convention that is worth using deliberately:

| status | meaning |
|---|---|
| `0` | success — including a correct run that printed nothing |
| `1` | the job could not be done: a missing file, a failed write |
| `2` | **misuse**: bad options or arguments. What bash's own builtins use |
| `126` / `127` | found but not executable / not found — the shell's, not yours |
| `128+N` | killed by signal N (`130` = SIGINT, `141` = SIGPIPE) |

And the stream matters as much as the number. Errors go to stderr (`>&2`) so that
`top-talkers big.log > report.txt` puts the report in the file and the complaint on the terminal. A
script that prints its errors to stdout corrupts its own output, which is why this lab checks that
stdout is *empty* on the failure paths.

### The two traps with `set -e` and `pipefail`

The careful defaults from the previous journal — `set -euo pipefail` — can break *this* script in two
ways. Both are worth understanding, because they are the most common reason a correct pipeline exits
non-zero, and the first one is intermittent.

**`head` closes the pipe.** `head -n 5` exits as soon as it has five lines, and if the writer upstream
is still writing, its next write gets `SIGPIPE`. That is normal, cooperative behaviour — it is how
`head` stops a long job early — but the upstream command's status becomes `141`, and `pipefail`
propagates it. With `-e` as well, the script exits 141 having printed exactly the right output.

Whether it happens depends on how much the writer has left to write. On the sample log `sort` emits
seven short lines, they fit in the pipe's buffer (64 KiB on Linux), `sort` has finished before `head`
exits, and nothing goes wrong. On a log with 200,000 distinct addresses it does — measured on the lab
machine, the `set -e` version of the script printed `1 10.0.0.0` and exited 141. A bug that passes
every test on small input and fails on the production log is the worst kind, which is why it is worth
designing out rather than waiting for.

**`grep` reports "no matches" as failure.** `grep -v` on a file containing only comments prints
nothing and exits `1`, by design: grep's status answers "did you match anything?". The specification
says an empty log must print nothing and **exit 0**, so a pipeline starting with `grep` plus
`pipefail` gives you exit 1 on a case the spec calls success.

Three ways out, and the choice is a real one:

```bash
set -uo pipefail        # keep -u, drop -e, and end the script with an explicit `exit 0`
pipeline || true        # explicitly ignore the pipeline's status
set +o pipefail         # inside the section with head, then back on
```

The first is what this script wants: `-u` still catches typos, the checks above are explicit `||
exit` lines rather than relying on `-e`, and a final `exit 0` states that a report with no rows is a
success. The general lesson: `set -e` is a good default for a script whose commands should all
succeed, and a bad one for a pipeline whose components signal information through their exit status.

## A failure, walked through

There is no failure to diagnose here — there is a specification to satisfy. So the walkthrough is the
method: **build the pipeline at the prompt, one stage at a time, looking at the output after each
addition.** Never write ten lines and then debug them.

**1. Look at the data before writing anything.**

```console
$ head -3 /srv/logs/access.log
# access log, rotated daily
203.0.113.4 - - [11/Sep/2026:10:00:00 +0000] "GET /api/items/0 HTTP/1.1" 200 2671

$ grep -c '' /srv/logs/access.log ; grep -c '^#' /srv/logs/access.log
406
1
$ grep -c '^[[:space:]]*$' /srv/logs/access.log
5
```

A comment line and five blanks — the third line of the file is already one of them — both mentioned
in the specification, and now confirmed present in the sample.

**2. Extract the field.**

```console
$ awk '{print $1}' /srv/logs/access.log | head -3
#
203.0.113.4

```

The comment came through as `#`, and the blank line as an empty line — both would be counted as
"clients". Filter first:

```console
$ grep -v -e '^#' -e '^[[:space:]]*$' -- /srv/logs/access.log | awk '{print $1}' | head -3
203.0.113.4
203.0.113.9
203.0.113.4
```

**3. Count.**

```console
$ grep -v -e '^#' -e '^[[:space:]]*$' -- /srv/logs/access.log \
    | awk '{print $1}' | LC_ALL=C sort | uniq -c
      8 192.0.2.77
     16 198.51.100.2
     79 203.0.113.10
     30 203.0.113.23
    136 203.0.113.4
     28 203.0.113.57
    103 203.0.113.9
```

The counts are right and the format is not: the padding is `uniq`'s, and the order is by address
rather than by count. **4. Normalise, then order.**

```console
$ … | uniq -c | awk '{print $1, $2}' | LC_ALL=C sort -k1,1nr -k2,2 | head -n 5
136 203.0.113.4
103 203.0.113.9
79 203.0.113.10
30 203.0.113.23
28 203.0.113.57
```

**5. Check the tie-break deliberately**, with input designed to tie, because the sample log has no
ties and this is the requirement most likely to be silently wrong:

```console
$ printf '%s\n' '4 10.0.0.9' '4 10.0.0.10' '7 172.16.0.1' '4 10.0.0.2' \
    | LC_ALL=C sort -k1,1nr -k2,2
7 172.16.0.1
4 10.0.0.10
4 10.0.0.2
4 10.0.0.9
```

`10.0.0.10` before `10.0.0.2` before `10.0.0.9` — byte order, as specified. Compare with the wrong
version, which is the whole reason to test this:

```console
$ printf '%s\n' '4 10.0.0.9' '4 10.0.0.10' '7 172.16.0.1' | sort -rn
7 172.16.0.1
4 10.0.0.9
4 10.0.0.10
```

**6. Wrap it in the script**, adding the option parsing, the validation and the statuses:

```bash
#!/bin/bash
# top-talkers [-n N] FILE — the N busiest client addresses in an access log.
set -uo pipefail

n=5
while getopts ":n:" opt; do
    case $opt in
        n) n=$OPTARG ;;
        :) echo "top-talkers: invalid count" >&2; exit 2 ;;
        *) echo "top-talkers: unknown option -$OPTARG" >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))

[[ $n =~ ^[1-9][0-9]*$ ]] || { echo "top-talkers: invalid count" >&2; exit 2; }
file=${1:-}
[[ -n $file && -f $file && -r $file ]] || { echo "top-talkers: cannot read $file" >&2; exit 1; }

grep -v -e '^#' -e '^[[:space:]]*$' -- "$file" \
    | awk '{print $1}' \
    | LC_ALL=C sort | uniq -c \
    | awk '{print $1, $2}' \
    | LC_ALL=C sort -k1,1nr -k2,2 \
    | head -n "$n"
exit 0
```

The `exit 0` at the end is not decoration: it is what makes "an empty log prints nothing and exits 0"
true, given that `grep` exits 1 when it filters everything away.

**7. Run every case in the specification.** There are seven, and the script is not finished until all
seven have been seen:

```console
$ install -m 755 top-talkers /usr/local/bin/top-talkers

$ top-talkers /srv/logs/access.log ; echo "exit=$?"          # default 5 rows
$ top-talkers -n 3 /srv/logs/access.log | wc -l              # 3
$ top-talkers -n 99 /srv/logs/access.log | wc -l             # 7 — fewer rows than asked for is fine

$ printf '# only a comment\n\n' > /tmp/empty.log
$ top-talkers /tmp/empty.log ; echo "exit=$?"                # no output, exit 0
exit=0

$ top-talkers /nope.log ; echo "exit=$?"
top-talkers: cannot read /nope.log
exit=1

$ for bad in 0 -3 abc 2.5 ''; do
>   top-talkers -n "$bad" /srv/logs/access.log >/dev/null ; echo "$bad -> $?"
> done
top-talkers: invalid count
0 -> 2
…
'' -> 2

$ top-talkers /srv/logs/access.log | cat -A | head -2        # exactly one space, no trailing junk
136 203.0.113.4$
103 203.0.113.9$
```

`cat -A` is the check nobody runs and everybody needs: it makes `$` the end of each line and shows
tabs as `^I`, so a trailing space or a tab instead of a space becomes visible. A specification that
says "a single space" is testing for exactly this.

**8. Check the stream discipline**, because the graders check that stdout is clean on failure:

```console
$ top-talkers -n 0 /srv/logs/access.log 2>/dev/null ; echo "stdout was empty: $?"
$ top-talkers -n 0 /srv/logs/access.log 2>&1 >/dev/null     # only stderr
top-talkers: invalid count
```

## Common wrong turns

**`uniq -c` without sorting first.** `uniq` only collapses *adjacent* duplicates, so unsorted input
gives one group per run and counts that look plausible and are wrong. The bug hides in a log where
requests from one address happen to arrive together.

**Leaving `uniq -c`'s padding in the output.** `      4 10.0.0.9` has seven leading spaces. The
specification says "a single space between them", and a grader comparing strings sees a different
line. `awk '{print $1, $2}'` rebuilds it correctly.

**`sort -rn` instead of two keys.** It reverses the tie-break as well as the count, so tied addresses
come out in descending byte order — the opposite of what was asked. `-k1,1nr -k2,2` states the two
orderings separately, which is the only way to have them differ.

**Omitting `LC_ALL=C`.** The script then produces different output on machines with different
locales: under `en_US.UTF-8`, `101.0.0.1` sorts before `10.2.0.1`, while the specification's own
`10.0.0.10`/`10.0.0.9` example happens to agree in both, and the lab image's `C.UTF-8` hides it
entirely. Any time output is compared rather
than read, pin the locale on the command that compares.

**`set -euo pipefail` with a pipeline ending in `head`.** When the upstream output is larger than the
pipe buffer, `head` exits early, upstream takes `SIGPIPE`, `pipefail` propagates 141 and `-e` exits —
after printing exactly the right answer. It passes on small logs, which is what makes it dangerous. Drop
`-e` for this script (keep `-u`), or append `|| true`, and end with an explicit `exit 0`.

**Forgetting that `grep` exits 1 when it matches nothing.** On a log of only comments the filter
removes everything, `grep` reports failure, and with `pipefail` the script exits 1 on a case the
specification calls success. The explicit `exit 0` is the fix.

**`grep -v '#'` without the anchor.** That drops every line containing a hash anywhere, including
ordinary requests for URLs with fragments. Anchor it: `^#`.

**Treating "empty line" as strictly empty.** A line with a single space is blank to a human and not to
`^$`. `^[[:space:]]*$` is the pattern.

**Forgetting `shift $((OPTIND - 1))`.** `getopts` consumes `-n 3` and leaves `$1` pointing at it, so
the script tries to read a file called `-n`. This produces the baffling "cannot read -n" and it is
the single most common `getopts` mistake.

**Accepting anything `getopts` hands you as a count.** `-n abc` parses fine as an option argument;
only your own validation rejects it. And the specification lists five rejections — including the empty
string, which `[1-9]` handles only because it requires at least one digit.

**Exiting 1 for a bad option, or 2 for a missing file.** The specification assigns them the other way
round (2 is misuse, 1 is a runtime failure), and this is a genuine convention rather than an
arbitrary choice: bash's own builtins use 2 for usage errors.

**Printing the error to stdout.** It corrupts the report, defeats `>report.txt`, and fails a check
that requires stdout to be empty on the failure paths. `>&2`.

**Printing a header, a total, or a trailing blank line.** The specification says the rows and nothing
else. `cat -A` shows what you actually emitted.

**Testing only against `/srv/logs/access.log`.** The sample log has no ties, no unreadable-file case
and no invalid option. The specification *is* the test list: seven cases, all of them run, before you
call it done.

## Cheat sheet

```bash
# counting
awk '{print $1}' file | sort | uniq -c            # frequency table (sort FIRST — uniq is adjacent)
uniq -c | awk '{print $1, $2}'                    # strip uniq's 7-wide padding
uniq -d / -u                                      # only duplicated / only unique lines
awk '!/^#/ && NF { c[$1]++ } END { for (k in c) print c[k], k }' file    # one pass, no pre-sort
grep -c ''  file                                  # count lines
grep -v -e '^#' -e '^[[:space:]]*$' -- file       # drop comments and blank/whitespace lines

# ordering
LC_ALL=C sort -k1,1nr -k2,2      # field 1 numeric descending, then field 2 as bytes ascending
#          │ │ ││    └─ second key: field 2 only, default (byte) order
#          │ │ │└─ r: reverse this key      -n numeric, -h human sizes, -V versions
#          │ └─┴─ from field 1 to field 1 (omit the end and the key runs to end of line)
sort -s                          # stable: preserve input order for equal keys
sort -t: -k3,3n /etc/passwd      # a different field separator
LC_ALL=C                         # byte order, reproducible anywhere  ← whenever output is compared

# options
while getopts ":n:v" opt; do case $opt in
    n) n=$OPTARG ;;                 # ":n:" — leading colon: handle errors yourself
    v) verbose=1 ;;
    :) echo "$0: -$OPTARG needs an argument" >&2; exit 2 ;;
    *) echo "$0: unknown option -$OPTARG"     >&2; exit 2 ;;
esac; done
shift $((OPTIND - 1))            # ← forget this and $1 is still an option
[[ $n =~ ^[1-9][0-9]*$ ]] || { echo "…" >&2; exit 2; }      # validate, unquoted pattern

# tests and statuses
[[ -f $f && -r $f ]]             # -f regular file, -d dir, -r/-w/-x access, -s non-empty
[[ -n $s ]] / [[ -z $s ]]        # non-empty / empty string
exit 0                           # success (including a correct empty report)
exit 1                           # could not do the job
exit 2                           # misuse: bad options or arguments
# 126 not executable, 127 not found, 128+N killed by signal N (141 = SIGPIPE)
echo "msg" >&2                   # errors on stderr, always

# set -e and pipelines
set -uo pipefail                 # -u without -e: for scripts whose pipelines end in head/grep
cmd | head -n 5 || true          # head closes the pipe → upstream gets SIGPIPE → 141
# grep exits 1 when it matches nothing — that is information, not an error

# checking your own output
cmd | cat -A                     # line ends as $, tabs as ^I — finds stray spaces
diff <(cmd) expected             # compare against a known-good file
cmd >/dev/null ; echo $?         # the status alone
cmd 2>&1 >/dev/null              # only stderr
bash -n script ; shellcheck script
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

Manual pages: `man 1 sort`, `man 1 uniq`, `man 7 locale`, `man 1 grep`, `man 1 bash`, `man 1 test`.

## Review

1. Why must `sort` come before `uniq -c`, and what does the output look like when it does not?

   > `uniq` only collapses *adjacent* identical lines, so unsorted input yields one group per run of
   > repeats: the same address appears several times with partial counts. It looks like a plausible
   > report, which is what makes it dangerous.

2. `sort -rn` and `sort -k1,1nr -k2,2` both put the biggest count first. What does the specification
   require that only the second one delivers?

   > A tie-break in the *opposite* direction: counts descending but equal counts ordered by address
   > ascending. A single global `-r` reverses every comparison, so tied addresses come out in
   > descending byte order. Per-key modifiers are the only way to have two orderings in one sort.

3. What does `LC_ALL=C` change, and why does a requirement phrased as "plain text, byte order" need
   it?

   > It selects the C locale, where comparison is byte-by-byte, instead of the locale's collation
   > rules — glibc's `en_US.UTF-8` ignores punctuation on the first pass and folds case. Without it,
   > `101.0.0.1` sorts before `10.2.0.1`, and the output differs between machines.

4. A pipeline ending in `head -n 5` produces exactly the right output and the script exits 141 under
   `set -euo pipefail` — but only on large logs. Explain the mechanism and give two fixes.

   > `head` exits after five lines and closes the pipe; if the upstream process is still writing, its
   > next write kills it with `SIGPIPE`, giving status 141 (128+13). Small output fits in the pipe
   > buffer and is written before `head` exits, so the failure appears only with large input. `pipefail` propagates that and `-e` exits on it.
   > Either drop `-e` (keeping `-u`) and end with an explicit `exit 0`, or append `|| true` to the
   > pipeline.

5. Why does a log containing only comments make a `grep`-based pipeline exit 1, and what does the
   specification say should happen?

   > `grep` uses its exit status to report whether anything matched: filtering everything away is
   > "no matches", status 1. The specification calls an empty report a success, so the script must
   > end with an explicit `exit 0` (or otherwise ignore that status).

6. What is `shift $((OPTIND - 1))` for, and what is the symptom of omitting it?

   > `$OPTIND` is the index of the next unparsed argument, so the shift discards the options
   > `getopts` consumed and leaves `"$1"` as the first operand. Omit it and `$1` is still `-n`, so
   > the script reports that it cannot read a file called `-n`.

7. The specification assigns status 2 to a bad `-n` and status 1 to an unreadable file. What is the
   convention behind that, and why does the stream the message goes to matter just as much?

   > 2 is the conventional status for *misuse* — bad options or arguments, as bash's own builtins
   > use — while 1 means the job itself could not be done. The message belongs on stderr so that
   > redirecting stdout to a file keeps the report clean and still shows the complaint; a script that
   > writes errors to stdout corrupts its own output.

8. Your script prints the right rows and a grader rejects the output. Which command shows you what a
   string comparison sees?

   > `cmd | cat -A`: it marks the end of each line with `$` and renders tabs as `^I`, exposing a
   > trailing space, a tab used where a space was specified, or `uniq -c`'s leading padding — the
   > invisible differences that a "single space between them" requirement is testing.
