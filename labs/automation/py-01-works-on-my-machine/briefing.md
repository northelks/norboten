# The Job That Works on My Machine

`/opt/etl/report.py` pulls metrics from the internal metrics API and writes a summary to
`/var/lib/etl/reports/latest.json`. Its author says it works: they run it from `/opt/etl`, with
the project's virtualenv activated, and the report appears.

From its systemd timer it has never produced a single report. The timer is supposed to run it
shortly after boot and every five minutes after that.

Security also flagged the metrics API token in `/etc/etl/token`.

What is expected, and graded:

1. `etl-report.timer` is enabled and active, so it survives reboots.
2. The job succeeds when systemd runs it — without anyone logged in — and writes a fresh report.
3. It runs as the **`etl`** service account, not as root.
4. The token is readable by that account and nobody else.

You have root through `sudo`. Everything must still hold after a reboot.
