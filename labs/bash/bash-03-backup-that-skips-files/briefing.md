# The Backup That Skips Files

`backup-docs` copies every file under `/srv/docs` into `/var/backups/docs/<YYYY-MM-DD>/`, keeping the
relative paths. `backup-docs.timer` runs it shortly after boot and every night.

Last week legal asked for last month's contract, `Contract - ACME.pdf`. It was not in any backup.
The job's journal says `backed up 0 files` every night, systemd lists every run as successful, and
nobody had looked at it since it was written.

What is expected, and graded — the grader runs `backup-docs` itself, as an ordinary user, against its
own directories, through the `DOCS_DIR` and `BACKUP_DIR` variables the script already reads:

1. Every regular file is copied, byte for byte, to the same relative path under today's directory —
   whatever its name: spaces, a leading dash, leading blanks, a backslash, even a newline.
2. The last line of output is `backed up N files`, where N is the number of files it copied.
3. When a file cannot be copied, the script names it on standard error, still copies the rest, and
   exits non-zero.
4. The run started by `backup-docs.timer` succeeds and backs up everything in `/srv/docs` — and still
   does after a reboot.

You have root through `sudo`.
