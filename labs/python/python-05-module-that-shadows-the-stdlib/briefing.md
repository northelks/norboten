# The Module That Shadows the Standard Library

`/opt/digest/digest.py` reads the day's events from `/srv/digest/events.json` and writes a one-line
digest to `/var/lib/digest/today.txt`. `digest.service` runs it after boot.

Since a colleague added a small helper for the internal calendar, every run fails with a traceback
that makes no sense: `AttributeError: module 'calendar' has no attribute 'monthrange'`. Somebody
added `WorkingDirectory=/opt/digest` to the unit last week hoping it would help; it changed
nothing.

What is expected, and graded — the grader runs `digest.py` itself, through the `DIGEST_EVENTS` and
`DIGEST_OUT` variables the script already reads:

1. Started from `/opt/digest`, the program writes the digest and exits 0.
2. Started from any other directory, it writes exactly the same digest.
3. The standard library modules it uses are the standard library's, not the program's own files:
   importing `calendar`, `json` or `logging` in a program started from `/opt/digest` gives the
   module from Python's own library.
4. `digest.service` succeeds and the digest holds today's events — and still does after a reboot.

You have root through `sudo`. The helper's own function must keep working: the digest names the
number of days in the month.
