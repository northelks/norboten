# The Playbook That Changes Everything, Every Time

`/srv/ansible` holds the playbook that configures this machine as an application host: an `app`
account, the application in `/opt/app`, its configuration in `/etc/app/app.conf`, the `app` systemd
service, and IP forwarding for the containers it will run.

```sh
cd /srv/ansible && sudo ansible-playbook site.yml
```

Every run reports most tasks as **changed**, restarts the application whether or not anything
changed, and grows a file a little. `--check` is useless: it skips half the tasks. And the
application listens on 8080 although the inventory for the `app` group says **8081**.

What is expected, and graded:

1. The application answers on the port the inventory gives it, 8081, and still does after a reboot.
2. IP forwarding is on, configured in exactly one line, and stays on after a reboot.
3. On this machine, `ansible-playbook site.yml --check` runs every task — none skipped — and finds
   nothing to change.

The grader runs the playbook in check mode only; it never applies it for you. You have root through
`sudo`. There is no internet access, and none is needed.
