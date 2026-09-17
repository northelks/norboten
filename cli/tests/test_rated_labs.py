"""A rated lab on disk: where it lives, what the linter asks of it, its bundles (lab-spec §13)."""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path

import pytest

from norboten.labs import store
from norboten.labs.lint import lint_lab
from norboten.paths import repo_root
from norboten.session import guest

TEMPLATE = repo_root() / "labs" / "_template"

COLLECT = """import os


def collect(ctx):
    path = "/srv/example/motd"
    if not os.path.exists(path):
        return {"exists": False}
    return {"exists": True, "mode": os.stat(path).st_mode & 0o7777}
"""

JUDGE = """import stat


def judge(facts, ctx):
    if not facts["exists"]:
        return ctx.failed("The welcome message file does not exist any more.")
    if not facts["mode"] & stat.S_IROTH:
        return ctx.failed("Other users still cannot read the welcome message.")
    return ctx.passed("Every user can read the welcome message.")
"""


def make_rated(root: Path, lab_id: str = "linux-90-rated-example") -> Path:
    """The template, turned into a rated lab under <root>/linux/<id>/."""
    lab = root / "linux" / lab_id
    shutil.copytree(TEMPLATE, lab)
    text = (lab / "lab.yaml").read_text().replace("linux-00-template", lab_id)
    (lab / "lab.yaml").write_text(text + "rated: true\n")
    (lab / "collect").mkdir()
    (lab / "collect" / "01_motd_world_readable.py").write_text(COLLECT)
    (lab / "check" / "01_motd_world_readable.py").write_text(JUDGE)
    return lab


@pytest.fixture
def rated(tmp_path: Path) -> Path:
    return make_rated(tmp_path / "rated")


def test_a_rated_lab_lints_clean(rated: Path) -> None:
    assert lint_lab(rated) == []


def test_rated_labs_are_found_only_where_asked(rated: Path, monkeypatch) -> None:
    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(rated.parents[1]))
    assert [lab.id for lab in store.rated_labs()] == ["linux-90-rated-example"]
    assert "linux-90-rated-example" not in {lab.id for lab in store.all_labs()}
    assert store.find("linux-90", include_rated=True).manifest.rated
    with pytest.raises(Exception, match="no lab"):
        store.find("linux-90-rated-example")


def test_rated_needs_collect_and_collect_needs_rated(rated: Path, tmp_path: Path) -> None:
    shutil.rmtree(rated / "collect")
    assert any("needs collect/" in e for e in lint_lab(rated))
    plain = tmp_path / "linux-00-template"
    shutil.copytree(TEMPLATE, plain)
    (plain / "collect").mkdir()
    assert any("belongs to a rated lab" in e for e in lint_lab(plain))


def test_collect_and_check_must_both_match_the_manifest(rated: Path) -> None:
    (rated / "collect" / "02_extra.py").write_text("def collect(ctx):\n    return {}\n")
    assert any("do not match collect/ files" in e for e in lint_lab(rated))


def test_a_collector_never_decides(rated: Path) -> None:
    (rated / "collect" / "01_motd_world_readable.py").write_text(
        "def collect(ctx):\n    return ctx.passed('fine')\n"
    )
    assert any("calls ctx.passed" in e for e in lint_lab(rated))


@pytest.mark.parametrize(
    "body",
    [
        "import subprocess\n\n\ndef judge(facts, ctx):\n    return ctx.passed('x')\n",
        "def judge(facts, ctx):\n    return ctx.passed(open('/etc/shadow').read())\n",
        "def check(ctx):\n    return ctx.passed('x')\n",
    ],
)
def test_a_judge_reads_only_its_facts(rated: Path, body: str) -> None:
    (rated / "check" / "01_motd_world_readable.py").write_text(body)
    assert lint_lab(rated)


def test_a_rated_lab_has_no_journal_and_needs_no_hints(rated: Path) -> None:
    (rated / "hints.yaml").unlink()
    assert lint_lab(rated) == []
    shutil.copy(repo_root() / "labs" / "hello" / "journal.md", rated / "journal.md")
    assert any("no public journal" in e for e in lint_lab(rated))


def test_a_rated_lab_may_not_sit_in_the_public_labs(tmp_path: Path, monkeypatch) -> None:
    import norboten.paths

    fake_root = tmp_path / "repo"
    lab = make_rated(fake_root / "labs")
    monkeypatch.setattr(norboten.paths, "repo_root", lambda: fake_root)
    assert any("never in the public labs/" in e for e in lint_lab(lab))


def _tar(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_a_server_bundle_gets_this_clients_runner() -> None:
    data = guest.bundle_with_runner(_tar({"lab/lab.yaml": b"id: x\n", "lab/collect/01_a.py": b""}))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
    assert "lab/collect/01_a.py" in names
    assert "norboten_runner/collect_runner.py" in names


@pytest.mark.parametrize("name", ["../evil", "lab/../../evil", "elsewhere/x"])
def test_a_server_bundle_cannot_escape_lab(name: str) -> None:
    with pytest.raises(guest.GuestError):
        guest.bundle_with_runner(_tar({name: b"x"}))


def make_rated_container(root: Path, lab_id: str = "linux-91-rated-container") -> Path:
    lab = make_rated(root, lab_id)
    text = (lab / "lab.yaml").read_text()
    text = text.replace(
        "base_images: [ubuntu-26.04, alpine]", "base_images: [ubuntu-26.04-container]"
    )
    text = text.replace("runtime: vm", "runtime: container").replace(
        "reboot_required: true", "reboot_required: false"
    )
    (lab / "lab.yaml").write_text(text)
    return lab


@pytest.mark.docker
def test_the_gate_proves_a_rated_lab_by_collecting_there_and_judging_here(tmp_path: Path) -> None:
    from norboten.labs.manifest import Lab
    from norboten.session.gate import validate

    lab = Lab.load(make_rated_container(tmp_path / "rated"))
    assert lint_lab(lab.path) == []
    result = validate(lab, "ubuntu-26.04-container")
    assert result.ok, result.failures

    # and a solution that fixes nothing is caught, exactly as for an unrated lab
    (lab.path / "solution" / "solution.sh").write_text("#!/bin/sh\ntrue\n")
    broken = validate(lab, "ubuntu-26.04-container")
    assert not broken.ok
    assert any("fails after the solution" in f for f in broken.failures)
