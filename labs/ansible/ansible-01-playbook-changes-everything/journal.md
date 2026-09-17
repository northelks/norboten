---
title: A playbook describes a state, not a sequence of commands
topics: [ansible, boot-systemd]
minutes: 40
---

The playbook in `/srv/ansible` runs without errors. That is the problem with it: it runs without
errors every single time, reports six changes every single time, restarts the application every
single time, and grows a configuration file by one line every single time. Its `--check` mode skips
five of its seven tasks, so nobody can preview what it will do. And the application listens on 8080
although the inventory says 8081, because a variable set "for testing" in the play outranks the
inventory.

None of that is a bug in Ansible. It is what happens when a playbook is written as a shell script
with YAML around it. `command` and `shell` tasks run commands; they do not know what the machine is
supposed to look like, so they cannot tell whether there is anything to do, they cannot report
honestly whether they changed something, and they cannot predict it in check mode. Ansible's value
comes from **modules**, which compare the desired state with the actual one and act only on the
difference. A playbook built from them **converges**: run it once and the machine matches; run it
again and nothing happens.

## What you should be able to do after this

- Explain idempotence in terms of what a module does: read the current state, compare, change only the
  difference, report `changed` truthfully.
- Recognise tasks that cannot converge — `command`, `shell`, appends — and replace them with the
  builtin module that describes the same state.
- Use handlers so services restart only when their configuration actually changed.
- Find where a variable's value comes from with `ansible … -m debug`, and name which sources outrank
  inventory `group_vars`.
- Use `--check --diff` as a preview, and read its skipped and changed counts.
- Apply kernel parameters persistently and immediately, and know that writing a file in
  `/etc/sysctl.d` does neither by itself at run time.

## The mechanism

### What "idempotent" really means

An operation is idempotent when doing it twice has the same effect as doing it once. For
configuration management the useful form is stronger: a task **describes an end state**, and running
it is a request to make the machine match. The builtin modules implement that in three steps:

1. **Gather** the current state (does the user exist? what is in the file? is the unit enabled?).
2. **Compare** with the parameters of the task.
3. **Act** only if they differ, and set `changed` accordingly.

That third step is what gives `changed` a meaning. On a converged machine every task reports `ok`,
handlers are not notified, and the play recap says `changed=0`. When something drifts, exactly the
tasks that fixed it report `changed`, which is a small, readable audit of what was wrong.

### Why `command` and `shell` cannot converge

```yaml
- name: Enable forwarding for the application's containers
  ansible.builtin.shell: echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.d/90-app.conf
```

Ansible cannot know what an arbitrary command does, so it assumes the worst: every run, the command
runs and the task reports `changed`. An append is the pure form of the problem — each run is a new
line. `useradd app` fails on the second run, which is why it came with `ignore_errors: true`, which
in turn hides the day it fails for a real reason. `cp` always "changes". `systemctl restart` in a
handler notified by a task that always changes restarts the application on every run.

`command` and `shell` are still legitimate, for operations no module covers. They must then be taught
the missing steps:

```yaml
- ansible.builtin.command: /opt/app/bin/migrate
  args:
    creates: /var/lib/app/.migrated        # skip if this exists
- ansible.builtin.command: /opt/app/bin/rotate-keys --dry-run
  register: plan
  changed_when: "'nothing to do' not in plan.stdout"
```

`creates`/`removes` decide whether to run; `changed_when` decides what to report. Without them, a
command task is a statement that the playbook cannot be trusted to converge.

### The module for each job

| What the shell did | What describes the state |
|---|---|
| `useradd …` | `ansible.builtin.user` (`name`, `system`, `home`, `shell`, `create_home`) |
| `mkdir -p` | `ansible.builtin.file` with `state: directory` and a `mode` |
| `cp files/x dest` | `ansible.builtin.copy` with `src` and `mode` |
| `echo … > file`, `printf … > file` | `ansible.builtin.copy` with `content`, or `ansible.builtin.template` |
| `echo … >> file` | `copy`/`template` for a file you own; `lineinfile` for one line in someone else's file |
| `systemctl daemon-reload && enable --now` | `ansible.builtin.systemd_service` with `state`, `enabled`, `daemon_reload` |
| `sysctl -w`, sysctl.d files | a file via `copy` plus a handler, or `ansible.posix.sysctl` if that collection is installed |

`copy` with `content:` manages the *whole* file: whatever duplicates or strays are in it, the next run
replaces them with exactly the content given, and reports `changed` once. That is why it is the right
tool here, and `lineinfile` is not — `lineinfile` would leave the existing duplicates alone.

### Handlers: change-triggered actions

```yaml
    - name: Configuration
      ansible.builtin.template:
        src: templates/app.conf.j2
        dest: /etc/app/app.conf
      notify: Restart app
  handlers:
    - name: Restart app
      ansible.builtin.systemd_service:
        name: app
        state: restarted
```

A task notifies a handler **only when it reports `changed`**. Handlers run once, after the tasks of
the play (or at `meta: flush_handlers`), however many tasks notified them. A handler that is a
`command` with `changed_when: true` is fine: it only runs when something real changed. The restart on
every run in the original came from the notifying task, not from the handler.

### Where a variable's value comes from

Ansible merges variables from many sources, and each source has a fixed rank. The ones that matter
most, from low to high:

```
role defaults  <  inventory group_vars/all  <  inventory group_vars/<group>  <  host_vars
               <  play vars / vars_files     <  role vars  <  block/task vars
               <  set_fact / register        <  extra vars (-e)   ← always wins
```

`group_vars/app.yml` next to the inventory gives `app_port: 8081`. The play has

```yaml
  vars:
    app_port: 8080  # testing — remove before merging
```

and **play vars outrank inventory variables**, so every task in the play sees 8080. The inventory is
not ignored; it is overridden. `ansible <pattern> -m ansible.builtin.debug -a var=app_port` evaluates
the variable from the inventory alone (no play), which is the quickest way to see that the inventory
is right and the play is the culprit.

A useful habit that follows: values that describe a host or group live in the inventory; play and role
`vars` are for constants that should *not* be overridable per host. Anything "temporary" belongs on
the command line as `-e`, where it cannot be committed by accident.

### Check mode and diff

`--check` runs the play without changing anything. Modules that support it report what they would
change. `command` and `shell` cannot be simulated, so Ansible **skips** them in check mode — which is
why `skipped` is as important in a check-mode recap as `changed`: a skipped task is a part of the
playbook that the preview did not see. `--diff` adds a unified diff for file changes.

On a converged host, `ansible-playbook site.yml --check` should say `changed=0 skipped=0` (tasks with
a `when:` condition that is false are the legitimate exception). That single line is a strong test of
a playbook: it proves the tasks describe state and that the machine is in it. It is exactly what the
lab grades, and it never changes the machine.

One subtlety visible in the walkthrough: a handler notified in check mode also runs in check mode.
A `systemd_service` handler reports `changed` ("it would restart"); a `command` handler is skipped.

### Kernel parameters: two places, two moments

`/etc/sysctl.d/*.conf` is read by `systemd-sysctl.service` **at boot**. Writing the file changes
nothing now. `sysctl -w key=value` (or writing to `/proc/sys/…`) changes the running kernel and is
lost at reboot. A correct configuration does both: the file for the next boot, and an apply for now.
`sysctl -p FILE` loads one file; `sysctl --system` reloads them all. In a playbook that is a file task
plus a handler, so the kernel is touched only when the file changed. On Ubuntu `sysctl` lives in
`/usr/sbin`, which is not on an unprivileged user's `PATH`.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. Look at the symptoms before running anything.**

```console
$ cat /etc/sysctl.d/90-app.conf; /usr/sbin/sysctl net.ipv4.ip_forward
net.ipv4.ip_forward = 1
net.ipv4.ip_forward = 1
net.ipv4.ip_forward = 0
$ sudo ss -ltnp | grep python3
LISTEN 0      5          127.0.0.1:8080      0.0.0.0:*    users:(("python3",pid=1512,fd=3))
$ curl -s http://127.0.0.1:8080/; curl -sS http://127.0.0.1:8081/; echo "exit=$?"
inventory service
curl: (7) Failed to connect to 127.0.0.1 port 8081 after 0 ms: Could not connect to server
exit=7
$ systemctl show app -p ActiveEnterTimestamp
ActiveEnterTimestamp=Mon 2026-09-14 03:47:32 UTC
```

Two identical lines in the sysctl file — the playbook has been run twice — and forwarding is still
off in the kernel: nothing ever applied the file. The application answers on 8080, not 8081.

**2. Run the playbook, look again, then preview it.**

```console
$ cd /srv/ansible && sudo ansible-playbook site.yml 2>&1 | tail -n 4

PLAY RECAP *********************************************************************
localhost                  : ok=8    changed=6    unreachable=0    failed=0    skipped=0    rescued=0    ignored=1
$ cat /etc/sysctl.d/90-app.conf; systemctl show app -p ActiveEnterTimestamp
net.ipv4.ip_forward = 1
net.ipv4.ip_forward = 1
net.ipv4.ip_forward = 1
ActiveEnterTimestamp=Mon 2026-09-14 03:47:34 UTC
$ cd /srv/ansible && sudo ansible-playbook site.yml --check 2>&1 | grep -E '^(TASK|changed|ok|skipping)|localhost'
TASK [Gathering Facts] *********************************************************
ok: [localhost]
TASK [Create the app account] **************************************************
skipping: [localhost]
TASK [Enable forwarding for the application's containers] **********************
skipping: [localhost]
TASK [Install the application] *************************************************
skipping: [localhost]
TASK [Write the configuration] *************************************************
skipping: [localhost]
TASK [Install the unit] ********************************************************
ok: [localhost]
TASK [Start the application] ***************************************************
skipping: [localhost]
localhost                  : ok=2    changed=0    unreachable=0    failed=0    skipped=5    rescued=0    ignored=0
```

On an unchanged machine: six changes, one ignored failure (the second `useradd`), a third line in the
file, and a new `ActiveEnterTimestamp` — the application restarted for nothing. Check mode skips five
tasks and reports `changed=0`, which looks reassuring and means only "I did not look".

**3. Find where the port comes from.**

```console
$ cat /srv/ansible/inventory.ini /srv/ansible/group_vars/app.yml
[app]
localhost ansible_connection=local
---
app_port: 8081
app_greeting: inventory service
$ cd /srv/ansible && ansible app -m ansible.builtin.debug -a var=app_port
localhost | SUCCESS => {
    "app_port": 8081
}
$ sed -n 1,12p /srv/ansible/site.yml
---
- name: Configure the application host
  hosts: app
  become: true
  vars:
    app_port: 8080  # testing — remove before merging
  tasks:
    - name: Create the app account
      ansible.builtin.command: useradd --system --home-dir /opt/app --shell /usr/sbin/nologin app
      ignore_errors: true

    - name: Enable forwarding for the application's containers
```

The inventory alone resolves `app_port` to 8081. The play's own `vars` sets 8080, and play vars
outrank inventory variables.

**4. Rewrite the playbook with modules.** No play `vars`, one module per piece of state, and handlers
for the two things that should follow a change:

```yaml
---
- name: Configure the application host
  hosts: app
  become: true
  tasks:
    - name: App account
      ansible.builtin.user:
        name: app
        system: true
        home: /opt/app
        create_home: false
        shell: /usr/sbin/nologin

    - name: Forwarding for the application's containers
      ansible.builtin.copy:
        dest: /etc/sysctl.d/90-app.conf
        content: "net.ipv4.ip_forward = 1\n"
        mode: "0644"
      notify: Apply sysctl

    - name: Application directory
      ansible.builtin.file:
        path: /opt/app
        state: directory
        mode: "0755"

    - name: Application
      ansible.builtin.copy:
        src: files/app.py
        dest: /opt/app/app.py
        mode: "0644"
      notify: Restart app

    - name: Configuration directory
      ansible.builtin.file:
        path: /etc/app
        state: directory
        mode: "0755"

    - name: Configuration
      ansible.builtin.template:
        src: templates/app.conf.j2
        dest: /etc/app/app.conf
        mode: "0644"
      notify: Restart app

    - name: Unit
      ansible.builtin.copy:
        src: files/app.service
        dest: /etc/systemd/system/app.service
        mode: "0644"
      notify: Restart app

    - name: Application running and enabled
      ansible.builtin.systemd_service:
        name: app
        state: started
        enabled: true
        daemon_reload: true

  handlers:
    - name: Apply sysctl
      ansible.builtin.command: sysctl -p /etc/sysctl.d/90-app.conf
      changed_when: true

    - name: Restart app
      ansible.builtin.systemd_service:
        name: app
        state: restarted
        daemon_reload: true
```

**5. Preview, apply, apply again, preview again.**

```console
$ cd /srv/ansible && sudo ansible-playbook site.yml --check --diff 2>&1 | grep -vE '^\s*$'
PLAY [Configure the application host] ******************************************
TASK [Gathering Facts] *********************************************************
ok: [localhost]
TASK [App account] *************************************************************
ok: [localhost]
TASK [Forwarding for the application's containers] *****************************
--- before: /etc/sysctl.d/90-app.conf
+++ after: /etc/sysctl.d/90-app.conf
@@ -1,3 +1 @@
 net.ipv4.ip_forward = 1
-net.ipv4.ip_forward = 1
-net.ipv4.ip_forward = 1
changed: [localhost]
TASK [Application directory] ***************************************************
ok: [localhost]
TASK [Application] *************************************************************
ok: [localhost]
TASK [Configuration directory] *************************************************
ok: [localhost]
TASK [Configuration] ***********************************************************
--- before: /etc/app/app.conf
+++ after: /root/.ansible/tmp/ansible-local-21777amddf4y/tmp669hmsui/app.conf.j2
@@ -1,2 +1,3 @@
-port = 8080
+# managed by Ansible — /srv/ansible
+port = 8081
 greeting = inventory service
changed: [localhost]
TASK [Unit] ********************************************************************
ok: [localhost]
TASK [Application running and enabled] *****************************************
ok: [localhost]
RUNNING HANDLER [Apply sysctl] *************************************************
skipping: [localhost]
RUNNING HANDLER [Restart app] **************************************************
changed: [localhost]
PLAY RECAP *********************************************************************
localhost                  : ok=10   changed=3    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0
```

The preview now covers every task and says exactly what will change: the duplicate lines go, the port
becomes 8081. The existing `app` account, directories, application file and unit already match, so
those tasks are `ok`. The one skip is the `command` handler, which check mode cannot simulate.

```console
$ cd /srv/ansible && sudo ansible-playbook site.yml 2>&1 | grep -E '^(TASK|RUNNING|changed|ok)|localhost'
TASK [Gathering Facts] *********************************************************
ok: [localhost]
TASK [App account] *************************************************************
ok: [localhost]
TASK [Forwarding for the application's containers] *****************************
changed: [localhost]
TASK [Application directory] ***************************************************
ok: [localhost]
TASK [Application] *************************************************************
ok: [localhost]
TASK [Configuration directory] *************************************************
ok: [localhost]
TASK [Configuration] ***********************************************************
changed: [localhost]
TASK [Unit] ********************************************************************
ok: [localhost]
TASK [Application running and enabled] *****************************************
ok: [localhost]
RUNNING HANDLER [Apply sysctl] *************************************************
changed: [localhost]
RUNNING HANDLER [Restart app] **************************************************
changed: [localhost]
localhost                  : ok=11   changed=4    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
$ cd /srv/ansible && sudo ansible-playbook site.yml 2>&1 | tail -n 3
PLAY RECAP *********************************************************************
localhost                  : ok=9    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
$ cd /srv/ansible && sudo ansible-playbook site.yml --check 2>&1 | tail -n 3
PLAY RECAP *********************************************************************
localhost                  : ok=9    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

The real run changed two things and ran both handlers once. The second run changed nothing and ran no
handlers. Check mode on the converged machine: `changed=0 skipped=0`.

**6. Confirm the result on the machine.**

```console
$ cat /etc/sysctl.d/90-app.conf /etc/app/app.conf; /usr/sbin/sysctl net.ipv4.ip_forward; curl -s http://127.0.0.1:8081/
net.ipv4.ip_forward = 1
# managed by Ansible — /srv/ansible
port = 8081
greeting = inventory service
net.ipv4.ip_forward = 1
inventory service
```

**7. Grade.** The checks — including the check-mode run — passed before and after the reboot.

## Common wrong turns

**Deleting the `vars:` block and changing nothing else.** The port is fixed, but the playbook still
appends, restarts on every run and hides in check mode.

**`lineinfile` for the sysctl setting.** It stops new duplicates but leaves the two that already exist,
so the file keeps three lines. For a file the playbook owns, manage the whole content.

**`changed_when: false` on the shell tasks.** The recap becomes `changed=0`, and the tasks still append
and restart on every run. It silences the report without making the task describe a state, and check
mode still skips them.

**`check_mode: false` on the shell tasks "so --check does not skip them".** Then `--check` really
runs them — and changes the machine during what everybody believes is a dry run.

**Keeping `ignore_errors: true` on the account task.** With `ansible.builtin.user` there is no error to
ignore; with `ignore_errors` left in place, a genuine failure (a UID clash, a locked `/etc/passwd`)
passes silently.

**Setting the port with `-e app_port=8081` in the documentation.** It works because extra vars win,
and it hides the conflict instead of removing it. The next person who forgets `-e` gets 8080.

**Writing the sysctl file and expecting the kernel to follow.** The file is read at boot. Without a
handler (or `sysctl --system`) the value is only right after the next reboot — the grader checks the
running kernel too.

**Restarting through `ansible.builtin.command: systemctl restart app`.** It works as a handler, but
`systemd_service` with `state: restarted` also runs `daemon-reload` when asked and reports clearly;
use the module.

## Cheat sheet

```console
$ ansible-playbook site.yml --check --diff          # preview; watch changed AND skipped
$ ansible-playbook site.yml                          # apply
$ ansible-playbook site.yml | tail -n 3              # the recap: a second run should be changed=0
$ ansible-playbook site.yml --list-tasks             # what would run, without running it
$ ansible-playbook site.yml --start-at-task "Configuration"
$ ansible app -m ansible.builtin.debug -a var=app_port     # a variable from the inventory alone
$ ansible-inventory --host localhost                 # all inventory variables for a host
$ ansible-doc ansible.builtin.copy                   # a module's parameters and examples
$ /usr/sbin/sysctl net.ipv4.ip_forward               # the running value
$ sudo sysctl -p /etc/sysctl.d/90-app.conf           # apply one file now
$ systemctl show app -p ActiveEnterTimestamp         # did the service restart?
```

```yaml
# a command that converges
- ansible.builtin.command: /usr/local/bin/init-db
  args: {creates: /var/lib/db/.initialised}
# a command that reports honestly
- ansible.builtin.command: some-tool status
  register: out
  changed_when: false
# restart only on change
- ansible.builtin.template: {src: app.conf.j2, dest: /etc/app/app.conf}
  notify: Restart app
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *A green run is not a correct machine* (topic journal `ansible`) — Variable precedence, the parts that bite
- *A green run is not a correct machine* (topic journal `ansible`) — Idempotence is a property of each task
- *A green run is not a correct machine* (topic journal `ansible`) — Handlers: a notification is a promise kept at the end
- *A green run is not a correct machine* (topic journal `ansible`) — shell and command report changed because they cannot know
- *A green run is not a correct machine* (topic journal `ansible`) — Check mode, and what it cannot see

The whole subject, end to end: the topic journal *A green run is not a correct machine* (`ansible`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. What three steps does a state module perform that a `command` task does not?

   > It reads the current state, compares it with the desired state from its parameters, and changes only the difference — reporting `changed` only when it acted.

2. Why did check mode report `changed=0` on the original playbook, and why is that misleading?

   > Five of the seven tasks were `command`/`shell` tasks, which check mode cannot simulate and therefore skips; `changed=0` only reflects the two tasks it did evaluate.

3. `group_vars/app.yml` sets `app_port: 8081` and the play sets `vars: app_port: 8080`. Which value do tasks see, and how do you prove the inventory value?

   > 8080 — play vars outrank inventory group_vars. `ansible app -m ansible.builtin.debug -a var=app_port` shows the inventory's 8081 without the play.

4. Why is `copy` with `content:` the right fix for the duplicated sysctl lines, and `lineinfile` not?

   > `copy` manages the whole file, so it removes the existing duplicates and reports changed once; `lineinfile` only ensures one matching line exists and leaves the other copies.

5. When does a handler run, and how many times?

   > Only if at least one task that notifies it reports `changed`; once per host, after the play's tasks (or at `meta: flush_handlers`), no matter how many tasks notified it.

6. What does a playbook recap of `changed=0 skipped=0` from `--check` prove on a configured host?

   > That every task could be evaluated without being skipped, and that none of them would change anything: the playbook describes state and the machine is already in it.

7. After a play writes `/etc/sysctl.d/90-app.conf`, why can `sysctl net.ipv4.ip_forward` still print 0?

   > The file is only read at boot by systemd-sysctl; the running kernel changes only when the value is applied, e.g. with `sysctl -p FILE` or `sysctl --system`.

8. Why is `changed_when: false` on an appending `shell` task not a fix?

   > It only changes the report; the task still appends on every run and is still skipped in check mode.
