# The Shared Folder That Locks People Out

The reports team — **alice**, **bob** and **carol**, as `/srv/reports/TEAM.txt` says — shares
`/srv/reports`. It has never worked. Whoever writes a report is the only one who can change it;
carol cannot open half the files at all; and **dave**, a contractor who is not on the team, reads
all of it. A previous admin "hardened" logins last year, and things got worse.

This lab runs in a container, not a VM: there is no boot and nothing to reboot. You are `learner`
with `sudo`. `su - alice` (or bob, carol, dave) is how to see the folder through someone's eyes —
the grader looks at it that way too.

What is expected, and graded:

1. alice, bob and carol are in the group `reports`; dave is not.
2. Each of them can read and change every file and directory already in `/srv/reports`.
3. A file or directory any of them creates there later belongs to `reports`, and the other two can
   read and change it — without anyone running `chmod` afterwards.
4. dave cannot list `/srv/reports` or read anything in it.

Do not solve it with `chmod 777`: that fails the fourth, and it fails your next audit.
