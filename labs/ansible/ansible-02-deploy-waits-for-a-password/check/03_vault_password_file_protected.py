import configparser
import os
import pwd
import re
import stat


def _password_file(ctx):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read("/srv/deploy/ansible.cfg")
    if cfg.get("defaults", "vault_password_file", fallback=""):
        return cfg.get("defaults", "vault_password_file"), "ansible.cfg"
    unit = ctx.run(
        ["systemctl", "show", "deploy.service", "-p", "Environment", "-p", "ExecStart"]
    ).out
    m = re.search(r"ANSIBLE_VAULT_PASSWORD_FILE=(\S+)", unit)
    if m:
        return m.group(1), "the unit's environment"
    m = re.search(r"--vault-password-file[= ](\S+)", unit)
    if m:
        return m.group(1), "the unit's command line"
    m = re.search(r"--vault-id[= ]\S*?@?(/\S+)", unit)
    if m:
        return m.group(1), "the unit's command line"
    return "", ""


def check(ctx):
    path, source = _password_file(ctx)
    if not path:
        return ctx.failed("The deploy is not given a vault password file.")
    if path.startswith("~/"):  # the deploy account's home, not root's
        path = "/var/lib/deploy/" + path[2:]
    if not os.path.isabs(path):
        path = os.path.join("/srv/deploy", path)
    try:
        st = os.stat(path)
    except OSError:
        return ctx.failed(f"The vault password file named in {source} does not exist.", path)
    mode = stat.S_IMODE(st.st_mode)
    owner = pwd.getpwuid(st.st_uid).pw_name
    evidence = f"{path} (from {source}): mode {mode:04o}, owner {owner}"
    if stat.S_ISREG(st.st_mode) and mode & 0o111:
        return ctx.failed(
            "The vault password file is executable, so Ansible would run it.", evidence
        )
    if mode & 0o077:
        return ctx.failed(
            "Accounts other than its owner can read the vault password file.", evidence
        )
    if owner != "deploy":
        return ctx.failed(
            "The vault password file does not belong to the deploy account.", evidence
        )
    if (ctx.read(path) or "").strip() != ctx.state["vault_pass"]:
        return ctx.failed("The file does not hold the vault password.", evidence)
    return ctx.passed("Only deploy can read the vault password file.", evidence)
