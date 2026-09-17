# The Deploy That Took the Site Down

The web server serves whatever `/srv/www/current` points at. Releases are unpacked next to it, in
`/srv/www/releases/`, by `deploy-site`:

```sh
deploy-site /tmp/release-2026-09-13.tar.gz
```

Last night a release archive arrived truncated. `deploy-site` printed `deployed`, exited 0, and the
site served an empty directory until someone noticed in the morning. The on-call engineer also says
the script "does something strange" when it is run twice quickly, and that it failed outright on the
staging box, where the web root is `/srv/web root/` — with a space.

What is expected, and graded — the grader runs `deploy-site` itself, against its own directories,
through the `SITE_ROOT` variable the script already reads:

1. A good archive becomes the live release, even when `SITE_ROOT` contains spaces.
2. A corrupt or missing archive changes nothing: `current` still points at the previous release, no
   half-unpacked release is left behind, and the script exits non-zero.
3. Run with no argument, it prints a usage message to standard error, exits non-zero and changes
   nothing.
4. Two deploys straight after each other produce two separate releases, and `current` ends on the
   second.

You have root through `sudo`. Everything must still hold after a reboot.
