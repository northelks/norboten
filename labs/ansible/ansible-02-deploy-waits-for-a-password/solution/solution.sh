#!/bin/sh
set -eu
cd /srv/deploy
install -o deploy -g deploy -m 0400 /root/vault-password.txt /var/lib/deploy/.vault-password
cat > ansible.cfg <<'CFG'
[defaults]
inventory = inventory.ini
retry_files_enabled = false
interpreter_python = /usr/bin/python3
vault_password_file = /var/lib/deploy/.vault-password
CFG
rm -f group_vars/app/vault.yml.plain
cat > deploy.yml <<'YAML'
---
- name: Render the application's database settings
  hosts: app
  gather_facts: false
  tasks:
    - name: Database settings
      ansible.builtin.template:
        src: templates/db.conf.j2
        dest: /srv/app/config/db.conf
        mode: "0640"
YAML
chown -R deploy:deploy /srv/deploy
systemctl start deploy.service
