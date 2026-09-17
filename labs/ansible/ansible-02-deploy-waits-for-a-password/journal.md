---
title: Automation that needs a person is not automation
topics: [ansible, users-permissions]
minutes: 40
---

`deploy.service` runs a playbook at every boot to render the application's database settings. The
password comes from an Ansible Vault file, and the project's `ansible.cfg` says `ask_vault_pass =
true`. That works perfectly when a person runs the playbook from a terminal, types the password, and
watches. At boot there is no terminal and no person, Ansible's prompt reads end-of-file, and the
application starts with no database settings. Someone "fixed" it on another machine by running the
playbook by hand — which proves the playbook works and fixes nothing about the service.

While debugging, the same person saved a decrypted copy of the vault next to the encrypted one, to
read it, and the playbook has a debug task that prints the password into whatever log captures its
output. So the machine had three secret-handling problems at once: the secret could not be reached by
the automation that needed it, it could be reached by anyone who could read the project directory, and
it would be written to the journal the moment the automation worked.

This journal is about running Ansible Vault unattended without weakening it: who holds the vault
password, where it lives, what else must never contain the secret, and how to check each of those
claims on the machine.

## What you should be able to do after this

- Explain what Ansible Vault encrypts, what the vault password protects, and why whoever can read the
  password file can read every secret.
- Run a playbook that uses vault content from a service, with `vault_password_file` (or its
  equivalents), and no prompt.
- Give an unattended account exactly the access it needs: its own copy of the password, owned by it,
  mode 0400 or 0600, not executable.
- Find plaintext copies of a secret on disk, and understand why Ansible ignored the one in
  `group_vars` while a person could still read it.
- Keep secrets out of logs: debug output, module arguments and diffs, and `no_log`.
- Read a single run of a systemd service in the journal with its invocation ID.

## The mechanism

### What Vault is, and what it is not

Ansible Vault encrypts data at rest with a symmetric key derived from a password: a whole file
(`ansible-vault encrypt file.yml`) or single values (`ansible-vault encrypt_string`). An encrypted
file starts with a header such as `$ANSIBLE_VAULT;1.1;AES256`. When a playbook loads vault content,
Ansible decrypts it in memory with the vault password and uses the values like any other variable.

Two consequences follow, and both matter here:

- **The vault password is the secret now.** Encryption moves the problem from "protect the database
  password" to "protect the vault password". Anyone who has it can decrypt every vault file encrypted
  with it.
- **Decrypted values are ordinary variables at run time.** Vault does nothing to stop them from being
  printed, templated into a world-readable file, or logged.

### How Ansible gets the vault password

| Source | Unattended? |
|---|---|
| `--ask-vault-pass` on the command line, or `ask_vault_pass = true` in `ansible.cfg` | no: prompts on the terminal |
| `--vault-password-file PATH`, or `vault_password_file = PATH` in `ansible.cfg` | yes |
| `ANSIBLE_VAULT_PASSWORD_FILE=PATH` in the environment | yes |
| `--vault-id label@PATH` (several vaults, several passwords) | yes |

A password file holds the password on its first line. **If the file is executable, Ansible runs it**
and uses its output — the hook for password managers and secret stores (`vault-keyring-client`, a
script that calls an API). A plain password file must therefore *not* be executable, or Ansible will
try to execute a line of random characters.

Under systemd, `ask_vault_pass` cannot work: the service's standard input is `/dev/null` and there is
no controlling terminal. Python's `getpass` warns that it cannot control echo, reads end-of-file, and
Ansible fails with `EOFError (ctrl-d) on prompt`. That message is the signature of an interactive
setting in unattended automation.

### Who may read the password file

The playbook runs as `deploy`. The only copy of the password was `/root/vault-password.txt`, mode
0600, owned by root: correct for root, unreadable for `deploy`. The fix is not to loosen root's file;
it is to give the account that runs the automation its own copy, with the same protection:

```console
$ sudo install -o deploy -g deploy -m 0400 /root/vault-password.txt /var/lib/deploy/.vault-password
```

`install` copies the file and sets owner, group and mode as part of the same command, instead of
leaving a window in which a `cp` copy sits with default permissions until someone remembers `chmod`. `0400` (or `0600`) means no access for group or others, and no
execute bit. The home directory of a system account is a natural place: it belongs to that account and
is outside the project directory, so the password is not committed, synced or backed up with the code.

Then tell Ansible about it in the project's configuration:

```ini
[defaults]
inventory = inventory.ini
vault_password_file = /var/lib/deploy/.vault-password
```

Putting it in `ansible.cfg` means every run in the project — the service, a person running with
`sudo -u deploy`, a test — uses the same source. The alternative for a service-only setup is
`Environment=ANSIBLE_VAULT_PASSWORD_FILE=…` in the unit.

### Plaintext copies, and why Ansible ignored this one

`group_vars/app/` is a directory of variable files for the `app` group. Ansible loads the files in it
whose names end in `.yml`, `.yaml` or `.json` (or have no extension), and ignores others. So
`vault.yml.plain` was never used by the playbook — and it was mode 0644, readable by every account on
the machine, with the database password in it. "The automation does not use it" and "it is harmless"
are different statements.

Plaintext secrets turn up in predictable places: files named `*.dec`, `*.plain`, `*.bak` or `*.orig`
next to vault files; editor swap files; shell history (`ansible-vault view` output pasted into a file);
`--diff` output saved from a CI run. The honest check is to search the tree for the secret itself,
which only someone who already knows it can do — a small, deliberate use of the secret to prove its
absence elsewhere.

`ansible-vault edit` and `ansible-vault view` decrypt to memory or a temporary file and clean up; they
are how you read or change vault content without leaving a copy.

### Secrets in logs

A playbook's output goes wherever the runner's standard output goes. Under systemd that is the journal,
readable by administrators and often shipped off the machine. Three sources of leaks:

- **Explicit output.** `debug: msg: "… {{ db_password }}"` prints it. Remove such tasks, or print only
  non-secret facts.
- **Module arguments and results.** On the managed host, Ansible modules log their arguments to syslog
  (`Invoked with …` lines in the journal). Parameters that modules declare as secret — a `password`
  option — are masked automatically; values you pass in ordinary parameters are not. `--diff` prints
  file contents, templated secrets included.
- **Errors.** A failing task prints its arguments and results.

`no_log: true` on a task suppresses its arguments, results and diff in the output and in those logs:

```yaml
- name: Database settings
  ansible.builtin.template:
    src: templates/db.conf.j2
    dest: /srv/app/config/db.conf
    mode: "0640"
  no_log: true
```

It also hides the details you need when the task fails, so use it on tasks that handle secrets, not on
whole plays. Here the template task's arguments are only paths; the leak was the debug task.

### Reading exactly one run

A service can run many times per boot. systemd gives every activation an **invocation ID**, and
journald records it with each line the run writes:

```console
$ systemctl show deploy.service -p InvocationID --value
$ journalctl -u deploy.service _SYSTEMD_INVOCATION_ID=<id> -o cat
```

That is precisely "what did the last run print", independent of what earlier runs printed. Past leaks
remain in older runs; the persistent journal keeps them until rotation, and removing them means
rotating and vacuuming the journal (`journalctl --rotate`, `--vacuum-time=`). Once a secret has been
logged, rotating the secret itself is the real fix.

### The rendered file

The playbook writes `/srv/app/config/db.conf` with mode 0640 into a directory owned by `deploy`, group
`app`, with the setgid bit. The walkthrough shows the file ended up `deploy:deploy` anyway: setgid on a
directory gives its group to files *created* in it, but Ansible writes a temporary file and renames it
into place, and a rename keeps the group the temporary file already had. If the application's account
must read the settings through the `app` group, the task has to say `group: app`. A secret rendered by
automation needs the same care as the password file: owner, group and mode stated in the task, not
inherited by accident.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed. The database
password is generated per lab VM; where it would appear in the output of a working deploy, the journal
text is redacted.

**1. Read the failed boot run.**

```console
$ systemctl status deploy.service --no-pager | head -n 6
× deploy.service - Render the application's configuration with Ansible
     Loaded: loaded (/etc/systemd/system/deploy.service; enabled; preset: enabled)
     Active: failed (Result: exit-code) since Mon 2026-09-14 03:51:30 UTC; 130ms ago
 Invocation: 6c0b5299b44646fea2e3ed3c6a9f9c72
    Process: 841 ExecStart=/usr/bin/ansible-playbook deploy.yml (code=exited, status=1/FAILURE)
   Main PID: 841 (code=exited, status=1/FAILURE)
$ sudo journalctl -u deploy.service -b --no-pager -o cat | tail -n 8
/usr/lib/python3.13/getpass.py:90: GetPassWarning: Can not control echo on the terminal.
  passwd = fallback_getpass(prompt, stream)
Warning: Password input may be echoed.
Vault password: [WARNING]: Error in vault password prompt (default): EOFError (ctrl-d) on prompt for (default)
[ERROR]: EOFError (ctrl-d) on prompt for (default)
deploy.service: Main process exited, code=exited, status=1/FAILURE
deploy.service: Failed with result 'exit-code'.
Failed to start deploy.service - Render the application's configuration with Ansible.
$ cat /srv/deploy/ansible.cfg
[defaults]
inventory = inventory.ini
retry_files_enabled = false
interpreter_python = /usr/bin/python3
ask_vault_pass = true
```

`Vault password:` followed by `EOFError` — a prompt with nobody to answer it. `ask_vault_pass = true`
is the cause.

**2. Look at the secrets on disk.**

```console
$ ls -la /srv/deploy/group_vars/app/
total 20
drwxr-xr-x 2 deploy deploy 4096 Sep 14 03:51 .
drwxr-xr-x 3 deploy deploy 4096 Sep 13 19:40 ..
-rw-r--r-- 1 deploy deploy   65 Sep 13 19:40 vars.yml
-rw------- 1 deploy deploy  484 Sep 14 03:51 vault.yml
-rw-r--r-- 1 deploy deploy   42 Sep 14 03:51 vault.yml.plain
$ head -c 120 /srv/deploy/group_vars/app/vault.yml; echo
head: cannot open '/srv/deploy/group_vars/app/vault.yml' for reading: Permission denied
$ cat /srv/deploy/group_vars/app/vault.yml.plain
---
db_password: ykpNDZxzPGA6oqGGVpPBcxou
$ ls -l /root/vault-password.txt 2>&1; sudo ls -l /root/vault-password.txt
ls: cannot access '/root/vault-password.txt': Permission denied
-rw------- 1 root root 33 Sep 14 03:51 /root/vault-password.txt
$ sudo -u deploy cat /root/vault-password.txt
cat: /root/vault-password.txt: Permission denied
```

The encrypted vault is protected (0600) and even its ciphertext is unreadable to an ordinary user. Its
decrypted copy is world-readable, and an unprivileged account just printed the database password. The
vault password exists, but only root can read it — not `deploy`, which runs the playbook.

**3. Give `deploy` its own password file and stop prompting.**

```console
$ sudo install -o deploy -g deploy -m 0400 /root/vault-password.txt /var/lib/deploy/.vault-password && sudo ls -l /var/lib/deploy/.vault-password
-r-------- 1 deploy deploy 33 Sep 14 03:51 /var/lib/deploy/.vault-password
$ sudo sed -i 's#^ask_vault_pass = true#vault_password_file = /var/lib/deploy/.vault-password#' /srv/deploy/ansible.cfg && cat /srv/deploy/ansible.cfg
[defaults]
inventory = inventory.ini
retry_files_enabled = false
interpreter_python = /usr/bin/python3
vault_password_file = /var/lib/deploy/.vault-password
$ cd /srv/deploy && sudo -u deploy env HOME=/var/lib/deploy ansible-vault view group_vars/app/vault.yml | sed 's/db_password: .*/db_password: <redacted>/'
---
db_password: <redacted>
$ sudo rm /srv/deploy/group_vars/app/vault.yml.plain
```

`ansible-vault view`, run as `deploy` from the project directory, found the password file through
`ansible.cfg` and decrypted the vault without asking: the configuration works for that account. Then
the plaintext copy goes.

**4. Run the service the way the boot does.**

```console
$ sudo systemctl start deploy.service; systemctl show deploy.service -p Result -p ExecMainStatus
Result=success
ExecMainStatus=0
$ sudo cat /srv/app/config/db.conf | sed 's/^password = .*/password = <redacted>/'; sudo ls -l /srv/app/config/db.conf
# managed by Ansible — /srv/deploy
[database]
host = 127.0.0.1
name = inventory
user = inventory_app
password = <redacted>
-rw-r----- 1 deploy deploy 139 Sep 14 03:51 /srv/app/config/db.conf
$ sudo journalctl -u deploy.service _SYSTEMD_INVOCATION_ID=$(systemctl show deploy.service -p InvocationID --value) --no-pager -o cat | grep -A3 'Show what' | sed -E 's/with password [^"]+/with password <REDACTED BY THE JOURNAL AUTHOR>/'
TASK [Show what is being deployed] *********************************************
ok: [localhost] => {
    "msg": "database inventory on 127.0.0.1 as inventory_app with password <REDACTED BY THE JOURNAL AUTHOR>"
}
```

The deploy works unattended. And the journal of that very run now contains the database password in
clear text — the `sed` in the last command is only there so it does not appear in this document.

**5. Remove the task that prints it, and read the next run.**

```console
$ sed -n 1,12p /srv/deploy/deploy.yml
---
- name: Render the application's database settings
  hosts: app
  gather_facts: false
  tasks:
    - name: Show what is being deployed
      ansible.builtin.debug:
        msg: "database {{ db_name }} on {{ db_host }} as {{ db_user }} with password {{ db_password }}"

    - name: Database settings
      ansible.builtin.template:
        src: templates/db.conf.j2
```

The debug task was replaced by writing a `deploy.yml` with only the template task (as `sudo tee`, then
`chown deploy:deploy`):

```console
$ sudo chown deploy:deploy /srv/deploy/deploy.yml && sudo systemctl start deploy.service; systemctl show deploy.service -p Result
Result=success
$ sudo journalctl -u deploy.service _SYSTEMD_INVOCATION_ID=$(systemctl show deploy.service -p InvocationID --value) --no-pager -o cat
PLAY [Render the application's database settings] ******************************
TASK [Database settings] *******************************************************
Invoked with path=/srv/app/config/db.conf follow=False get_checksum=True get_size=False checksum_algorithm=sha1 get_mime=True get_attributes=True
Invoked with mode=0640 dest=/srv/app/config/db.conf _original_basename=db.conf.j2 recurse=False state=file path=/srv/app/config/db.conf force=False follow=True modification_time_format=%Y%m%d%H%M.%S access_time_format=%Y%m%d%H%M.%S unsafe_writes=False _diff_peek=None src=None modification_time=None access_time=None owner=None group=None seuser=None serole=None selevel=None setype=None attributes=None
ok: [localhost]
PLAY RECAP *********************************************************************
localhost                  : ok=1    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
```

That is the whole log of the last run, unredacted. The `Invoked with` lines are the module arguments
Ansible logs on the managed host: paths and modes, no secret. (Earlier runs in this boot still contain
the leak; after a real leak, rotate the database password.)

**6. Prove there is no plaintext copy left in the project.**

```console
$ PW=$(sudo sed -n 's/^password = //p' /srv/app/config/db.conf); sudo grep -rl -- "$PW" /srv/deploy; echo "grep exit=$?"
grep exit=1
```

`grep -l` lists files that contain the password; exit status 1 means none.

**7. Grade.** The service ran at boot, the vault stayed encrypted with no plain copy, the password file
belonged to `deploy` with no access for anyone else, and the last run's log was clean — before and
after the reboot.

## Common wrong turns

**`chmod 644 /root/vault-password.txt`** (or adding `deploy` to root's group). It makes the key to every
vault readable by more than the one account that needs it, and root's home is the wrong place for a
service's credential anyway.

**Putting the vault password file inside `/srv/deploy`.** It then travels with the project: into Git,
into backups of the code, into every copy a colleague makes. Keep it with the account, outside the
tree, and add a `.gitignore` entry if someone insists on keeping it nearby.

**`chmod 755` on the password file "so Ansible can read it".** An executable password file is run as a
script. Ansible fails with an exec error or, worse, executes whatever the first line happens to be.

**Decrypting the vault permanently** (`ansible-vault decrypt vault.yml`) to make the service work. The
prompt disappears because there is nothing left to decrypt. The machine now has the secret in plain
text in a variables file.

**Deleting `vault.yml.plain` and considering the job done.** It removes one exposure; the service still
prompts, and once it works it prints the password.

**`no_log: true` on the whole play.** It hides the leak, and also every error message the next time the
deploy fails at boot, when nobody is watching and the journal is all you have. Remove the debug task,
and use `no_log` on the specific tasks that handle secrets.

**Checking `journalctl -u deploy.service` without an invocation ID and concluding it is still leaking.**
Older runs of the same boot keep their output. Look at the run that matters.

**Testing with `sudo ansible-playbook`.** Root can read root's password file. The service runs as
`deploy`; test as `deploy` (`sudo -u deploy env HOME=/var/lib/deploy …`) or by starting the service.

## Cheat sheet

```console
$ ansible-vault create|edit|view FILE             # work on vault content without leaving copies
$ ansible-vault encrypt FILE / decrypt FILE       # in place
$ ansible-vault encrypt_string 'value' --name 'db_password'
$ ansible-vault rekey FILE                        # change the vault password
$ head -1 FILE                                    # $ANSIBLE_VAULT;1.1;AES256 when encrypted
$ ansible-playbook site.yml --vault-password-file PATH
$ ANSIBLE_VAULT_PASSWORD_FILE=PATH ansible-playbook site.yml
$ sudo install -o deploy -g deploy -m 0400 SRC DST   # copy with owner and mode in one step
$ sudo -u deploy env HOME=/var/lib/deploy CMD     # test as the service account
$ systemctl show UNIT -p InvocationID --value
$ journalctl -u UNIT _SYSTEMD_INVOCATION_ID=ID -o cat    # one run's output
$ sudo grep -rl -- "$SECRET" DIR; echo $?         # 1 = no file contains it
```

```ini
# ansible.cfg
[defaults]
vault_password_file = /var/lib/deploy/.vault-password    # not ask_vault_pass in automation
```

```yaml
- name: Task that handles a secret
  ansible.builtin.template: {src: db.conf.j2, dest: /srv/app/config/db.conf, mode: "0640"}
  no_log: true
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *Nine letters and a refusal* (lab journal `hello`) — How the kernel picks a triad
- *The log lines that were never written down* (topic journal `logging-journald`) — Everything a service prints becomes a journal entry

Documentation:

- https://docs.ansible.com/ansible/latest/vault_guide/vault_managing_passwords.html
- https://docs.ansible.com/ansible/latest/vault_guide/index.html

The whole subject, end to end: the topic journal *A green run is not a correct machine* (`ansible`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. What does `EOFError (ctrl-d) on prompt` in a service's journal tell you about the Ansible configuration?

   > Ansible tried to prompt for the vault password (`ask_vault_pass` or `--ask-vault-pass`), and the service has no terminal, so the prompt read end-of-file.

2. What must be true of a vault password file for an unattended run as `deploy`?

   > It holds the password, is readable by `deploy`, is not readable by group or others (0400/0600), is not executable, and is named by `vault_password_file`, `ANSIBLE_VAULT_PASSWORD_FILE` or `--vault-password-file`.

3. What happens if a vault password file has the execute bit set?

   > Ansible runs it as a program and uses its output as the password, which is meant for password-manager scripts and fails or misbehaves for a plain file.

4. Why did the playbook ignore `group_vars/app/vault.yml.plain`, and why was it still a problem?

   > Ansible only loads variable files with `.yml`, `.yaml`, `.json` or no extension; the file was world-readable and contained the password in plain text.

5. After encrypting secrets with Vault, what remains your responsibility at run time?

   > Everything that happens to the decrypted values: not printing them (debug, diffs, errors), rendering them into files with the right owner and mode, and keeping them out of logs with `no_log` where tasks handle them.

6. How do you read only the output of the most recent run of a oneshot service?

   > Take its invocation ID with `systemctl show UNIT -p InvocationID --value` and filter the journal with `journalctl -u UNIT _SYSTEMD_INVOCATION_ID=<id>`.

7. Why is `sudo install -o deploy -g deploy -m 0400 SRC DST` better than `cp` followed by `chown` and `chmod`?

   > It sets owner, group and mode as part of the copy, so there is no forgotten or delayed `chmod` leaving the secret with default permissions.

8. A secret was printed to the journal before the leak was fixed. What is the complete remedy?

   > Stop the leak, then rotate the secret itself; purging old journal files (rotate and vacuum) only reduces exposure of a value that must be considered disclosed.
