# The Volume That Filled Overnight

The application volume, mounted at `/var/lib/app`, filled up overnight. Someone "fixed" it at
3 a.m. and rebooted. Now the machine does not finish booting and sits waiting at a maintenance
prompt.

You cannot SSH in yet. Attach to the console with **`k`** on this lab's
screen (detach with `Ctrl-]`). The root password is **`norboten`**.

Facts you have been given:

- The volume group `vg0` holds the application's logical volume. A second disk was added to the
  machine last week "for growth" and never used.
- The files under `/var/lib/app/data` are the application's data. **They must not be deleted,
  moved or truncated.**
- The machine used to have swap. It has none now.

What is expected, and graded:

1. The machine boots cleanly on its own, with `/var/lib/app` mounted.
2. `/var/lib/app` has at least 30% free space, with all its data intact.
3. Swap is active, and stays active after a reboot.
4. Filesystems are mounted by UUID or label, never by a raw device name.
5. No space on `/var/lib/app` is held by files that no longer exist.
