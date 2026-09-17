import os
import sys

import httpx
import pytest
from typer.testing import CliRunner

from norboten import __version__, cli, selfmanage

RECEIPT = """\
[tool]
requirements = [{ name = "norboten", extras = ["pdf"], specifier = "==0.1.0" }]
python = "3.12"
entrypoints = [{ name = "norboten", install-path = "/u/norboten", from = "norboten" }]

[tool.options]
exclude-newer-package = {}
"""


@pytest.fixture(autouse=True)
def no_find_links(monkeypatch):
    monkeypatch.delenv("NORBOTEN_FIND_LINKS", raising=False)


def test_the_receipt_gives_extras_and_python(tmp_path):
    (tmp_path / "uv-receipt.toml").write_text(RECEIPT)
    assert selfmanage.receipt(tmp_path) == selfmanage.Receipt(("pdf",), "3.12")
    assert selfmanage.receipt(tmp_path / "elsewhere") is None


def test_the_update_repeats_the_install_at_the_new_version(monkeypatch):
    found = selfmanage.Receipt(("pdf",), "3.12")
    command = selfmanage.update_command("0.3.0", found, "/bin/uv")
    assert command[:4] == ["/bin/uv", "tool", "install", "--upgrade"]
    assert command[-1] == "norboten[pdf]==0.3.0"
    assert command[command.index("--python") + 1] == "3.12"

    monkeypatch.setenv("NORBOTEN_FIND_LINKS", "/dist")
    plain = selfmanage.update_command("0.3.0", selfmanage.Receipt((), None), "/bin/uv")
    assert plain[-1] == "norboten==0.3.0" and "/dist" in plain and "3.12" in plain


def test_versions_compare_as_numbers():
    assert selfmanage.is_newer("0.10.0", "0.9.1")
    assert not selfmanage.is_newer("0.2.0", "0.2.0")
    assert not selfmanage.is_newer(None, "0.2.0")


def test_latest_version_from_pypi_and_offline(monkeypatch):
    def pypi(url, **kwargs):
        return httpx.Response(
            200, json={"info": {"version": "0.4.2"}}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(selfmanage.httpx, "get", pypi)
    assert selfmanage.latest_version() == "0.4.2"

    def offline(url, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(selfmanage.httpx, "get", offline)
    assert selfmanage.latest_version() is None


def test_latest_version_from_a_wheel_directory(tmp_path, monkeypatch):
    for name in (
        "norboten-0.2.0-py3-none-any.whl",
        "norboten-0.10.1-py3-none-any.whl",
        "norboten_runner-0.11.0-py3-none-any.whl",
    ):
        (tmp_path / name).write_text("")
    monkeypatch.setenv("NORBOTEN_FIND_LINKS", str(tmp_path))
    assert selfmanage.latest_version() == "0.10.1"


def test_update_refuses_without_a_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(selfmanage, "latest_version", lambda: "99.0.0")
    result = CliRunner().invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 1
    assert "not installed by install.sh" in result.output


def test_update_runs_uv_and_reports(monkeypatch, tmp_path):
    (tmp_path / "uv-receipt.toml").write_text(RECEIPT)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(selfmanage, "latest_version", lambda: "99.0.0")
    monkeypatch.setattr(selfmanage, "uv_binary", lambda: "/bin/uv")
    ran = []
    monkeypatch.setattr(selfmanage.subprocess, "call", lambda command: ran.append(command) or 0)
    result = CliRunner().invoke(cli.app, ["update", "--yes"])
    assert result.exit_code == 0, result.output
    assert ran and ran[0][-1] == "norboten[pdf]==99.0.0"
    assert "norboten 99.0.0" in result.output


def test_update_check_and_current(monkeypatch):
    monkeypatch.setattr(selfmanage, "latest_version", lambda: "99.0.0")
    ran = []
    monkeypatch.setattr(selfmanage.subprocess, "call", lambda command: ran.append(command) or 0)
    result = CliRunner().invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0 and "99.0.0" in result.output and not ran

    monkeypatch.setattr(selfmanage, "latest_version", lambda: __version__)
    result = CliRunner().invoke(cli.app, ["update"])
    assert result.exit_code == 0 and "is the newest" in result.output


def test_u_in_the_tui_updates_after_it_closes_and_starts_the_new_norboten(monkeypatch):
    from norboten.tui import app as tui_app

    monkeypatch.setattr(tui_app, "run", lambda: "update")
    monkeypatch.setattr(selfmanage, "latest_version", lambda: "99.0.0")
    monkeypatch.setattr(selfmanage, "require_receipt", lambda: selfmanage.Receipt((), "3.12"))
    updated, started = [], []
    monkeypatch.setattr(selfmanage, "update", updated.append)
    monkeypatch.setattr(selfmanage, "executable", lambda: "/u/norboten")
    monkeypatch.setattr(os, "execv", lambda *a: started.append(a))
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0, result.output
    assert updated == ["99.0.0"] and started == [("/u/norboten", ["/u/norboten"])]


# -- uninstall ------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    from norboten.lima import instance

    home = tmp_path / "nb"
    monkeypatch.setenv("NORBOTEN_HOME", str(home))
    monkeypatch.setattr(instance, "list_instances", lambda: {"nb-orphan": {}})
    for d in ("images/alpine", "sessions", "lima"):
        (home / d).mkdir(parents=True)
    (home / "images/alpine/image.qcow2").write_bytes(b"x" * 1000)
    (home / "settings.json").write_text("{}")
    return home


def _session(lab_id="hello"):
    from norboten.session.state import Session

    Session(lab_id=lab_id, lab_version="1", image="alpine", instance=f"nb-{lab_id}").save()


def test_removal_lists_machines_size_and_what_is_not_ours(home):
    _session()
    (home / "notes.txt").write_text("mine")
    plan = selfmanage.removal()
    assert plan.machines == ("nb-hello", "nb-orphan")
    assert plan.home_bytes >= 1000
    assert plan.others == ("notes.txt",)


def test_the_home_goes_but_foreign_files_stay(home):
    said = []
    (home / "notes.txt").write_text("mine")
    selfmanage._remove_home(home, said.append)
    assert sorted(p.name for p in home.iterdir()) == ["notes.txt"]
    assert "kept" in said[-1]

    (home / "notes.txt").unlink()
    (home / "images").mkdir()
    selfmanage._remove_home(home, said.append)
    assert not home.exists()


def test_the_home_directory_itself_is_never_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(selfmanage.Path, "home", lambda: tmp_path)
    with pytest.raises(selfmanage.SelfManageError):
        selfmanage._remove_home(tmp_path, print)


def test_uninstall_removes_machines_then_home_then_the_program(home, monkeypatch, tmp_path):
    monkeypatch.setattr(os, "_exit", lambda code: None)
    (tmp_path / "uv-receipt.toml").write_text(RECEIPT)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(selfmanage, "uv_binary", lambda: "/bin/uv")
    order = []
    monkeypatch.setattr(selfmanage, "_destroy_machines", lambda say: order.append("machines"))
    monkeypatch.setattr(selfmanage.subprocess, "call", lambda command: order.append(command) or 0)
    result = CliRunner().invoke(cli.app, ["uninstall"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "images, sessions" in result.output
    assert order == ["machines", ["/bin/uv", "tool", "uninstall", "norboten"]]
    assert "norboten is gone" in result.output
    assert not home.exists()


def test_uninstall_can_keep_the_data_and_asks_first(home, monkeypatch, tmp_path):
    monkeypatch.setattr(os, "_exit", lambda code: None)
    (tmp_path / "uv-receipt.toml").write_text(RECEIPT)
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    monkeypatch.setattr(selfmanage, "uv_binary", lambda: "/bin/uv")
    monkeypatch.setattr(selfmanage, "_destroy_machines", lambda say: None)
    ran = []
    monkeypatch.setattr(selfmanage.subprocess, "call", lambda command: ran.append(command) or 0)
    declined = CliRunner().invoke(cli.app, ["uninstall"], input="n\n")
    assert declined.exit_code == 1 and not ran and home.exists()

    kept = CliRunner().invoke(cli.app, ["uninstall", "--yes", "--keep-data"])
    assert kept.exit_code == 0 and ran and (home / "images").exists()


def test_x_in_the_tui_uninstalls_after_it_closes(monkeypatch):
    from norboten.tui import app as tui_app

    monkeypatch.setattr(tui_app, "run", lambda: "uninstall")
    calls = []
    monkeypatch.setattr(cli, "_uninstall", lambda yes, keep_data: calls.append((yes, keep_data)))
    assert CliRunner().invoke(cli.app, []).exit_code == 0
    assert calls == [(True, False)]
