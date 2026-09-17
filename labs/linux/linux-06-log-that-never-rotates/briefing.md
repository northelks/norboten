# The Log That Never Rotates

The shop's order service writes to `/var/log/shop/app.log` as the system user `shop`. The file is
300 MB and growing. There is a logrotate policy for it in `/etc/logrotate.d/shop`, and logrotate
runs every night — yet the log has never been rotated, and the only time someone forced it by hand
the service stopped logging until a restart.

This lab runs in a container: no boot, no cron daemon, nothing to reboot. Run `logrotate` yourself
to see what the nightly job would do (`-d` shows it without touching anything). You are `learner`
with `sudo`. `/usr/local/bin/shop-log` writes one line as `shop`, the way the service does.

What is expected, and graded — rotation is tried against a copy of your policy, in a scratch
directory set up like `/var/log/shop`, so the grader never rotates your real logs:

1. logrotate reads `/etc/logrotate.d/shop` instead of ignoring it.
2. logrotate agrees to rotate logs in a directory like `/var/log/shop`.
3. After a rotation, `shop` can still write to `app.log`.
4. The policy keeps seven rotated logs, compressed, and no more.
5. The oversized `app.log` has actually been rotated: it is small now, and its history is beside it.

Do not solve it by making `/var/log/shop` root's: the service writes there.
