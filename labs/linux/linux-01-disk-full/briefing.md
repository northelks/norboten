# The Disk That Stays Full

The **ledger** service writes its transaction log to its own filesystem, mounted at
`/var/log/app`. This morning it reported the disk full.

An hour ago a colleague deleted the biggest file they could find there. `df` still says the
filesystem is almost full. `du` says there is hardly anything in it. The colleague went home.

What is expected, and graded:

1. The log filesystem has at least half of its space free.
2. No space on it is held by files that no longer exist.
3. The ledger log is rotated automatically, so this cannot happen again.
4. ledger keeps running, and starts at boot. Stopping or removing it is not a fix.

You have root through `sudo`. Everything must still hold after a reboot.
