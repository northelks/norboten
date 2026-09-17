"""The claude track's image carries a copy of the scripted model; the copy must not drift."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "images" / "base" / "ubuntu-26.04-claude"


def test_the_image_carries_the_same_fake_api_the_rehearsal_uses():
    original = ROOT / "automation" / "stand_ins" / "fake_anthropic.py"
    assert (IMAGE / "fake_anthropic.py").read_bytes() == original.read_bytes()


def test_the_pinned_version_is_the_one_the_launcher_names():
    dockerfile = (IMAGE / "Dockerfile").read_text()
    assert "ARG CLAUDE_VERSION=2.1.270" in dockerfile
    assert "2.1.270" in (IMAGE / "claude-offline").read_text()
    assert "sha256sum -c" in dockerfile
