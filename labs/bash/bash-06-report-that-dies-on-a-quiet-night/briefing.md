# The Report That Dies on a Quiet Night

`errors-report` reads the shop's access log, `/var/log/shop/access.log`, and writes the server errors
(status 500–599) per endpoint to `/var/lib/shop/errors.txt` for the morning stand-up.
`errors-report.timer` runs it shortly after boot and every night.

Somebody added `set -euo pipefail` after a code review. Since then the timer's run fails on every
good night — the nights with no errors at all — and the alert about the failed unit has been
muted. On bad nights the report shows `/cart` twice with two different counts.

What is expected, and graded — the grader runs `errors-report` itself, through the `LOG` and
`REPORT` variables the script already reads. The report is one line per endpoint, `<count> <path>`,
highest count first (equal counts by path), then a last line `total <N>`:

1. A log with no server errors produces a report of just `total 0`, and the script exits 0.
2. A log with errors produces one line per endpoint with the right counts, in that order.
3. A log that does not exist, or cannot be read, makes the script exit non-zero with a message on
   standard error.
4. The run started by `errors-report.timer` succeeds and writes the report — and still does after a
   reboot.

You have root through `sudo`.
