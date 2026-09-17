#!/bin/sh
set -eu
cd /srv/ansible
cat > site.yml <<'YAML'
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
YAML
ANSIBLE_NOCOLOR=1 ansible-playbook site.yml
