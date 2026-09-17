---
title: Nothing matched is an answer, not a failure
topics: [bash, logging-journald]
minutes: 30
---

`set -euo pipefail` is good advice, and the review that asked for it was right. What the review did
not say is that `set -e` acts on a single signal — a non-zero exit status — and that several
perfectly ordinary commands use a non-zero status to mean "I looked, and there was nothing", not "I
failed". `grep` is the famous one. Add `pipefail`, and a night with no server errors becomes a failed
unit and an emptied report.

The second bug in the same one-line pipeline is quieter and older than the review: `uniq -c` counts
runs of *adjacent* equal lines, so an endpoint that appears in three separate places in the log is
reported three times with three small counts. Both come from the same habit — reading a pipeline as
a sentence rather than as five programs with their own rules.

## What you should be able to do after this

- Name grep's three exit statuses and say what each one means.
- Explain what `set -e` and `pipefail` do to a pipeline whose first command finds nothing.
- Tell an empty result from an error, and write a script that treats them differently.
- Count occurrences correctly with `sort | uniq -c`, and sort the result by count and then by name.
- Keep a report intact when a run fails, instead of truncating it before the work starts.
- Read a failed oneshot unit: `systemctl show`, `journalctl -u`.

## The mechanism

### Three exit statuses, not two

`grep` exits 0 when at least one line matched, **1 when no line matched**, and 2 when something
actually went wrong — a file it cannot open, a bad pattern. The distinction is deliberate and
documented, and it is what makes `if grep -q …` work. `awk`, by contrast, exits 0 whether or not any
line matched its pattern: "no matching lines" is not an error condition for it at all.

Other commands share grep's convention: `diff` (1 = differences found), `cmp`, `test`/`[`. None of
them is broken; they answer a question, and the answer is in the status.

### What `set -e` and `pipefail` make of that

`set -e` ends the script when a command exits non-zero — outside the places where a status is being
tested (`if`, `while`, `&&`, `||`, a `!` negation). A pipeline's status is normally the status of its
**last** command, so `grep … | awk … | sort` is 0 even when grep found nothing. `set -o pipefail`
changes that: the pipeline's status becomes the last non-zero status in it. Together, the two turn
"nothing matched" into "stop the script".

The redirection has already happened by then. In `grep … | … > "$REPORT"` the shell opens and
truncates the report before the pipeline runs, so a quiet night leaves a zero-byte report *and* a
failed unit.

### Counting with `uniq`

`uniq` compares each line with the one before it only. It is a streaming tool with a one-line memory,
which is why it is fast and why it needs sorted input: `sort | uniq -c` is the idiom, and `sort -u`
is the shorthand when the counts are not needed.

Sorting the counts afterwards needs care too. `sort -rn` on `<count> <path>` lines sorts by the whole
line numerically, which is fine for the counts but leaves equal counts in whatever order they arrived.
`sort -k1,1nr -k2,2` says exactly what is meant: first key numeric and reversed, second key the path,
ascending — a stable, reproducible report.

### Not a failure, and not silence either

The fix is not `|| true` on the end of the pipeline. That makes every failure invisible, including
the log that has been rotated away or a disk that is full — and this lab's third check exists to
catch exactly that shortcut. Separate the two questions:

- *Can I read the input?* Test it, and fail loudly if not.
- *Did the input contain anything?* Let the tool answer; zero is a number.

Using `awk` for the selection does both at once: it exits 0 on a quiet log, and non-zero when it
cannot open the file, so the pipeline's status keeps its meaning under `pipefail`.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, GNU bash 5.3.9, before any change.

The unit's run, on a night with no server errors in the log:

```console
$ sudo systemctl start errors-report.service; systemctl show errors-report.service -p Result -p ExecMainStatus; sudo journalctl -u errors-report.service -b --no-pager -o cat | tail -3
Result=exit-code
ExecMainStatus=1
errors-report.service: Main process exited, code=exited, status=1/FAILURE
errors-report.service: Failed with result 'exit-code'.
Failed to start errors-report.service - Server errors per endpoint, for the morning stand-up.
```

The report it left is empty, although the log has six lines:

```console
$ wc -l /var/log/shop/access.log; cat /var/lib/shop/errors.txt; echo "[end of report]"
6 /var/log/shop/access.log
[end of report]
```

The status of the `grep` in that pipeline is the whole story:

```console
$ grep '" 5[0-9][0-9] ' /var/log/shop/access.log; echo "grep status: $?"
grep status: 1
```

And that status, under `set -e` with `pipefail`, ends the script — even though the rest of the
pipeline ran happily:

```console
$ bash -c 'set -euo pipefail; grep missing /etc/hostname | wc -l; echo "reached the next line"'; echo "script status: $?"
0
script status: 1
```

`wc -l` printed its `0`; the line after it never ran. The counting bug is easy to see beside its
fix — the same five lines, with and without a `sort` in front of `uniq`:

```console
$ printf '/cart\n/pay\n/cart\n/cart\n/pay\n' | uniq -c
      1 /cart
      1 /pay
      2 /cart
      1 /pay
$ printf '/cart\n/pay\n/cart\n/cart\n/pay\n' | sort | uniq -c | sort -k1,1nr -k2,2
      3 /cart
      2 /pay
```

After the fix — the log checked for readability, `awk` in place of `grep` for the selection, `sort`
before `uniq -c`, a second `awk` for the total, and the report written to a temporary file and
renamed — a bad night, a quiet night and a missing log all behave:

```console
$ sudo /usr/local/bin/errors-report; echo "status: $?"; cat /var/lib/shop/errors.txt
status: 0
1 /cart
total 1
$ sudo sh -c 'grep -v 502 /var/log/shop/access.log > /tmp/quiet.log'; sudo env LOG=/tmp/quiet.log REPORT=/tmp/quiet.txt /usr/local/bin/errors-report; echo "status: $?"; cat /tmp/quiet.txt
status: 0
total 0
$ sudo env LOG=/nonexistent REPORT=/tmp/quiet.txt /usr/local/bin/errors-report; echo "status: $?"; cat /tmp/quiet.txt
errors-report: cannot read /nonexistent
status: 1
total 0
```

The quiet night is `total 0` with status 0; the missing log is a message on standard error, status 1,
and the previous report untouched.

## Common wrong turns

- **`grep … || true`.** The quiet night passes, and so does every real failure: an unreadable log, a
  rotated log, a typo in the path. The lab's third check fails anyone who does this.
- **`set +e` around the pipeline.** Same objection, with more lines.
- **`grep -c` for the total.** It also exits 1 when the count is zero, so the "total" line brings the
  problem back on the last line of the script.
- **Keeping `uniq -c` and sorting afterwards.** Sorting the wrong counts does not make them right;
  the input to `uniq` is what has to be sorted.
- **`sort -rn` alone.** It works on the numbers but leaves equal counts in arbitrary order, so the
  report changes between runs for no reason.
- **Muting the alert.** A unit that fails every quiet night trains everyone to ignore it, which is
  how the counting bug survived for weeks.

## Cheat sheet

```bash
grep pattern file                  # 0 matched · 1 no match · 2 error
awk '/pattern/ { … }' file         # 0 whether or not anything matched; non-zero if it cannot read
set -o pipefail                    # a pipeline's status = its last non-zero status
if grep -q pattern file; then …    # a status being tested does not trigger set -e

sort | uniq -c | sort -k1,1nr -k2,2    # count occurrences, most frequent first, ties by name
awk '{ print $1, $2; n += $1 } END { print "total", n + 0 }'

[ -r "$LOG" ] || { echo "cannot read $LOG" >&2; exit 1; }
tmp=$(mktemp "$REPORT.XXXXXX"); trap 'rm -f -- "$tmp"' EXIT
… > "$tmp" && mv -f -- "$tmp" "$REPORT"

systemctl show unit -p Result -p ExecMainStatus
journalctl -u unit -b -o cat
```

## Going deeper

- `man 1 grep`, *EXIT STATUS*, and `man 1 awk`.
- `man 1 bash`, *SHELL BUILTIN COMMANDS: set*, for the exact rule `-e` follows and where it does not
  apply.
- `man 1 sort` (`-k`, `-n`, `-r`, `-u`) and `man 1 uniq`.
- The logging journal, [the log lines that were never written down](../../journals/logging-journald/),
  for where an access log comes from in the first place.

## Review

1. What do grep's exit statuses 0, 1 and 2 mean?

   > 0: at least one line matched. 1: no line matched. 2: an error, such as a file it could not read.

2. Why did a quiet night fail the script even though `sort` at the end of the pipeline succeeded?

   > `pipefail` makes the pipeline's status the last non-zero status in it — grep's 1 — and `set -e`
   > ends the script on a non-zero status.

3. Why was the report empty rather than stale after the failure?

   > The redirection truncates the report when the pipeline is set up, before any of it runs.

4. Why does `uniq -c` report `/cart` several times?

   > `uniq` only compares adjacent lines, so each separate run of `/cart` is counted on its own; the
   > input has to be sorted first.

5. What is wrong with ending the pipeline in `|| true`?

   > It hides every failure, not just the empty result: an unreadable or missing log then produces a
   > successful run with an empty report.

6. Which command would you use instead of grep to select lines when a pipeline runs under `pipefail`,
   and why?

   > `awk`: it exits 0 whether or not anything matched, and non-zero only when something really went
   > wrong, so the pipeline's status keeps its meaning.
