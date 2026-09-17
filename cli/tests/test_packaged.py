"""An installed norboten has no checkout: its labs, banks and journals come from the wheel."""

import shutil
from pathlib import Path

import pytest

from norboten import journal, paths
from norboten.labs import manifest, store
from norboten.quiz import bank

ROOT = paths.repo_root()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend to be a wheel: no checkout, content in a data directory, an empty home."""
    content = tmp_path / "content"
    shutil.copytree(ROOT / "labs" / "hello", content / "labs" / "hello")
    shutil.copytree(ROOT / "quizzes", content / "quizzes")
    (content / "journals").mkdir()
    shutil.copy(ROOT / "journals" / "networking.md", content / "journals")
    registry = paths.registry_file()
    monkeypatch.setattr(paths, "repo_root", lambda: None)
    monkeypatch.setattr(manifest, "registry_file", lambda: registry)
    monkeypatch.setattr(paths, "packaged_content", lambda: content)
    monkeypatch.setattr(store, "packaged_content", lambda: content)
    monkeypatch.delenv("NORBOTEN_LABS_DIR", raising=False)
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))
    return content


def _cache(lab_dir: Path, version: str) -> Path:
    target = store.cache_dir() / "hello" / version
    shutil.copytree(lab_dir, target)
    manifest = target / "lab.yaml"
    manifest.write_text(manifest.read_text().replace("version: 1.0.0", f"version: {version}"))
    return target


def test_the_wheel_carries_labs_banks_and_journals(installed: Path) -> None:
    assert [lab.id for lab in store.all_labs()] == ["hello"]
    assert {b.topic for b in bank.topic_banks()} >= {"linux", "bash"}
    assert any(b.lab_id == "hello" for b in bank.all_banks())
    ids = {j.id for j in journal.all_journals()}
    assert {"networking", "hello"} <= ids


def test_a_newer_pulled_lab_replaces_the_packaged_one(installed: Path) -> None:
    newer = _cache(installed / "labs" / "hello", "1.1.0")
    [lab] = store.all_labs()
    assert lab.manifest.version == "1.1.0"
    assert lab.path == newer


def test_an_older_pulled_lab_does_not(installed: Path) -> None:
    _cache(installed / "labs" / "hello", "0.9.0")
    [lab] = store.all_labs()
    assert lab.manifest.version == "1.0.0"


def test_a_checkout_always_wins_over_the_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("NORBOTEN_LABS_DIR", raising=False)
    _cache(ROOT / "labs" / "hello", "9.0.0")
    hello = next(lab for lab in store.all_labs() if lab.id == "hello")
    assert hello.manifest.version == "1.0.0"
