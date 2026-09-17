"""A vault that prompts, a decrypted copy beside it, a debug task that prints the secret."""

import grp
import os
import pwd
import secrets
import shutil


def _account(ctx, name, home):
    if not ctx.run(["id", name]).ok:
        ctx.run(
            [
                "useradd",
                "--system",
                "--home-dir",
                home,
                "--create-home",
                "--shell",
                "/sbin/nologin",
                name,
            ],
            check=True,
        )


def apply(ctx):
    _account(ctx, "deploy", "/var/lib/deploy")
    if not ctx.run(["getent", "group", "app"]).ok:
        ctx.run(["groupadd", "--system", "app"], check=True)
    password = ctx.state.get("db_password") or secrets.token_urlsafe(18)
    vault_pass = ctx.state.get("vault_pass") or secrets.token_urlsafe(24)
    ctx.state.update(db_password=password, vault_pass=vault_pass)

    if not os.path.exists("/srv/deploy/deploy.yml"):
        shutil.copytree(os.path.join(ctx.lab_dir, "files", "project"), "/srv/deploy")
    ctx.write("/root/vault-password.txt", vault_pass + "\n", mode=0o600)
    vault = "/srv/deploy/group_vars/app/vault.yml"
    if not (ctx.read(vault) or "").startswith("$ANSIBLE_VAULT"):
        ctx.write(vault, f"---\ndb_password: {password}\n", mode=0o600)
        ctx.run(
            [
                "ansible-vault",
                "encrypt",
                "--vault-password-file",
                "/root/vault-password.txt",
                vault,
            ],
            check=True,
            env={"LC_ALL": "C.UTF-8"},  # Ansible refuses a non-UTF-8 locale
        )
    # "ansible-vault view vault.yml > vault.yml.plain", to have a look — and left there
    ctx.write(vault + ".plain", f"---\ndb_password: {password}\n", mode=0o644)
    ctx.run(["chown", "-R", "deploy:deploy", "/srv/deploy"], check=True)

    os.makedirs("/srv/app/config", exist_ok=True)
    os.chown("/srv/app/config", pwd.getpwnam("deploy").pw_uid, grp.getgrnam("app").gr_gid)
    os.chmod("/srv/app/config", 0o2750)
    shutil.copy(os.path.join(ctx.lab_dir, "files", "deploy.service"), "/etc/systemd/system/")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "deploy.service"], check=True)
    ctx.run(["systemctl", "start", "deploy.service"], timeout=60)  # fails: it wants a password
