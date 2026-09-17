#!/usr/bin/env python3
"""Install the Norboten server on a fresh Ubuntu VPS, from a clone of the repository.

    ssh root@<server>
    git clone https://github.com/northelks/norboten.git /opt/norboten-src
    python3 /opt/norboten-src/deploy/install-server.py --domain norboten.org --email you@example.org

It runs the repository's own Ansible playbooks on the server itself (`connection: local`), so this
installer and a deploy from a laptop (`make bootstrap` + `make server`) configure the same machine:

  1. checks the machine: Ubuntu, root, memory and disk, and whether the DNS names point here
  2. installs Ansible into a private virtualenv, with the collections the playbooks need
  3. playbooks/bootstrap.yml: the `deploy` user, holding the keys root already accepts plus a new
     key for GitHub Actions, and passwordless sudo
  4. playbooks/server.yml: hardening (keys-only SSH, no root login, ufw, fail2ban, automatic
     security updates), Docker, the compose project in /opt/norboten, the backup and analytics
     timers
  5. the API image: pulled from GHCR, or built here from the clone when there is none to pull
  6. deploy.sh: the stack up, waiting for /readyz, rolled back if it never gets there
  7. the site, built from the clone into /opt/norboten/site
  8. prints what to put into GitHub, so every push to main deploys from then on

Secrets (the PostgreSQL and Grafana passwords, the MCP state key) are generated once and kept in
/etc/norboten/install.json, readable by root only; running the installer again keeps them and
changes only what has changed. **The GitHub OAuth App is the one thing it cannot make up**: signing
in is GitHub and nothing else, so pass `--github-client-id` and `--github-client-secret` or nobody
can sign in — run it again with them once the app exists. Discord (`--discord-*`, for linking and
the weekly digest) is optional, and Telegram stays off; docs/deploy.md turns both on.

Standard library only: it runs before anything else is installed.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = Path("/etc/norboten/install.json")
VENV = Path("/opt/norboten-installer")
LOG = Path("/var/log/norboten-install.log")
CI_KEY = Path("/root/norboten-ci/deploy_ed25519")
API_IMAGE = "ghcr.io/northelks/norboten-api"
SUPPORTED = ("24.04", "26.04")
ANSIBLE = "ansible-core>=2.19,<2.22"
NAMES = ("", "www.", "api.", "status.")
SITE_BUILD = (
    "pip install -q uv && uv sync -q --all-packages --frozen"
    " && uv run python seed/generate.py && uv run python site/build.py --out /out"
)

GREEN, AMBER, RED, BOLD, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[1m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = AMBER = RED = BOLD = RESET = ""


def say(message: str) -> None:
    print(f"{GREEN}[ norboten ]{RESET} {message}", flush=True)


def warn(message: str) -> None:
    print(f"{GREEN}[ norboten ]{RESET} {AMBER}{message}{RESET}", flush=True)


def die(message: str) -> None:
    print(f"{GREEN}[ norboten ]{RESET} {RED}{message}{RESET}", file=sys.stderr, flush=True)
    raise SystemExit(1)


# -- pure parts (tests/test_install_server.py) ---------------------------------------------------


def os_release(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip().strip("\"'")
    return out


def check_os(release: dict[str, str]) -> str | None:
    """None when this is a supported Ubuntu, otherwise why not."""
    if release.get("ID") != "ubuntu":
        return f"this is {release.get('PRETTY_NAME', 'an unknown system')}; the server needs Ubuntu"
    if release.get("VERSION_ID") not in SUPPORTED:
        return f"Ubuntu {release.get('VERSION_ID')} is not one of {', '.join(SUPPORTED)} (LTS)"
    return None


def valid_domain(domain: str) -> bool:
    labels = domain.rstrip(".").split(".")
    return len(labels) >= 2 and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
    )


@dataclass
class State:
    domain: str = ""
    email: str = ""
    postgres_password: str = ""
    grafana_password: str = ""
    mcp_state_key: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_bot_token: str = ""
    discord_guild_id: str = ""
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        known = {k: data.pop(k) for k in list(data) if k in cls.__dataclass_fields__}
        return cls(**known, extra=data)

    def fill_secrets(self) -> None:
        self.postgres_password = self.postgres_password or secrets.token_urlsafe(24)
        self.grafana_password = self.grafana_password or secrets.token_urlsafe(18)
        self.mcp_state_key = self.mcp_state_key or secrets.token_urlsafe(32)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fields = {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "extra"}
        tmp = path.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        tmp.write_text(json.dumps({**self.extra, **fields}, indent=2) + "\n")
        os.replace(tmp, path)


KEY = re.compile(r"(ssh-(?:ed25519|rsa)|ecdsa-sha2-\S+|sk-\S+@openssh\.com) (\S+)")


def public_keys(*texts: str) -> list[str]:
    """SSH public keys from authorized_keys files, deduplicated, options and comments kept."""
    seen, out = set(), []
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            match = KEY.search(line)
            if not line or line.startswith("#") or not match or match.group(2) in seen:
                continue
            seen.add(match.group(2))
            out.append(line)
    return out


def inventory(state: State, api_tag: str, admin: str, python: str) -> dict:
    return {
        "all": {
            "hosts": {
                "norboten": {"ansible_connection": "local", "ansible_python_interpreter": python}
            },
            "vars": {
                "server_base_admin_user": admin,
                "norboten_domain": state.domain,
                "norboten_acme_email": state.email,
                "norboten_api_image": API_IMAGE,
                "norboten_api_tag": api_tag,
                "norboten_postgres_password": state.postgres_password,
                "norboten_grafana_admin_password": state.grafana_password,
                "norboten_mcp_state_key": state.mcp_state_key,
                "norboten_github_client_id": state.github_client_id,
                "norboten_github_client_secret": state.github_client_secret,
                "norboten_discord_client_id": state.discord_client_id,
                "norboten_discord_client_secret": state.discord_client_secret,
                "norboten_discord_bot_token": state.discord_bot_token,
                "norboten_discord_guild_id": state.discord_guild_id,
            },
        }
    }


def dns_problems(domain: str, addresses: set[str], resolve) -> list[str]:
    """Each name the site needs that does not resolve to one of this server's addresses."""
    problems = []
    for prefix in NAMES:
        name = f"{prefix}{domain}"
        try:
            found = resolve(name)
        except OSError:
            problems.append(f"{name} does not resolve")
            continue
        if not found & addresses:
            problems.append(f"{name} points at {', '.join(sorted(found))}, not at this server")
    return problems


def github_settings(host: str, host_key: str, domain: str) -> list[tuple[str, str, str]]:
    return [
        ("variable", "SERVER_HOST", host),
        ("variable", "SERVER_HOST_KEY", f"{host} {' '.join(host_key.split()[:2])}"),
        ("variable", "NORBOTEN_DOMAIN", domain),
        ("secret", "DEPLOY_SSH_KEY", f"the whole of {CI_KEY} (then delete that file)"),
    ]


# -- side effects ---------------------------------------------------------------------------------


class Runner:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def __call__(self, cmd: list[str], *, env=None, cwd=None, check=True, secret=False):
        print(f"  $ {cmd[0] if secret else ' '.join(cmd)}", flush=True)
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        proc = subprocess.run(
            cmd,
            env={**os.environ, **(env or {})},
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with LOG.open("a") as log:
            log.write(f"\n$ {cmd[0] if secret else ' '.join(cmd)}\n{proc.stdout}")
        if check and proc.returncode != 0:
            tail = "\n".join(proc.stdout.strip().splitlines()[-25:])
            die(f"that failed (exit {proc.returncode}); the whole output is in {LOG}\n{tail}")
        return proc


def resolve(name: str) -> set[str]:
    return {info[4][0] for info in socket.getaddrinfo(name, None)}


def local_addresses() -> set[str]:
    try:
        out = subprocess.run(
            ["ip", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True
        ).stdout
    except OSError:  # no iproute2: not the server, a dry run somewhere else
        return set()
    found = set()
    for match in re.finditer(r"inet6? ([0-9a-f.:]+)/", out):
        address = ipaddress.ip_address(match.group(1))
        if address.is_global:
            found.add(str(address))
    return found


def ask(question: str, default: str = "", assume_yes: bool = False) -> str:
    if assume_yes:
        return default
    suffix = f" [{default}]" if default else ""
    return input(f"{GREEN}[ norboten ]{RESET} {question}{suffix}: ").strip() or default


def confirm(question: str, assume_yes: bool) -> bool:
    return assume_yes or ask(f"{question} y/N", "n").lower() in ("y", "yes")


def read(path: str | Path) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def preflight(dry_run: bool) -> None:
    if os.geteuid() != 0 and not dry_run:
        die("run it as root: sudo python3 deploy/install-server.py")
    if not (REPO / "deploy" / "compose.yaml").is_file() or not (REPO / "ansible").is_dir():
        die(f"{REPO} is not a Norboten checkout")
    release = os_release(read("/etc/os-release"))
    problem = check_os(release)
    if problem and not dry_run:
        die(problem)
    if platform.machine() not in ("x86_64", "aarch64", "arm64"):
        die(f"unsupported CPU architecture {platform.machine()}")
    memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    disk = shutil.disk_usage("/").free / 2**30
    name = release.get("PRETTY_NAME", "unknown system")
    say(f"{name}, {platform.machine()}, {memory:.1f} GiB memory, {disk:.0f} GiB free")
    if memory < 1.8:
        warn("less than 2 GB of memory: 2 GiB keeps about 290 MiB free with the model loaded")
    if disk < 25:
        warn("less than 25 GB free: the images take about 11 GB, Ollama's alone 7 GB")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the Norboten server on this Ubuntu machine."
    )
    parser.add_argument("--domain", help="the apex domain, e.g. norboten.org")
    parser.add_argument("--email", help="Let's Encrypt's contact for expiry notices")
    parser.add_argument(
        "--github-client-id",
        help="the GitHub OAuth App everyone signs in with (required to sign in; kept from the last "
        "run when omitted)",
    )
    parser.add_argument("--github-client-secret", help="that app's client secret")
    parser.add_argument("--discord-client-id", help="optional: the Discord application")
    parser.add_argument("--discord-client-secret", help="the Discord application's secret")
    parser.add_argument("--discord-bot-token", help="the bot that sends the weekly digest")
    parser.add_argument("--discord-guild-id", help="the Norboten Discord server's id")
    parser.add_argument("--api-tag", default="latest", help="API image tag (default: latest)")
    parser.add_argument("--build-api", action="store_true", help="build the API image here")
    parser.add_argument("--no-site", action="store_true", help="skip building the site")
    parser.add_argument("--admin", default="deploy", help="the one user SSH lets in")
    parser.add_argument("--yes", action="store_true", help="do not ask; go on past DNS warnings")
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    args = parser.parse_args(argv)
    run = Runner(args.dry_run)

    preflight(args.dry_run)
    state = State.load(STATE)
    domain = args.domain or state.domain or ask("domain (the apex, e.g. norboten.org)")
    state.domain = domain.lower().rstrip(".")
    if not valid_domain(state.domain):
        die(f"{state.domain!r} is not a domain name")
    contact = f"ops@{state.domain}"
    state.email = args.email or state.email or ask("e-mail for Let's Encrypt", contact, args.yes)
    for name in (
        "github_client_id",
        "github_client_secret",
        "discord_client_id",
        "discord_client_secret",
        "discord_bot_token",
        "discord_guild_id",
    ):
        given = getattr(args, name)
        if given is not None:
            setattr(state, name, given)
    state.fill_secrets()
    if not (state.github_client_id and state.github_client_secret):
        warn("no GitHub OAuth App: the server comes up, but nobody can sign in until it has one")
    if not args.dry_run:
        LOG.touch(mode=0o600)
        state.save(STATE)
    say(f"secrets are in {STATE} (root only); the log is {LOG}")

    # 1 — DNS, before anything asks Let's Encrypt for a certificate
    here = local_addresses()
    problems = dns_problems(state.domain, here, resolve)
    if problems:
        warn("DNS is not ready, so Caddy cannot get certificates yet:")
        for problem in problems:
            warn(f"  - {problem}")
        names = ", ".join(prefix + state.domain for prefix in NAMES)
        warn(f"  A and AAAA records for {names} -> {', '.join(sorted(here)) or 'this server'}")
        if not confirm("go on anyway? Caddy keeps trying until the names resolve", args.yes):
            return 1
    else:
        say(f"DNS: every name points at this server ({', '.join(sorted(here))})")

    # 2 — Ansible, private to the installer
    say("Ansible, in a private virtualenv")
    apt_env = {"DEBIAN_FRONTEND": "noninteractive"}
    run(["apt-get", "update", "-qq"], env=apt_env)
    packages = ["python3-venv", "git", "rsync", "openssh-client"]
    run(["apt-get", "install", "-y", "-qq", *packages], env=apt_env)
    if not (VENV / "bin" / "ansible-playbook").exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    run([str(VENV / "bin" / "pip"), "install", "-q", "--upgrade", ANSIBLE])
    collections = str(VENV / "collections")
    ansible_env = {"ANSIBLE_COLLECTIONS_PATH": collections, "ANSIBLE_NOCOLOR": "1"}
    requirements = str(REPO / "ansible" / "requirements.yml")
    galaxy = [str(VENV / "bin" / "ansible-galaxy"), "collection", "install"]
    run([*galaxy, "-r", requirements, "-p", collections], env=ansible_env)

    # 3 — the admin user, holding every key root already accepts, and a key for the deploy workflow
    sudo_user = os.environ.get("SUDO_USER", "")
    admin_keys = public_keys(
        read("/root/.ssh/authorized_keys"),
        read(f"/home/{sudo_user}/.ssh/authorized_keys") if sudo_user not in ("", "root") else "",
    )
    if not admin_keys and not args.dry_run:
        die(
            "no SSH public key found for root. Hardening turns password and root logins off, so "
            "you would be locked out. Put your key in /root/.ssh/authorized_keys and run it again."
        )
    # Not root, and /root is unreadable: exists() raises rather than answering, so a dry run has to
    # short-circuit before it asks (a real run is root, and this is the key GitHub Actions gets).
    if not args.dry_run and not CI_KEY.exists():
        CI_KEY.parent.mkdir(mode=0o700, exist_ok=True)
        comment = "github-actions@norboten"
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(CI_KEY)])
    keys = "\n".join([*admin_keys, read(CI_KEY.with_suffix(".pub")).strip()]).strip()

    work = Path(tempfile.mkdtemp(prefix="norboten-")) if args.dry_run else VENV / "run"
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    hosts = work / "inventory.json"
    hosts.touch(mode=0o600)
    hosts.write_text(
        json.dumps(inventory(state, args.api_tag, args.admin, "/usr/bin/python3"), indent=2)
    )
    playbook = [str(VENV / "bin" / "ansible-playbook"), "-i", str(hosts)]
    ansible_dir = REPO / "ansible"

    say(f"bootstrap: the {args.admin} user and its keys")
    extra = ["-e", f"deploy_user={args.admin}", "-e", json.dumps({"deploy_public_key": keys})]
    run([*playbook, "playbooks/bootstrap.yml", *extra], cwd=ansible_dir, env=ansible_env)

    # 4 — the server itself; the API comes up in step 6, once its image is here
    say("server: hardening, Docker, the compose project, timers")
    skip = ["-e", "norboten_skip_deploy=true"]
    run([*playbook, "playbooks/server.yml", *skip], cwd=ansible_dir, env=ansible_env)

    # 5 — the API image
    tag = args.api_tag
    pulled = False
    if not args.build_api:
        say(f"pulling {API_IMAGE}:{tag}")
        pulled = run(["docker", "pull", f"{API_IMAGE}:{tag}"], check=False).returncode == 0
    if not pulled:
        tag = "local"
        say(f"building {API_IMAGE}:{tag} from this clone (a few minutes, once)")
        build = ["docker", "build", "-t", f"{API_IMAGE}:{tag}", "-f", "api/Dockerfile", "."]
        run(build, cwd=REPO)

    # 6 — up, or rolled back
    say(f"deploying api:{tag}")
    run(["/opt/norboten/deploy.sh", tag])

    # 7 — the site
    if not args.no_site:
        say("building the site from this clone")
        api = f"NORBOTEN_SITE_API=https://api.{state.domain}"
        mounts = ["-v", f"{REPO}:/src", "-v", "/opt/norboten/site:/out", "-w", "/src"]
        image = ["-e", api, "-e", "UV_LINK_MODE=copy", "python:3.12-slim"]
        run(["docker", "run", "--rm", *mounts, *image, "sh", "-c", SITE_BUILD])
        run(["chown", "-R", f"{args.admin}:{args.admin}", "/opt/norboten/site"], check=False)

    # 8 — done; what is left happens outside this machine
    host = sorted(here, key=lambda a: ":" in a)[0] if here else socket.getfqdn()
    host_key = read("/etc/ssh/ssh_host_ed25519_key.pub") or "ssh-ed25519 <this server's host key>"
    print()
    say(f"{BOLD}done{RESET}")
    print(
        textwrap.dedent(f"""
        site      https://{state.domain}/
        API       https://api.{state.domain}/readyz
        Grafana   https://status.{state.domain}/   (admin, grafana_password in {STATE})

        Before closing this root session, check from a second terminal that this works:
            ssh {args.admin}@{host}
        Root and password logins are off from now on.

        GitHub: Settings, Secrets and variables, Actions, so that every push to main deploys:
    """)
    )
    for kind, name, value in github_settings(host, host_key, state.domain):
        print(f"    {kind:<9} {name:<16} {value}")
    if not (state.github_client_id and state.github_client_secret):
        warn("\nNobody can sign in yet: there is no GitHub OAuth App. Create one (docs/deploy.md,")
        warn(f"callback https://api.{state.domain}/auth/github/callback,")
        warn("Enable Device Flow ticked)")
        warn("and run this again with --github-client-id … --github-client-secret …")
    if not state.discord_bot_token:
        print("\nDiscord is off: no linking and no weekly digest (docs/deploy.md turns it on).")
    print("Telegram is off (docs/deploy.md turns it on).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        raise SystemExit(130) from None
