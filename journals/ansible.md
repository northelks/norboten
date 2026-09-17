---
title: A green run is not a correct machine
topics: [ansible]
minutes: 40
covers: >-
  idempotence per module; command/shell with creates and changed_when; lineinfile regexp; handlers and --force-handlers; check mode and diff; variable precedence; vault passwords without a terminal
---

Ansible's whole promise is a sentence: *describe the state you want, and running the playbook again
changes nothing*. Every useful property follows from it — you can re-run after a failure, run against
a fleet where half the machines are already right, and read `changed=0` as proof that nothing drifted.
Break that promise in one task and the others do not save you: the recap turns into noise, check mode
lies, and a restart that should have happened quietly never does.

This journal is built on a small role with four mistakes that appear in real playbooks every day,
each run against a lab machine with ansible-core 2.21 and recorded. None of them produces a
red line on a normal run. That is the point. A playbook that fails loudly is easy; the ones worth
studying are the ones that pass.

## What you should be able to do after this

- Say what idempotence means for a task, and read a play recap to tell whether a playbook has it.
- Recognise the three module choices that break idempotence — `shell`/`command` without guards,
  `lineinfile` used as a file editor, restarts written as tasks — and replace each with the module that
  owns the state.
- Explain exactly when a handler runs, what happens to a notification when the play fails first, and
  why a restart can be lost for good.
- Use `--check` and `--diff` and know which tasks check mode silently skips.
- Predict which value a variable takes when it is set in role defaults, `group_vars`, play `vars`
  and `-e`.

## The mechanism

### Idempotence is a property of each task

A task is idempotent when running it against a machine already in the desired state reports `ok` and
touches nothing. The play recap is the summary of that promise:

```
PLAY RECAP *********************************************************************
web01                      : ok=5    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

Run a correct playbook twice: the first run may say `changed=3`, and the second must say `changed=0`.
A second run that still reports changes means one of two things — something on the machine really is
fighting the playbook, or the playbook is lying about state — and it is nearly always the second.
**Run twice** is the cheapest test there is, and the one that finds everything in this journal.

Modules achieve idempotence by comparing first and acting second. `ansible.builtin.file` checks mode and
ownership before changing them; `template` renders the file, compares it with the one on the host, and
writes only when they differ; `systemd_service` asks systemd whether the unit is already running.
The modules that cannot compare are the ones that run arbitrary commands.

### `shell` and `command` report `changed` because they cannot know

```yaml
- name: Log level
  ansible.builtin.shell: echo "LOG_LEVEL={{ app_log_level }}" >> /etc/app/app.env
```

Ansible has no idea what a shell command does, so it assumes it did something: the task reports
`changed` on every run, and here it is also *true* — every run appends another line. After a few runs
the file on the lab machine read:

```
LOG_LEVEL=info
PORT=8081
LOG_LEVEL=info
LOG_LEVEL=info
LOG_LEVEL=info
PORT=8082
```

When a command is genuinely needed, it has to be taught about state:

- `creates:` / `removes:` — skip the task if a path exists (or does not);
- `changed_when:` — decide from the output whether anything changed (`changed_when: false` for a
  read-only command, a condition on `result.stdout` otherwise);
- `register:` plus `when:` — run it only if an earlier check said it is needed.

But the better answer is usually a module that owns the state, and for a file that means the next
section.

### `lineinfile` is for one line in a file you do not own

`lineinfile` makes sure a line is present. Without `regexp` it matches the *whole line*, so changing a
value adds a new line instead of replacing the old one — which is how the file above grew a second
`PORT=`. With `regexp` it replaces the matching line, and the natural fix looks like this:

```yaml
- name: Port
  ansible.builtin.lineinfile:
    path: /etc/app/app.env
    regexp: "^PORT="
    line: "PORT={{ app_port }}"
```

On the lab machine, against the file already full of duplicates, that fix reported `ok` for the
log level and edited one `PORT=` line — **only the last match is replaced**, so the duplicates stayed,
and the file ended with two `PORT=8081` lines. `lineinfile` is right for adding one setting to a file
some other package owns (`/etc/ssh/sshd_config`, say). For a file your role owns completely, own it
completely:

```yaml
- name: Environment file
  ansible.builtin.template:
    src: app.env.j2
    dest: /etc/app/app.env
    mode: "0644"
  notify: Restart app
```

```jinja
# {{ ansible_managed }}
LOG_LEVEL={{ app_log_level }}
PORT={{ app_port }}
```

A template states the whole file, so duplicates, stale settings and hand edits all disappear on the
next run — and `--diff` shows exactly what went:

```diff
--- before: /etc/app/app.env
+++ after: …/app.env.j2
@@ -1,6 +1,3 @@
+# Ansible managed
 LOG_LEVEL=info
 PORT=8081
-LOG_LEVEL=info
-LOG_LEVEL=info
-LOG_LEVEL=info
-PORT=8081
```

`{{ ansible_managed }}` renders as `Ansible managed` by default: a note to the next person that hand
edits will be overwritten.

### Handlers: a notification is a promise kept at the end

A task notifies a handler; the handler runs **once, at the end of the play**, however many tasks
notified it, and only if at least one of them reported `changed`:

```
TASK [app : Environment file] ***
changed: [web01]
TASK [app : Unit file] ***
ok: [web01]
TASK [app : App is enabled and running] ***
changed: [web01]
RUNNING HANDLER [app : Restart app] ***
changed: [web01]
```

That is why a restart belongs in a handler rather than in the task list. Written as a task —
`ansible.builtin.command: systemctl restart app` — it runs on every play, reports `changed` every time,
and restarts a healthy service for no reason. As a handler it runs exactly when configuration changed.

Three details decide whether handlers work at all:

**The name must match exactly.** Handler lookup is case-sensitive. A role whose handler is named
`Restart app` and whose task says `notify: restart app` fails — but only when the notification fires:

```
TASK [app : Unit file] ***
[ERROR]: The requested handler 'restart app' was not found in either the main handlers list nor in the listening handlers list
```

On the lab machine the task had already written the unit file when the play died. The second run found
the file unchanged, so nothing notified, so nothing failed: the playbook went green with the bug still
in it. A broken handler name only shows itself on runs that change something. (`listen:` on a handler
gives it a topic name several tasks can notify, which is sturdier than matching titles.)

**A failure before the end means the handlers do not run.** The notification is held in memory until
the handlers section, and a failed task ends the play for that host before it gets there. On the lab
machine, a template changed the log level to `debug`, a later task failed, and the service was not
restarted — its `ActiveEnterTimestamp` did not move.

**That restart is not retried.** The notification existed only in that run. On the next run the
template finds the file already says `debug`, reports `ok`, notifies nothing, and the play finishes
with `changed=0` — while the service is still running with the old configuration:

```
TASK [Environment file] ***
ok: [web01]
PLAY RECAP ***
web01                      : ok=3    changed=0    unreachable=0    failed=0    …
after both runs, service last started: Sun 2026-09-13 08:10:03 UTC     ← before the change
LOG_LEVEL=debug
```

A perfectly clean recap over a machine that is not in the state it describes. The defences:
`--force-handlers` (run notified handlers even when the play fails — verified: the handler ran and the
recap still said `failed=1`), `meta: flush_handlers` at the points where a restart must happen before
the next step, and designing validation into the change itself (`validate:` on `template`, a health
check after the restart) so that a failure stops the play *before* the file is replaced.

### Check mode, and what it cannot see

`ansible-playbook site.yml --check --diff` runs the play without changing the host: modules report what
they *would* do, and `--diff` shows the file differences. It is the right thing to run before any change
to production — with one blind spot that matters here. Modules that cannot predict their effect do not
run in check mode at all:

```
TASK [app : Log level] ***
skipping: [web01]
TASK [app : Restart the app] ***
skipping: [web01]
```

The appending `shell` task and the restart-as-a-task — the two worst tasks in the role — are exactly
the two check mode skipped. A clean `--check` says nothing about `shell` and `command`. If a command
is safe to run in check mode (a read-only query), mark it `check_mode: false`, and give it
`changed_when: false` so it does not pollute the recap.

### Variable precedence, the parts that bite

Ansible has more than twenty precedence levels; four cover nearly every surprise. Verified on the lab
machine, lowest to highest:

| where | value set | what the play saw |
|---|---|---|
| `roles/app/defaults/main.yml` | `app_port: 8080` | overridden |
| `group_vars/web.yml` | `app_port: 8081` | `PORT=8081` in the file |
| play `vars:` | `app_port: 9000` | `"app_port": 9000` |
| `-e app_port=9999` | | `"app_port": "9999"` |

Role **defaults** are the lowest thing there is — that is their job: a value the user of the role is
expected to override. Inventory `group_vars` beat them. Play `vars:` beat inventory. Extra vars (`-e`)
beat everything, and note the quotes in that last row: a `key=value` on the command line is a
**string**, so `-e app_port=9999` gives `"9999"`, and a template doing arithmetic or a comparison on it
may behave differently than with the integer from a file. `-e '{"app_port": 9999}'` passes JSON and
keeps the type.

Role `vars/main.yml` (as opposed to `defaults/`) sits near the top of the list, above inventory, which is
why a value that "will not change no matter what I put in group_vars" is usually hiding there.

## A failure, walked through

The role configures a small service: a directory, an environment file, a unit, a restart. Someone
reports that changing the port "sometimes does not take", and that the playbook has "always been
green".

**1. Run it, twice, and read only the recaps.**

```console
$ ansible-playbook site.yml
TASK [app : Unit file] ***
[ERROR]: The requested handler 'restart app' was not found in either the main handlers list nor in the listening handlers list
$ ansible-playbook site.yml | tail -2
web01                      : ok=6    changed=2    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

The first run fails; the second, immediately after, is green with `changed=2`. Two facts: the handler
name is wrong but only fails when something changes, and a second run on an unchanged machine still
changes two things — the playbook is not idempotent.

**2. Find which tasks change on a run that should change nothing.**

```console
$ ansible-playbook site.yml | grep -B1 changed:
TASK [app : Log level] ***
changed: [web01]
TASK [app : Restart the app] ***
changed: [web01]
```

A `shell` append and a `command` restart. Look at what the first one has been doing:

```console
$ ansible web -b -m command -a "cat /etc/app/app.env"
web01 | CHANGED | rc=0 >>
LOG_LEVEL=info
PORT=8081
LOG_LEVEL=info
LOG_LEVEL=info
```

(`CHANGED` there is the ad-hoc `command` module saying what it always says; it changed nothing.)

**3. Ask check mode, and notice what it does not say.**

```console
$ ansible-playbook site.yml --check --diff | grep -A1 'Log level\|Restart the app'
TASK [app : Log level] ***
skipping: [web01]
TASK [app : Restart the app] ***
skipping: [web01]
```

Check mode skips both culprits, so it cannot be the tool that finds them. The recap of two real runs
already has.

**4. Reproduce "the port sometimes does not take".**

```console
$ ansible-playbook site.yml -e app_port=8082 | tail -1
web01                      : ok=6    changed=3    …
$ ansible web -b -m command -a "cat /etc/app/app.env"
LOG_LEVEL=info
PORT=8081
LOG_LEVEL=info
LOG_LEVEL=info
LOG_LEVEL=info
PORT=8082
```

`lineinfile` without `regexp` appended a second `PORT=`. Which one the service uses depends on how it
reads the file — for systemd's `EnvironmentFile=` the last assignment wins, for another program perhaps
the first. "Sometimes does not take" is a precise description.

**5. Try the obvious fix, and watch it be half right.** Adding `regexp: "^PORT="` and
`regexp: "^LOG_LEVEL="` and running with the original port:

```console
$ ansible-playbook site.yml --diff
TASK [app : Log level] ***
ok: [web01]
TASK [app : Port] ***
@@ -3,4 +3,4 @@
 LOG_LEVEL=info
 LOG_LEVEL=info
 LOG_LEVEL=info
-PORT=8082
+PORT=8081
changed: [web01]
$ ansible web -b -m command -a "cat /etc/app/app.env"
LOG_LEVEL=info
PORT=8081
LOG_LEVEL=info
LOG_LEVEL=info
LOG_LEVEL=info
PORT=8081
```

Only the last match changed. The task is idempotent now, and the file is still wrong — idempotence
means the playbook stops making it worse, not that it repairs what is already there.

**6. Own the file, fix the handler, delete the restart task.**

```yaml
- name: Environment file
  ansible.builtin.template:
    src: app.env.j2
    dest: /etc/app/app.env
    mode: "0644"
  notify: Restart app            # exactly the handler's name

- name: Unit file
  ansible.builtin.copy:
    dest: /etc/systemd/system/app.service
    content: |
      …
    mode: "0644"
  notify: Restart app

- name: App is enabled and running
  ansible.builtin.systemd_service:
    name: app
    enabled: true
    state: started
```

The first run with it replaces the file (the `--diff` above shows six lines becoming three), enables
the service, and runs the handler once at the end.

**7. The proof: run it again, and in check mode.**

```console
$ ansible-playbook site.yml | tail -1
web01                      : ok=5    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
$ ansible-playbook site.yml --check | tail -1
web01                      : ok=5    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

`changed=0` twice, and check mode now agrees with reality because there is no task left that it has to
skip.

**8. Close the last hole: a failure between the change and the restart.** With a template that sets
`debug` followed by a task that fails, the file changed and the service was not restarted; running the
same play again reported `changed=0` and restarted nothing. The service stayed on the old
configuration with a green recap. For plays that change running services, run with
`--force-handlers`, or put `meta: flush_handlers` directly after the tasks whose restart must not be
lost.

## Common wrong turns

**Trusting a green run.** Green means no task failed. It does not mean the machine is in the described
state, and it does not mean the playbook is idempotent. `changed=0` on a second run is the evidence.

**`shell: echo … >> file`.** It reports `changed` every run because it is changing something every
run. Use `template` for a file you own, `lineinfile` with `regexp` for one line in a file you do not.

**`lineinfile` without `regexp` for a value that changes.** It matches the whole line, so a new value is
a new line. And with `regexp`, remember that only the last match is replaced — it will not clean up a
file that already has duplicates.

**Restarting in the task list.** `command: systemctl restart app` restarts on every run and reports
`changed` every time. Notify a handler.

**Fixing a handler error by re-running.** The second run is green because nothing changed, not because
the name matches. Handler names are case-sensitive; check them against the handler file, or use
`listen:`.

**Assuming the next run will do the restart a failed run missed.** The notification was lost with the
run. The next run sees the file already correct, notifies nothing and reports `changed=0`.
`--force-handlers`, `meta: flush_handlers`, or restart by hand and verify.

**Reading a clean `--check` as a clean playbook.** `shell` and `command` tasks are skipped in check mode,
so the most dangerous tasks are the ones it never evaluates.

**`changed_when: false` on a command that does change things**, to make the recap quiet. The recap is
then accurate about nothing. Use it for read-only commands only.

**Putting overridable values in `vars/main.yml`.** Role vars outrank inventory, so the user of the role
cannot override them from `group_vars`. Values meant to be overridden go in `defaults/main.yml`.

**Passing numbers with `-e key=value`.** They arrive as strings. Pass JSON (`-e '{"app_port": 9999}'`)
when the type matters.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| every run reports `changed` for the same tasks | `command`/`shell` tasks with no `creates`, `removes` or `changed_when` | `ansible-playbook -v`; the tasks marked changed on a second run |
| a line appears in a file twice, or keeps being rewritten | `lineinfile` with a `regexp` that does not match the line it writes | `--check --diff` on a converged host |
| a service is not restarted after its configuration changed | the handler was never notified, or the play failed before handlers ran | `-v` output for `RUNNING HANDLER`; `--force-handlers` |
| a variable has a different value than the inventory says | a higher-precedence source wins: play `vars`, `set_fact`, `-e` | `ansible -m debug -a var=NAME HOST`; the precedence list |
| `--check` passes, the real run fails | a task depends on a result that check mode could not produce | tasks with `check_mode: false`, or registered results in check mode |
| a deploy waits for a password and never finishes | vault, `become` or SSH asking on a terminal the job does not have | `ansible.cfg`: `ask_vault_pass`, `become_ask_pass`; the job's arguments |

## Cheat sheet

```console
# the two tests that matter
ansible-playbook site.yml && ansible-playbook site.yml | tail -1     # second run: changed=0
ansible-playbook site.yml --check --diff                              # what would change, as a diff
#   (shell/command tasks are SKIPPED in check mode; check_mode: false to run read-only ones)

# narrowing down
ansible-playbook site.yml | grep -B1 changed:     # which tasks change on a no-op run
ansible-playbook site.yml --list-tasks
ansible-playbook site.yml --start-at-task "Environment file"
ansible-playbook site.yml -l web01 -v             # one host, more output
ansible web -m ping ; ansible web -b -m command -a "cat /etc/app/app.env"   # ad hoc

# handlers
# notify: Restart app          ← must equal the handler's name exactly (or use listen:)
ansible-playbook site.yml --force-handlers        # run notified handlers even if the play fails
# - ansible.builtin.meta: flush_handlers          ← run pending handlers now, mid-play

# modules that own state instead of commands that guess
# template            a whole file you own (with {{ ansible_managed }} at the top)
# lineinfile + regexp one line in a file someone else owns (replaces the LAST match only)
# systemd_service     enabled / state: started|restarted, daemon_reload
# command/shell       creates:, removes:, changed_when:, register: + when:

# variables, low to high (the four that bite)
# roles/x/defaults/main.yml < inventory group_vars < play vars: < -e (extra vars, strings!)
# roles/x/vars/main.yml outranks inventory — do not put overridable values there
ansible-playbook site.yml -e '{"app_port": 9999}'   # JSON keeps the type
ansible web -m ansible.builtin.debug -a "var=app_port"
```

## Exercises

1. Run a playbook twice and count `changed` on the second run; make every task report `ok` without
   removing any.
2. Write a `lineinfile` task whose `regexp` does not match its own `line`, run it three times, and read
   the file.
3. Define the same variable in group_vars, host_vars, the play's `vars` and `-e`, and print it with the
   `debug` module after removing each in turn.
4. Make a configuration change that notifies a handler, then make a later task fail. Did the handler
   run? Try again with `--force-handlers`.
5. Run a play that registers a command's output and uses it, with `--check`. Which task breaks, and how
   does `check_mode: false` on the first one change that?

## Sources

- Variables and their precedence: https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html
- Handlers: https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_handlers.html
- Check mode and diff: https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_checkmode.html
- Vault passwords without a terminal: https://docs.ansible.com/ansible/latest/vault_guide/vault_managing_passwords.html
- `ansible-doc lineinfile`, `ansible-doc command` — every option, on the machine itself.

## Review

1. A playbook reports `changed=2` on a second run immediately after the first. What does that tell you,
   and what is the most likely cause?

   > The playbook is not idempotent: on a machine already in the desired state it still claims — or
   > makes — changes. The usual cause is `shell` or `command` tasks, which Ansible cannot compare
   > against state and therefore always report as changed (and which may really be changing things,
   > like appending a line on every run).

2. You replace `lineinfile: line: "PORT={{ app_port }}"` with the same task plus `regexp: "^PORT="`. The
   file already contains `PORT=8081` twice. What happens, and what is the better fix?

   > Only the last matching line is replaced; the earlier duplicate stays, so the task becomes
   > idempotent while the file remains wrong. For a file the role owns, use `template` to state the whole
   > file, which removes duplicates and hand edits on the next run.

3. A play fails with *The requested handler 'restart app' was not found*. You run it again and it
   succeeds. Is the bug fixed?

   > No. The first run changed the file and fired the notification, which failed on the name (handler
   > names are case-sensitive: `restart app` ≠ `Restart app`). The second run changed nothing, so nothing
   > notified and nothing failed. The error returns on the next run that changes that file.

4. A template changes a service's configuration, a later task fails, and the next run of the playbook
   reports `changed=0`. Is the service running with the new configuration?

   > No. Handlers run at the end of the play, so the failure prevented the restart, and the notification
   > was not saved. On the next run the template finds the file already correct, reports `ok`, notifies
   > nothing — the restart is lost. Use `--force-handlers` or `meta: flush_handlers`, or restart and
   > verify by hand.

5. Why can `ansible-playbook --check` report a clean run for a playbook that appends to a file on every
   real run?

   > Modules that cannot predict their effect — `shell` and `command` — are skipped in check mode. The
   > appending task never runs, so check mode has nothing to report about it.

6. `app_port` is 8080 in role defaults, 8081 in `group_vars/web.yml`, and 9000 in the play's `vars:`.
   Which value does the play use, and what changes with `-e app_port=9999`?

   > 9000: play `vars:` beat inventory `group_vars`, which beat role defaults. `-e` beats all of them,
   > but a `key=value` extra var is a string, `"9999"`; pass JSON (`-e '{"app_port": 9999}'`) to keep
   > it an integer.

7. What is the difference between `roles/app/defaults/main.yml` and `roles/app/vars/main.yml`, and
   which one should hold a value users of the role are expected to change?

   > Defaults have the lowest precedence of anything, so inventory and play variables override them;
   > role vars sit above inventory and are hard to override. Overridable values belong in `defaults/`.

8. Why should a service restart be a handler rather than a `command: systemctl restart` task?

   > As a task it runs on every play, always reports `changed`, and restarts a healthy service for
   > nothing. As a handler it runs once, at the end, and only when a task that affects the service
   > actually changed something.
