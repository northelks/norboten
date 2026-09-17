# The Report That Crashes on One Name

`/opt/members/report.py` reads the membership exports in `/srv/members/` and writes a summary of the
members per city to `/var/lib/members/summary.csv`. `members-report.timer` runs it shortly after boot
and every night.

Two systems export into that directory. The new one writes UTF-8. The old one, a Windows tool nobody
maintains, writes **cp1252** — its files are named `*.cp1252.csv`, and that is documented in
`/srv/members/README`. Since a member called Ruiz Peña joined, the job has failed every night with a
`UnicodeDecodeError`, and the summary is a week old. A colleague "fixed" it once by ignoring the
characters that would not decode, and the report then listed *Pea* as a member's name.

What is expected, and graded — the grader runs `report.py` itself, through the `MEMBERS_DIR` and
`SUMMARY_OUT` variables the script already reads:

1. Every export is read: a `*.cp1252.csv` file as cp1252, every other `*.csv` as UTF-8.
2. Every name reaches the summary exactly as it was written, with no character dropped or replaced.
3. The summary is written as UTF-8, whatever the machine's locale, and is valid CSV.
4. The run started by `members-report.timer` succeeds and the summary holds every city — and still
   does after a reboot.

You have root through `sudo`.
