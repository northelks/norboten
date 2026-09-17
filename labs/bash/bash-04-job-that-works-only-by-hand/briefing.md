# The Job That Works Only by Hand

`/opt/reports/bin/nightly-report` writes the disk use of every project listed in
`/opt/reports/report.conf` to `/var/lib/reports/latest.txt`, which the morning mail attaches.
`nightly-report.timer` runs it shortly after boot and every night.

The mail has attached an empty report for a week. Whenever someone logs in with `sudo -i` and runs
the script by hand, it works and prints `report written`. systemd lists every timer run as
successful anyway.

What is expected, and graded — the grader runs the script itself, through the `REPORT_CONF` (the
configuration, default `/opt/reports/report.conf`) and `REPORT_OUT` (the report, default
`/var/lib/reports/latest.txt`) variables the script already reads:

1. Started with an empty environment (`env -i`, apart from those two variables), it writes the
   report and exits 0.
2. Started from any working directory, with only `REPORT_OUT` set, it reads the default
   configuration and writes the report.
3. When the configuration file does not exist, it exits non-zero and the previous report is left
   exactly as it was.
4. The run started by `nightly-report.timer` succeeds and writes a report of every project — and
   still does after a reboot.

You have root through `sudo`.
