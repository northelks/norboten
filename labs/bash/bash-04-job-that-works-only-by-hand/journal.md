---
title: A script run by a timer inherits nothing you set up for yourself
topics: [bash, boot-systemd]
minutes: 30
---

"It works when I run it" is the most expensive sentence in operations, because it is true. The
person saying it is logged in, in an interactive shell that has read a start-up file, sitting in a
directory they chose, with a `PATH` somebody extended years ago. The timer that runs the same script
at five in the morning has none of that: a short `PATH`, the root directory as its working directory,
no terminal, and no start-up files at all.

`nightly-report` depends on two of those things without saying so — a helper found only through a
`PATH` added in root's `.bashrc`, and a configuration file found only because the same `.bashrc`
changes into `/opt/reports`. On top of that it cannot fail: whatever goes wrong, it empties the
report and exits 0.

## What you should be able to do after this

- List what a systemd service inherits — environment, working directory, start-up files — and how
  that differs from an interactive login shell.
- Explain when bash reads `.bashrc`, `.profile` and `/etc/environment`, and why none of them
  reaches a timer's run.
- Write a script that names everything it needs: an explicit `PATH`, absolute paths, configuration
  by absolute default.
- Explain the search rule of the `.` (source) command for a name without a slash.
- Keep the previous output when a run fails, by writing to a temporary file and renaming it.
- Reproduce a timer's environment by hand with `env -i` and `systemd-run`.

## The mechanism

### Two kinds of shell, and what each one reads

Bash decides which start-up files to read from how it was started. A **login** shell reads
`/etc/profile` and the first of `~/.bash_profile`, `~/.bash_login`, `~/.profile`. An **interactive
non-login** shell reads `~/.bashrc`. A **non-interactive** shell — `bash script`, `bash -c '…'`, the
interpreter named in a script's `#!` line — reads neither (only a file named in `$BASH_ENV`, if set).

Ubuntu's default `~/.bashrc` also begins by checking whether the shell is interactive and returning
immediately if it is not. Anything appended to the end of the file, as the `PATH` for the reporting
tools was, exists only in shells where a person is typing.

### What a service gets instead

systemd starts a service's process directly, not through a shell. The environment is built from the
manager's own small default — a `PATH` of the standard system directories — plus whatever the unit
sets with `Environment=` or `EnvironmentFile=`. The working directory is `/` unless
`WorkingDirectory=` says otherwise, and `HOME` cannot be relied on — on this machine it arrives
empty. There is no terminal. `/etc/environment` is read by PAM for logins, not by systemd for services.

`env -i` reproduces the empty end of that range from any shell: it starts a program with no
environment at all. `systemd-run --wait --pipe` runs a command as a transient service, so it gets
exactly what a real unit would.

### How a script finds a command

A command without a slash is searched for in each directory of `PATH`, in order. When `PATH` is
unset, bash substitutes a built-in default of standard directories. A helper installed in
`/opt/reports/tools/bin` is therefore found only by callers whose `PATH` includes that directory,
which is to say only by the shells that read that one `.bashrc`.

A script that must run anywhere sets its own `PATH` at the top, or calls its helpers by absolute
path. Both make the dependency visible in the script, instead of in someone's shell configuration.

### How `.` finds a file

`. report.conf` does not simply read `./report.conf`. For a name with no slash, bash first searches
`PATH` for a readable file of that name, and only then (outside POSIX mode) looks in the current
directory. Under the timer the current directory is `/`, so the configuration is not found at all;
in an unlucky `PATH`, a different `report.conf` could be found instead. `. "$conf"` with an absolute
default removes both surprises.

### A redirection happens first

In `{ …; } > "$out"`, the shell opens `$out` for writing — truncating it — before the commands in the
group run. If they then fail, the report is already gone. Writing to a temporary file in the same
directory and renaming it over the report with `mv` only when everything worked means a failure
leaves yesterday's report in place, and a reader never sees a half-written one. `rename(2)` within one
file system is atomic.

### Exit status, again

Nothing in the original script checks that the configuration was read, and its last command is
`echo "report written…"`, which succeeds. So the service's main process exits 0, and systemd records
`Result=success` for a run that produced an empty report. `set -euo pipefail` plus an explicit test
of the configuration file turn "nothing to report" into a failure the unit can show.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, GNU bash 5.3.9, before any change.

Starting the service the way the timer does, and reading its journal:

```console
$ sudo systemctl start nightly-report.service; sudo journalctl -u nightly-report.service -b --no-pager -o cat | tail -4
/opt/reports/bin/nightly-report: line 4: report.conf: No such file or directory
report written to /var/lib/reports/latest.txt
nightly-report.service: Deactivated successfully.
Finished nightly-report.service - Disk use per project, for the morning mail.
```

The script told the journal what went wrong and then told systemd that all was well. The report it
left is a header and nothing else. In an interactive shell, the same script works:

```console
$ sudo bash -ic '/opt/reports/bin/nightly-report' 2>/dev/null; sudo cat /var/lib/reports/latest.txt
report written to /var/lib/reports/latest.txt
Disk use per project, 2026-09-16
/srv/projects/alpha                             300 KiB
/srv/projects/beta                              124 KiB
```

A non-interactive shell as root — no `-i` — fails exactly like the timer, and the start of root's
`.bashrc` shows why:

```console
$ sudo bash -c '/opt/reports/bin/nightly-report' 2>&1; echo "exit status: $?"
/opt/reports/bin/nightly-report: line 4: report.conf: No such file or directory
report written to /var/lib/reports/latest.txt
exit status: 0
$ sudo head -12 /root/.bashrc | grep -n 'interactive' -A3
5:# If not running interactively, don't do anything
6-[ -z "$PS1" ] && return
7-
```

What a service actually starts with can be seen directly, with a transient unit:

```console
$ sudo systemd-run --wait --pipe -q sh -c 'echo "PATH=$PATH"; pwd; echo "HOME=${HOME-unset}"'
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
/
HOME=
```

No `/opt/reports/tools/bin`, and `/` as the working directory. The search rule of `.` is easy to
demonstrate as well — a `report.conf` found through `PATH` wins over none at all:

```console
$ cd /tmp && echo 'echo found the one in PATH' > /tmp/report.conf && PATH=/tmp:$PATH bash -c '. report.conf'
found the one in PATH
```

Finally, what a missing configuration does to the previous report:

```console
$ sudo sh -c 'echo "Disk use per project, yesterday" > /root/old.txt; REPORT_CONF=/nonexistent REPORT_OUT=/root/old.txt /opt/reports/bin/nightly-report 2>&1; echo "exit status: $?"; wc -c /root/old.txt'
/opt/reports/bin/nightly-report: line 4: /nonexistent: No such file or directory
report written to /root/old.txt
exit status: 0
33 /root/old.txt
```

Yesterday's 32-byte report was replaced by today's header, and the exit status is still 0.

After the fix — `PATH` set inside the script, the configuration by absolute default and checked
before use, the report written to a temporary file and renamed — an empty environment is enough:

```console
$ sudo env -i REPORT_OUT=/tmp/new.txt /opt/reports/bin/nightly-report; echo "exit status: $?"; cat /tmp/new.txt
report written to /tmp/new.txt
exit status: 0
Disk use per project, 2026-09-16
/srv/projects/alpha                             300 KiB
/srv/projects/beta                              124 KiB
$ sudo sh -c 'echo "Disk use per project, yesterday" > /root/old.txt; REPORT_CONF=/nonexistent REPORT_OUT=/root/old.txt /opt/reports/bin/nightly-report 2>&1; echo "exit status: $?"; cat /root/old.txt'
nightly-report: cannot read /nonexistent
exit status: 1
Disk use per project, yesterday
```

## Common wrong turns

- **Adding the `PATH` to another start-up file** — `/etc/profile`, `/etc/environment`, root's
  `.profile`. None of them is read by a service. The script still depends on its caller.
- **Fixing only the unit.** `Environment=PATH=…` and `WorkingDirectory=/opt/reports` make the timer's
  run work, and the next person to run the script from cron, from Ansible or from another directory
  meets the same failure. Setting them in the unit as well is fine; relying on them is not.
- **`cd "$(dirname "$0")"` at the top.** It finds the directory of the script, `/opt/reports/bin`,
  which is not where the configuration lives, and `$0` is not reliable when a script is sourced or
  started through a symlink.
- **Testing with `sudo -i`.** An interactive login shell is the one environment the timer never has.
  Test with `env -i` and `systemd-run`.
- **`set -e` alone.** It stops the script at a failed `.`, before the report is touched — but a
  failure inside the redirected group, such as a helper that is not found, comes after the report
  has been truncated. The temporary file is what keeps yesterday's report in every case.
- **Trusting `Result=success`.** It reports an exit status. Read the report, or make the script's exit
  status mean something.

## Cheat sheet

```bash
# at the top of a script that runs unattended
set -euo pipefail
PATH=/opt/reports/tools/bin:/usr/sbin:/usr/bin:/sbin:/bin
conf=${REPORT_CONF:-/opt/reports/report.conf}
[ -r "$conf" ] || { echo "cannot read $conf" >&2; exit 1; }
. "$conf"

# replace output only on success
tmp=$(mktemp "$out.XXXXXX"); trap 'rm -f -- "$tmp"' EXIT
generate > "$tmp" && mv -f -- "$tmp" "$out"

env -i /path/to/script                        # nothing inherited
sudo systemd-run --wait --pipe -q cmd         # exactly what a service gets
systemctl show unit -p Result -p ExecMainStatus
sudo journalctl -u unit -b -o cat             # what the run printed
```

In a unit, when it has to: `Environment=`, `EnvironmentFile=`, `WorkingDirectory=`, `User=`.

## Going deeper

- `man 1 bash`, *INVOCATION*, for exactly which files each kind of shell reads.
- `man 5 systemd.exec`, *Environment variables in spawned processes* and `WorkingDirectory=`.
- `man 1 env` and `man 1 systemd-run`, for reproducing an unattended environment by hand.
- The monitoring journal, [a check is an exit status](../../journals/monitoring/index.html#a-check-is-an-exit-status).

## Review

1. Which of root's start-up files does a service started by systemd read?

   > None. systemd starts the process directly, with its own environment; `.bashrc`, `.profile` and
   > `/etc/environment` belong to shells and logins.

2. Why did the report work in `sudo bash -ic` but not in `sudo bash -c`?

   > Only the interactive shell reads `.bashrc`, and Ubuntu's `.bashrc` returns early in a
   > non-interactive shell, before the lines that extend `PATH` and change directory.

3. What is a service's working directory unless the unit says otherwise?

   > The root directory, `/`.

4. Where does `. report.conf` look for the file?

   > In the directories of `PATH` first, then (outside POSIX mode) in the current directory.

5. Why was yesterday's report emptied even though the run failed?

   > The output redirection truncates the file before the commands that fill it run; writing to a
   > temporary file and renaming it on success keeps the old one.

6. How do you run a command with exactly the environment a systemd service would have?

   > `systemd-run --wait --pipe` runs it as a transient service; `env -i` gives the empty-environment
   > extreme from any shell.
