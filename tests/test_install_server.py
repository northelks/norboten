"""The server installer's decisions, without a server: deploy/install-server.py."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "install_server", ROOT / "deploy" / "install-server.py"
)
install = importlib.util.module_from_spec(_spec)
sys.modules["install_server"] = install
_spec.loader.exec_module(install)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ('ID=ubuntu\nVERSION_ID="26.04"\nPRETTY_NAME="Ubuntu 26.04 LTS"', True),
        ('ID=ubuntu\nVERSION_ID="24.04"', True),
        ('ID=ubuntu\nVERSION_ID="25.10"', False),
        ('ID=rocky\nVERSION_ID="10"', False),
        ("", False),
    ],
)
def test_only_an_ubuntu_lts_is_accepted(text, ok):
    assert (install.check_os(install.os_release(text)) is None) is ok


def test_domains():
    assert install.valid_domain("norboten.org") and install.valid_domain("a-b.example.co.uk")
    assert not install.valid_domain("localhost") and not install.valid_domain("bad_name.org")


def test_secrets_are_made_once_and_kept(tmp_path):
    path = tmp_path / "etc" / "install.json"
    state = install.State(domain="norboten.org", email="ops@norboten.org")
    state.fill_secrets()
    state.save(path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    again = install.State.load(path)
    again.fill_secrets()
    assert again.postgres_password == state.postgres_password
    assert again.mcp_state_key == state.mcp_state_key and len(state.mcp_state_key) >= 32
    # the Ansible role refuses shorter ones
    assert len(state.postgres_password) >= 16 and len(state.grafana_password) >= 12


def test_keys_are_collected_once_each():
    root = "ssh-ed25519 AAAAC3key1 me@laptop\n# a comment\n\nssh-rsa AAAAB3key2 old"
    user = 'from="1.2.3.4" ssh-ed25519 AAAAC3key1 again\nnonsense'
    assert install.public_keys(root, user) == [
        "ssh-ed25519 AAAAC3key1 me@laptop",
        "ssh-rsa AAAAB3key2 old",
    ]


def test_dns_names_all_point_here():
    table = {
        "norboten.org": {"203.0.113.10"},
        "www.norboten.org": {"203.0.113.10"},
        "api.norboten.org": {"198.51.100.7"},
    }

    def resolve(name):
        if name not in table:
            raise OSError("no such name")
        return table[name]

    problems = install.dns_problems("norboten.org", {"203.0.113.10", "2001:db8::1"}, resolve)
    assert problems == [
        "api.norboten.org points at 198.51.100.7, not at this server",
        "status.norboten.org does not resolve",
    ]


def test_the_inventory_carries_what_the_roles_assert():
    state = install.State("norboten.org", "ops@norboten.org", "p" * 32, "g" * 24)
    state.fill_secrets()
    inv = install.inventory(state, "latest", "deploy", "/usr/bin/python3")
    assert inv["all"]["hosts"]["norboten"]["ansible_connection"] == "local"
    values = inv["all"]["vars"]
    assert values["norboten_postgres_password"] == "p" * 32
    assert values["norboten_github_client_id"] == "" and "norboten_smtp_url" not in values
    assert values["server_base_admin_user"] == "deploy" and values["norboten_api_tag"] == "latest"
    json.dumps(inv)  # written as JSON, which Ansible's YAML inventory reads


def test_github_settings_pin_the_host_key():
    rows = install.github_settings("203.0.113.10", "ssh-ed25519 AAAAC3host root@vps\n", "x.org")
    assert ("variable", "SERVER_HOST_KEY", "203.0.113.10 ssh-ed25519 AAAAC3host") in rows


def test_a_dry_run_prints_every_step_and_touches_nothing(capsys, monkeypatch):
    monkeypatch.setattr(install, "local_addresses", lambda: {"203.0.113.10"})
    monkeypatch.setattr(install, "resolve", lambda name: {"203.0.113.10"})
    code = install.main(["--dry-run", "--domain", "norboten.org", "--email", "a@b.org", "--yes"])
    out = capsys.readouterr().out
    assert code == 0
    for step in ("playbooks/bootstrap.yml", "playbooks/server.yml", "deploy.sh", "site/build.py"):
        assert step in out
    assert "DNS: every name points at this server" in out


def test_a_dry_run_never_asks_about_the_ci_key(tmp_path, monkeypatch, capsys):
    """Only root can read /root: asking whether the key is there is itself an error off a server."""
    locked = tmp_path / "norboten-ci"
    locked.mkdir(mode=0o000)
    monkeypatch.setattr(install, "CI_KEY", locked / "deploy_ed25519")
    monkeypatch.setattr(install, "STATE", tmp_path / "install.json")
    monkeypatch.setattr(install, "local_addresses", lambda: {"203.0.113.10"})
    monkeypatch.setattr(install, "resolve", lambda name: {"203.0.113.10"})
    try:
        code = install.main(
            ["--dry-run", "--domain", "norboten.org", "--email", "a@b.org", "--yes"]
        )
    finally:
        locked.chmod(0o700)
    assert code == 0
    assert "ssh-keygen" not in capsys.readouterr().out


def test_without_a_github_app_it_says_nobody_can_sign_in(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(install, "STATE", tmp_path / "install.json")
    monkeypatch.setattr(install, "local_addresses", lambda: {"203.0.113.10"})
    monkeypatch.setattr(install, "resolve", lambda name: {"203.0.113.10"})
    base = ["--dry-run", "--domain", "norboten.org", "--email", "a@b.org", "--yes"]
    assert install.main(base) == 0
    assert "nobody can sign in" in capsys.readouterr().out.lower()
    assert install.main([*base, "--github-client-id", "Iv1.x", "--github-client-secret", "s"]) == 0
    assert "nobody can sign in" not in capsys.readouterr().out.lower()
