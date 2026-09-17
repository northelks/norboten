# The Backup Script That Lies

`/usr/local/bin/backup-data` archives `/srv/data` into `/var/backups` every night and writes
"backup OK" to `/var/log/backup-data.log`. It has said "backup OK" every night for a year.

Last week someone needed a restore. The newest archive held a fraction of the files. Nobody can
say when that started. Looking at `/var/backups`, there have been no new archives for days — and
the log still says "backup OK" whenever someone runs it by hand.

The script honours three variables, so you can test it safely: `BACKUP_SRC` (default
`/srv/data`), `BACKUP_DEST` (default `/var/backups`) and `BACKUP_LOG`
(default `/var/log/backup-data.log`).

What is expected, and graded — the script is run against test data you will not see:

1. Every file under the source ends up in the archive, whatever its name — spaces included.
2. If the archive cannot be written, the script exits non-zero, says why on stderr, and does not
   log "backup OK".
3. If the source directory does not exist, the same: non-zero exit, a message, no "backup OK".
4. The nightly cron job can actually run the script.

Keep the script in Bash.
