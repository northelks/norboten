---
title: The volume that filled overnight
topics: [storage-lvm, boot-systemd]
minutes: 40
---

A full filesystem is the most ordinary emergency there is, and the machine in this lab is what
happens when somebody fixes one at three in the morning. The volume filled. They freed some space,
edited `/etc/fstab`, rebooted to "make sure it was clean" — and now the machine will not finish
booting, `df` disagrees with `du`, and the swap that used to be there is gone.

None of those are hard problems. They are hard *together*, at three in the morning, when you
cannot log in over the network because the boot never got that far. This journal is the mechanism
behind all four, so that next time they are boring.

## What you should be able to do after this

- Read a storage stack from the bottom up: disk → physical volume → volume group → logical
  volume → filesystem → mount point, and say which layer is short of space.
- Grow an XFS filesystem onto a disk that was added to the machine and never used.
- Explain why a filesystem can be full while `du` says it is nearly empty, and find the process
  responsible without rebooting.
- Write an `/etc/fstab` entry that survives a device being renamed, and check it before you
  reboot rather than after.
- Get out of the maintenance prompt: read why the boot stopped, fix it from there, and continue
  the boot without a second reboot.
- Add swap that comes back on its own.

## The mechanism

### The stack, layer by layer

```
  /var/lib/app                     mount point       ← what df reports on
  ──────────────────────────
  XFS filesystem                   mkfs.xfs, xfs_growfs
  ──────────────────────────
  /dev/vg0/applv                   logical volume    ← lvextend grows this
  ──────────────────────────
  vg0   (extents: 4 MiB each)      volume group      ← vgextend grows this
  ──────────────────────────
  /dev/vdb        /dev/vdc         physical volumes  ← pvcreate makes these
  ──────────────────────────
  virtio disks                     the hardware
```

Four commands read the three LVM layers, and they are all worth knowing by heart:

```console
$ sudo pvs
  PV         VG  Fmt  Attr PSize  PFree
  /dev/vdb   vg0 lvm2 a--  <2.00g    0
  /dev/vdc       lvm2 ---   2.00g 2.00g

$ sudo vgs
  VG  #PV #LV #SN Attr   VSize  VFree
  vg0   1   1   0 wz--n- <2.00g    0

$ sudo lvs
  LV    VG  Attr       LSize  Pool Origin Data%  Meta%  Move Log Cpy%Sync Convert
  applv vg0 -wi-ao---- <2.00g
```

Read those three outputs in that order and the machine has already told you the answer: `vg0` has
**no free extents**, the logical volume is using all of them — and there is a second physical
volume, `/dev/vdc`, that belongs to no volume group at all. Someone prepared a disk for growth and
never wired it in. `PFree 2.00g` on a PV with an empty `VG` column is what "prepared and forgotten"
looks like. (The `<2.00g` on the one in use is LVM being honest: its metadata takes a few extents off
the top of the disk, so the usable size is slightly under 2 GiB.)

The fourth command is `df -h /var/lib/app`, and it is the only one that speaks about the
filesystem rather than the volume. Keep the distinction: **a logical volume can have free space
while the filesystem on it is full, and a filesystem can be full while the volume group is empty.**
They are different layers and they are grown by different commands.

### Growing it

Two steps, bottom up. First give the volume group the disk nobody used:

```console
$ sudo vgextend vg0 /dev/vdc
  Volume group "vg0" successfully extended
```

Then grow the logical volume *and the filesystem on it* in one move:

```console
$ sudo lvextend -r -l +100%FREE vg0/applv
  File system xfs found on vg0/applv mounted at /var/lib/app.
  Size of logical volume vg0/applv changed from <2.00 GiB (511 extents) to 3.99 GiB (1022 extents).
  Extending file system xfs to 3.99 GiB (4286578688 bytes) on vg0/applv...
xfs_growfs /dev/vg0/applv
…
data blocks changed from 523264 to 1046528
xfs_growfs done
  Extended file system xfs on vg0/applv.
  Logical volume vg0/applv successfully resized.
```

The flags are the whole lesson:

- `-l +100%FREE` — take every remaining extent in the group. `-L +2G` takes a size instead; `-l`
  speaks in extents and percentages, `-L` in bytes.
- `-r` (`--resizefs`) — after growing the volume, grow the filesystem to match, by calling
  `xfs_growfs` (or `resize2fs` on ext4). Without it you get a bigger volume with the same
  filesystem inside it, `df` does not move, and it looks as though nothing happened.

Both can be done online: XFS grows while mounted, and there is no need to stop the application.
**XFS cannot shrink.** Not with `-r`, not with any flag, not ever — if you need a smaller XFS
filesystem you make a new one and copy the data. That asymmetry is worth remembering before you
hand out extents you might want back.

### Why `df` and `du` disagree

`du` walks the directory tree and adds up the files it can see. `df` asks the filesystem how many
blocks are free. A file that has been deleted while a process still holds it open is invisible to
the first and very much visible to the second: its directory entry is gone, so `du` cannot find
it, but the inode and its blocks survive until the last file descriptor closes.

```console
$ df -h /var/lib/app
Filesystem             Size  Used Avail Use% Mounted on
/dev/mapper/vg0-applv  2.0G  1.9G  130M  94% /var/lib/app

$ sudo du -sh /var/lib/app
1.4G    /var/lib/app
```

Half a gigabyte is missing, and `lsof` knows where:

```console
$ sudo lsof -a +L1 /var/lib/app
COMMAND    PID USER   FD   TYPE DEVICE  SIZE/OFF NLINK NODE NAME
app-spool 1066 root    3r   REG  253,0 398458880     0  134 /var/lib/app/spool.tmp (deleted)
```

`+L1` means "files with fewer than one link" — that is exactly the definition of a deleted file
that is still open. `NLINK 0` and `(deleted)` are the two things to look for, and `-a` makes lsof AND
its conditions together (by default it ORs them, and would list every open file on the volume).
`COMMAND` is cut to nine characters, so `app-spool` is `app-spooler`. The same answer is in `/proc`,
which is useful when `lsof` is not installed:

```console
$ sudo ls -l /proc/1066/fd | grep deleted
lr-x------. 1 root root 64 Sep 13 04:54 3 -> /var/lib/app/spool.tmp (deleted)
```

To get the space back you have to make that process let go. Restarting the service is the honest
fix and takes a second:

```console
$ sudo systemctl restart app-spooler
$ sleep 1 ; df -h /var/lib/app
```

The `sleep` is not superstition. XFS on recent kernels frees the blocks of an unlinked inode in a
background worker, so a `df` run in the same instant as the restart can still show the old figure —
measured on this machine, it did. Give it a second before concluding the restart did nothing.

Killing the process works too, but a service that is supposed to be running should be restarted,
not killed. And **do not** reach for `truncate -s 0 /proc/1066/fd/3` unless you understand what the
program does with a file that suddenly became empty underneath it — some log writers are fine
with that, some write at their old offset and leave you with a sparse file the same size as
before.

### fstab, and what systemd does with it

An `/etc/fstab` line has six fields:

```
UUID=a01e…  /var/lib/app  xfs  defaults,x-systemd.device-timeout=10s  0  0
└─ source   └─ target     └─ fs └─ options                            │  └─ fsck order
                                                                      └─ dump
```

The **source** is the part that goes wrong. A device name like `/dev/vdb1` is not a stable
identifier: it depends on how many disks the machine has, which order the kernel enumerated them
in, and whether a partition exists at all. The 3 a.m. edit in this lab changed a UUID to
`/dev/vdb1` — a partition that has never existed on this machine, because `/dev/vdb` is a physical
volume with no partition table. Name the filesystem instead:

```console
$ sudo blkid -s UUID -o value /dev/vg0/applv
a01e14d3-b0c7-45d6-8e8d-881804180eb3
```

(The UUID is created by `mkfs`, so yours is different — which is precisely why you ask `blkid` rather
than copying one from anywhere.)

`UUID=` is the default choice; `LABEL=` is fine too and easier to read. LVM device paths
(`/dev/vg0/applv`) are stable as well, because LVM resolves them by metadata rather than by
enumeration order — but the exam, and most house styles, want a UUID, and a UUID is never wrong.

Then check it **before** you trust it:

```console
$ sudo findmnt --verify --tab-file /etc/fstab
Success, no errors or warnings detected
```

That parses every line, resolves every source and reports what would fail. It is the difference
between finding out now and finding out during a boot you cannot log into. Run it as root: as an
ordinary user it cannot open the block devices and reports a *cannot detect on-disk filesystem type
(Permission denied)* warning for every line, which buries the one that matters. And read the
warnings, not just the error count — the broken entry in this lab produces `0 errors, 2 warnings`:

```
/var/lib/app
   [W] unreachable source: /dev/vdb1: No such file or directory
   [W] cannot detect on-disk filesystem type (No such file or directory)
```

Systemd does not read `/etc/fstab` at mount time. At boot — and whenever you run `systemctl
daemon-reload` — `systemd-fstab-generator` turns each line into a `.mount` unit:

```console
$ systemctl cat var-lib-app.mount | head -5
# /run/systemd/generator/var-lib-app.mount
# Automatically generated by systemd-fstab-generator
[Unit]
Documentation=man:fstab(5) man:systemd-fstab-generator(8)
```

Two consequences worth internalising. First: after editing `fstab`, run `systemctl daemon-reload`,
or the *running* systemd is still acting on the previous version — `findmnt --verify` even says so,
*your fstab has been modified, but systemd still uses the old version*. (The next boot runs the
generator again and sees the new file; the stale view is a problem for the system you are standing
in.) Second: the mount is a dependency of `local-fs.target`, so a mount that cannot happen stops the
boot rather than degrading it. That is why a typo in `fstab` is not a cosmetic mistake: it is a
machine that does not come back.

`x-systemd.device-timeout=10s` in the options is a small kindness: without it systemd waits 90
seconds for a device that is never going to appear before giving up. The `x-` prefix marks an
option for the generator rather than for the filesystem driver, which is why `mount` itself
ignores it.

### The maintenance prompt

When the source in `fstab` names a device that never appears, systemd waits for it (here ten
seconds, thanks to `x-systemd.device-timeout`), gives up, and the failure cascades. The journal of
this lab's broken boot records exactly that chain:

```
systemd[1]: Timed out waiting for device dev-vdb1.device - /dev/vdb1.
systemd[1]: Dependency failed for var-lib-app.mount - /var/lib/app.
systemd[1]: Dependency failed for local-fs.target - Local File Systems.
systemd[1]: Started emergency.service - Emergency Shell.
systemd[1]: Reached target emergency.target - Emergency Mode.
```

and the console ends at:

```
Give root password for maintenance
(or press Control-D to continue):
```

Notice what failed: not the mount, but the *device* the mount was waiting for. The mount unit never
ran, so it is `inactive (dead)`, not `failed` — which matters in a moment.

There is no network in emergency mode, so this is a console conversation:
`k` on the lab's screen. Three things to do, in order:

```console
# journalctl -xb -p err          # why the boot stopped, with explanations  ← start here
# findmnt --verify              # whether fstab is the reason
# systemctl --failed            # what is broken — which may be nothing (see below)
```

Then fix `fstab`, reload, and mount by hand to prove it:

```console
# vi /etc/fstab
# systemctl daemon-reload
# mount -a
# findmnt /var/lib/app
```

And instead of rebooting, **continue the boot you interrupted**:

```console
# systemctl default
Failed to connect to system scope bus via local transport: No such file or directory
```

That switches to the default target and carries on. On Rocky 10 it prints that complaint about the
bus — D-Bus is not running in emergency mode — and then does it anyway: the console fills with the
rest of the boot and ends at a login prompt, and the journal records *Stopped target emergency.target*
followed by *Reached target multi-user.target*. Do not let the message send you back to a reboot. Rebooting also works, but `systemctl default`
is faster and tells you immediately whether the rest of the boot is healthy — and on the exam, the
difference between one reboot and three is minutes you do not have.

### Swap

Swap is not a filesystem, so it is not mounted; it is *enabled*, and it needs its own `fstab`
line. A swap **file** is made in three steps and enabled in one:

```console
$ sudo dd if=/dev/zero of=/swapfile bs=1M count=256 status=none   # or: fallocate -l 256M
$ sudo chmod 600 /swapfile
$ sudo mkswap /swapfile
$ sudo swapon /swapfile
$ swapon --show
NAME      TYPE SIZE USED PRIO
/swapfile file 256M   0B   -2
```

`chmod 600` is not decoration: `swapon` refuses a world-readable swap file, and rightly — anything
in memory can end up in there. To bring it back after a reboot, `fstab` needs:

```
/swapfile none swap defaults 0 0
```

The target field is `none` because there is nothing to mount it on, and the type is `swap`.
`swapon -a` enables everything in `fstab`, which is exactly what the boot does. A swap file that
is enabled but missing from `fstab` works perfectly until the next reboot and then silently does not
— and that next reboot is where this lab's machine already is: `/swapfile` exists, is off, and has no
`fstab` line.

## A failure, walked through

The machine is at the maintenance prompt, reached with `k` on the lab's screen. Nothing else
is known.

**1. Ask why the boot stopped.** Start with the errors of this boot, not with the failed units:

```console
# journalctl -xb -p err --no-pager | tail -8
Sep 13 04:46:53 lima-nb-rhcsa-03 systemd[1]: Timed out waiting for device dev-vdb1.device - /dev/vdb1.
░░ Subject: A start job for unit dev-vdb1.device has failed
░░ …
░░ A start job for unit dev-vdb1.device has finished with a failure.
░░
░░ The job identifier is 226 and the job result is timeout.
# systemctl --failed
  UNIT LOAD ACTIVE SUB DESCRIPTION

0 loaded units listed.
```

The first command has the answer — systemd waited for a device called `/dev/vdb1` and it never came.
The second shows why it is not the place to start: **nothing is in the failed state**. The device job
timed out, and the mount that depended on it was never attempted, so it is merely inactive. A lot of
people look at an empty `systemctl --failed`, conclude the boot is fine, and press Control-D.

**2. Ask what it tried to mount.**

```console
# systemctl status var-lib-app.mount --no-pager
○ var-lib-app.mount - /var/lib/app
     Loaded: loaded (/etc/fstab; generated)
     Active: inactive (dead)
      Where: /var/lib/app
       What: /dev/vdb1
```

`What: /dev/vdb1`. Does it exist?

```console
# ls -l /dev/vdb1
ls: cannot access '/dev/vdb1': No such file or directory
# lsblk
NAME        MAJ:MIN RM  SIZE RO TYPE MOUNTPOINTS
sr0          11:0    1  168K  0 rom
vda         252:0    0   16G  0 disk
├─vda1      252:1    0  200M  0 part /boot/efi
├─vda2      252:2    0 1000M  0 part /boot
└─vda3      252:3    0 14.8G  0 part /
vdb         252:16   0    2G  0 disk
└─vg0-applv 253:0    0    2G  0 lvm
vdc         252:32   0    2G  0 disk
# findmnt --verify
/var/lib/app
   [W] unreachable source: /dev/vdb1: No such file or directory
   [W] cannot detect on-disk filesystem type (No such file or directory)

0 parse errors, 0 errors, 2 warnings
```

There is the shape of the whole machine in one screen: `vdb` carries the LVM volume (no
partition — `vdb1` was never real), `vdc` is untouched, and the logical volume is 2 GiB. And
`findmnt --verify` agrees, with *warnings* — `0 errors` is not a clean bill of health.

**3. Fix the source, not the symptom.** The filesystem is `/dev/vg0/applv`; ask it for its UUID
and write that:

```console
# blkid -s UUID -o value /dev/vg0/applv
a01e14d3-b0c7-45d6-8e8d-881804180eb3
# vi /etc/fstab          # replace /dev/vdb1 with UUID=a01e14d3-…
# findmnt --verify --tab-file /etc/fstab
   [W] your fstab has been modified, but systemd still uses the old version;
       use 'systemctl daemon-reload' to reload

0 parse errors, 0 errors, 1 warning
# systemctl daemon-reload
# findmnt --verify --tab-file /etc/fstab
Success, no errors or warnings detected
# mount -a
[   51.796177] XFS (dm-0): Mounting V5 Filesystem a01e14d3-b0c7-45d6-8e8d-881804180eb3
[   51.804620] XFS (dm-0): Ending clean mount
# systemctl default
Failed to connect to system scope bus via local transport: No such file or directory
…
lima-nb-rhcsa-03 login:
```

`findmnt` noticed the missing `daemon-reload` before we did. And `systemctl default` continued the
boot despite its complaint about the bus: the console ran through the rest of the boot to a login
prompt, and SSH answers. Now the original problem is still waiting.

**4. Find out which layer is short of space.**

```console
$ df -h /var/lib/app          # 94% used, 130M free   → the filesystem is nearly full
/dev/mapper/vg0-applv  2.0G  1.9G  130M  94% /var/lib/app
$ sudo du -sh /var/lib/app    # 1.4G                  → but the files do not explain it all
1.4G    /var/lib/app
$ sudo vgs                    # VFree 0               → and the group has nothing left to give
  vg0   1   1   0 wz--n- <2.00g    0
$ sudo pvs                    # /dev/vdc, no VG       → while a whole disk sits unused
  /dev/vdb   vg0 lvm2 a--  <2.00g    0
  /dev/vdc       lvm2 ---   2.00g 2.00g
```

Two independent problems, and now both are visible: space held by a deleted file, and a volume
group that needs the spare disk.

**5. Release the held space.**

```console
$ sudo lsof -a +L1 /var/lib/app
COMMAND    PID USER   FD   TYPE DEVICE  SIZE/OFF NLINK NODE NAME
app-spool 1066 root    3r   REG  253,0 398458880     0  134 /var/lib/app/spool.tmp (deleted)
$ sudo systemctl restart app-spooler
$ sudo lsof -a +L1 /var/lib/app          # silence
```

Check `df` again a second later rather than instantly — XFS releases unlinked inodes in the
background.

**6. Grow the volume, because a few hundred megabytes of headroom on a volume that filled once will
fill again.**

```console
$ sudo vgextend vg0 /dev/vdc
  Volume group "vg0" successfully extended
$ sudo lvextend -r -l +100%FREE vg0/applv
  Size of logical volume vg0/applv changed from <2.00 GiB (511 extents) to 3.99 GiB (1022 extents).
  …
  Logical volume vg0/applv successfully resized.
$ df -h /var/lib/app
Filesystem             Size  Used Avail Use% Mounted on
/dev/mapper/vg0-applv  4.0G  1.5G  2.5G  38% /var/lib/app
$ lsblk /dev/vdb /dev/vdc
NAME        MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
vdb         252:16   0   2G  0 disk
└─vg0-applv 253:0    0   4G  0 lvm  /var/lib/app
vdc         252:32   0   2G  0 disk
└─vg0-applv 253:0    0   4G  0 lvm  /var/lib/app
```

`lsblk` now draws the same logical volume under both disks — which is what a volume spanning two
physical volumes is.

**7. Put swap back, and make it stick.**

```console
$ swapon --show                            # nothing
$ ls -l /swapfile                          # it is still there, just off
-rw-------. 1 root root 268435456 Sep 13 04:53 /swapfile
$ sudo swapon /swapfile
$ swapon --show
NAME      TYPE SIZE USED PRIO
/swapfile file 256M   0B   -2
$ echo '/swapfile none swap defaults 0 0' | sudo tee -a /etc/fstab
```

**8. Prove it survives a reboot**, because that is the only proof that counts:

```console
$ sudo reboot
$ findmnt /var/lib/app && swapon --show && df -h /var/lib/app
```

## Common wrong turns

**Deleting the data to make room.** The briefing says the files under `data/` must not be deleted,
moved or truncated, and the checks hash the first megabyte of `orders.db` to make sure they were
not. In real life the equivalent is deleting a database file to free space — which is how a full
disk becomes a restore from backup.

**Running `lvextend` without `-r`.** The volume grows, `lvs` shows the new size, `df` shows the
old one, and the natural conclusion is that LVM is broken. It is not: the filesystem inside the
volume has not been told. `lvextend -r`, or `xfs_growfs /var/lib/app` afterwards.

**Trying to shrink XFS** to give space back. There is no such operation. If you have over-grown a
volume, the way back is a new filesystem and a copy.

**Rebooting to reclaim held space.** On most machines it works — every process lets go when it
dies — but it hides the cause, and the one thing you know about a machine that filled up overnight
is that it will fill up again. On this machine it does not even work: the spooler takes its spool
again as it starts at the next boot, the way a leaking application does. Find the file and restart
the service that holds it.

**Trusting an empty `systemctl --failed`.** A mount waiting on a device that never appears is not
*failed*, it is *inactive* — the timed-out device job is what failed, and it has gone. Read
`journalctl -xb -p err` first.

**Fixing `fstab` and rebooting without checking.** If the entry is still wrong you are back at the
maintenance prompt, having spent a minute of boot to learn something `findmnt --verify` would have
told you instantly.

**Forgetting `systemctl daemon-reload`.** The running systemd keeps the mount unit generated from the
old `fstab`: `systemctl status` still shows `What: /dev/vdb1`, and anything that asks systemd to mount
the path — continuing the boot, starting a service with `RequiresMountsFor=` — can act on the stale
definition. The next boot regenerates the units, so it hides the mistake rather than exposing it.
`findmnt --verify` warns about exactly this; read its warnings.

**Adding swap without an `fstab` line.** `swapon` is not persistent. `swapon --show` says it is
fine; the next boot says otherwise.

**Mounting by device name because it is quicker.** It is quicker, and it is the reason this lab
exists. Names move; UUIDs do not.

## Cheat sheet

```console
# reading the stack
lsblk                          # disks, partitions, LVM, mount points, in one tree
pvs / vgs / lvs                # the three LVM layers, one line each
df -h /path                    # filesystem free space (the top layer)
du -sh /path                   # what the files actually add up to
blkid -s UUID -o value DEV     # the UUID to put in fstab
findmnt /path                  # what is mounted there, and how

# growing
vgextend vg0 /dev/vdc          # give the group another physical volume
lvextend -r -l +100%FREE vg0/applv    # grow the volume and the filesystem
lvextend -r -L +2G vg0/applv          # …by a size instead
xfs_growfs /var/lib/app        # grow XFS alone (what -r calls)
resize2fs /dev/vg0/applv       # the ext4 equivalent

# space that du cannot see
lsof -a +L1 /path              # deleted files still held open (-a: AND, not OR)
ls -l /proc/PID/fd | grep deleted
systemctl restart UNIT         # the honest way to make it let go

# fstab
findmnt --verify --tab-file /etc/fstab   # check before you reboot
systemctl daemon-reload                  # after every fstab edit
mount -a                                 # mount everything in fstab
systemctl cat var-lib-app.mount          # the unit systemd generated

# swap
mkswap /swapfile ; chmod 600 /swapfile ; swapon /swapfile
swapon --show
echo '/swapfile none swap defaults 0 0' >> /etc/fstab

# emergency mode
journalctl -xb -p err          # why the boot stopped  ← first
findmnt --verify               # fstab's problems, as warnings as well as errors
systemctl --failed             # what is broken now (a device timeout leaves this EMPTY)
systemctl default              # continue the boot instead of rebooting
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The space that belongs to a file with no name* (lab journal `linux-01-disk-full`) — Deleting a file does not delete a file

Manual pages: `man 5 fstab`, `man 5 systemd.mount`, `man 8 lvm`, `man 8 swapon`, `man 8 blkid`, `man 1 lsof`.

## Review

1. `df` says a 2 GiB filesystem is 94% full; `du` on its mount point says 1.4 GiB. Where
   is the difference, and which command finds it?

   > In blocks belonging to files that have been deleted while a process still holds them open —
   > unlinked inodes, invisible to a tree walk. `lsof -a +L1 <mountpoint>`, or
   > `ls -l /proc/<pid>/fd | grep deleted`.

2. You run `lvextend -l +100%FREE vg0/applv` and `df` does not change. What was forgotten?

   > The filesystem was never grown. Add `-r` (`--resizefs`) so lvextend calls `xfs_growfs`, or
   > run `xfs_growfs /var/lib/app` afterwards.

3. Why is `/dev/vdb1` a worse thing to put in `fstab` than `UUID=…`, beyond style?

   > Kernel device names depend on enumeration order and on the partition actually existing; a
   > UUID identifies the filesystem itself and cannot be changed by adding a disk. A wrong source
   > in fstab fails `local-fs.target` and stops the boot.

4. You have corrected `/etc/fstab` at the maintenance prompt. What do you run before rebooting,
   and what lets you avoid the reboot altogether?

   > `findmnt --verify --tab-file /etc/fstab`, then `systemctl daemon-reload` and `mount -a` to
   > prove it. `systemctl default` continues the interrupted boot instead of rebooting.

5. A swap file is active in `swapon --show` but gone after the next reboot. Why?

   > It was enabled by hand and never added to `/etc/fstab`; the boot only runs `swapon -a`, which
   > enables what fstab lists.

6. Which of these can be done online, on a mounted XFS filesystem: growing it, shrinking it,
   adding a physical volume to its volume group?

   > Growing: yes. Adding a PV to the group: yes. Shrinking XFS: never — not online, not offline.
   > Make a new filesystem and copy.

7. `systemctl status var-lib-app.mount` says `Loaded: loaded (/etc/fstab; generated)`. What
   generated it, and when does it run again?

   > `systemd-fstab-generator`, at boot and on every `systemctl daemon-reload`. Until you reload,
   > systemd is still acting on the previous fstab.

8. The machine is in emergency mode because of a bad `fstab` source, and `systemctl --failed` lists
   nothing. Why, and where is the evidence?

   > The mount was waiting for a device that never appeared; the device job timed out, and the mount
   > that depended on it was never attempted, so it is inactive rather than failed. The evidence is in
   > `journalctl -xb -p err` (*Timed out waiting for device dev-vdb1.device*) and in the warnings from
   > `findmnt --verify`.
