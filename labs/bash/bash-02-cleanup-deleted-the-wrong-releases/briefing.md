# The Cleanup That Kept the Wrong Releases

The application keeps one directory per release in `/srv/app/releases/`, named after the moment it
was built — `20260913-101500`, sometimes with a label after a space, such as
`20260911-180000 hotfix`. `current` in the same directory is a symlink to the release in use.

`prune-releases` is supposed to keep the five newest releases and delete the rest, every night. This
week it:

- deleted Tuesday's release and kept one from last month, after someone restored old releases from a
  backup;
- left `20260830-090000 rollback` behind, and complained about files called `rollback` that do not
  exist;
- and, on a machine where the releases directory had been moved, **deleted the contents of the
  directory it was started from**.

It has not run at all since the last reboot.

What is expected, and graded — the grader runs `prune-releases` itself, against its own directories,
through the `RELEASES_DIR` variable the script already reads:

1. The five releases with the newest names are kept, whatever their modification times; the others
   are deleted; `current` and anything that is not a release directory are left alone.
2. Release names containing spaces are kept or deleted correctly.
3. When `RELEASES_DIR` does not exist, the script exits non-zero and deletes nothing, wherever it was
   started from.
4. It runs every night from its systemd timer, and the timer is still there after a reboot.

You have root through `sudo`.
