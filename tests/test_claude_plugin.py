"""The norboten-author plugin and the marketplace this repository is.

Static checks keep the manifests, skills and agents loadable and in step with the copies CI uses.
The live tests (skipped where Claude Code is not installed) validate the manifests with the real
`claude`, install the plugin from this checkout into a throwaway configuration, and expand each
skill against the scripted Messages API from automation/. No token is spent.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
PLUGIN_DIR = ROOT / "plugins/norboten-author"
PLUGIN = json.loads((PLUGIN_DIR / ".claude-plugin/plugin.json").read_text())
SKILLS = sorted((PLUGIN_DIR / "skills").glob("*/SKILL.md"))
AGENTS = sorted((PLUGIN_DIR / "agents").glob("*.md"))
HAS_CLAUDE = shutil.which("claude") is not None


def _frontmatter(text: str) -> dict:
    assert text.startswith("---\n"), "frontmatter is read only when --- is the first line"
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_the_repository_is_a_marketplace_listing_the_plugin() -> None:
    assert MARKETPLACE["name"] == "norboten"
    (entry,) = MARKETPLACE["plugins"]
    assert entry["name"] == PLUGIN["name"] == "norboten-author"
    assert (ROOT / entry["source"]).resolve() == PLUGIN_DIR
    assert entry["version"] == PLUGIN["version"], "one version, in both manifests"


def test_the_checkout_enables_its_own_plugin() -> None:
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    assert settings["extraKnownMarketplaces"]["norboten"]["source"] == {
        "source": "directory",
        "path": ".",
    }
    assert settings["enabledPlugins"] == {"norboten-author@norboten": True}


def test_the_skills_are_the_content_workflows() -> None:
    assert {p.parent.name for p in SKILLS} == {
        "idea",
        "new-lab",
        "new-questions",
        "new-journal",
        "captures",
    }


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_a_skill_is_user_run_and_cites_only_what_exists(skill: Path) -> None:
    text = skill.read_text()
    meta = _frontmatter(text)
    assert 40 <= len(meta["description"]) <= 1536
    # each one boots machines, spends subscription usage or rewrites committed files
    assert meta["disable-model-invocation"] is True
    for path in set(re.findall(r"`((?:docs|cli|api|site|images|labs|quizzes)/[\w./-]+)`", text)):
        if "<" not in path and not path.endswith("/"):
            assert (ROOT / path).exists(), f"{skill.parent.name} cites {path}"
    for name, source in (
        ("REQUIRED_SECTIONS", "cli/src/norboten/journal.py"),
        ("SHOTS", "site/capture.py"),
    ):
        if name in text:
            assert name in (ROOT / source).read_text()
    for agent in re.findall(r"norboten-author:([a-z-]+-author)", text):
        assert (PLUGIN_DIR / "agents" / f"{agent}.md").is_file(), agent
    for other in re.findall(r"/norboten-author:([a-z-]+)", text):
        assert (PLUGIN_DIR / "skills" / other / "SKILL.md").is_file(), other


@pytest.mark.parametrize("agent", AGENTS, ids=lambda p: p.stem)
def test_an_agent_uses_only_what_a_plugin_agent_may(agent: Path) -> None:
    meta = _frontmatter(agent.read_text())
    assert meta["name"] == agent.stem
    assert 40 <= len(meta["description"]) <= 1536
    # a plugin agent may not carry these; Claude Code ignores them, which would hide a mistake
    assert not {"hooks", "mcpServers", "permissionMode"} & set(meta)
    assert "Write" not in meta["tools"] or agent.stem != "question-author"


def test_ci_and_the_plugin_share_one_lab_author_and_one_hook() -> None:
    # CI's headless runs do not trust the checkout, so they load the project's copies
    assert (ROOT / ".claude/agents/lab-author.md").read_bytes() == (
        PLUGIN_DIR / "agents/lab-author.md"
    ).read_bytes()
    assert (ROOT / ".claude/hooks/after_edit.py").read_bytes() == (
        PLUGIN_DIR / "scripts/after_edit.py"
    ).read_bytes()
    hooks = json.loads((PLUGIN_DIR / "hooks/hooks.json").read_text())["hooks"]
    command = hooks["PostToolUse"][0]["hooks"][0]["command"]
    script = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/(\S+?)\\?\"", command)
    assert script and (PLUGIN_DIR / script.group(1)).is_file(), command


def test_the_plugins_hook_steps_aside_where_the_checkout_has_its_own(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".claude/hooks").mkdir(parents=True)
    shutil.copy(ROOT / ".claude/hooks/after_edit.py", project / ".claude/hooks/after_edit.py")
    (project / "labs/linux/linux-99").mkdir(parents=True)
    (project / "labs/linux/linux-99/lab.yaml").write_text("id: linux-99\n")
    (project / ".venv/bin").mkdir(parents=True)
    linter = project / ".venv/bin/norboten"  # a lint that always fails, and says it ran
    linter.write_text(f"#!/bin/sh\ntouch {tmp_path}/linted\necho broken\nexit 1\n")
    linter.chmod(0o755)
    call = json.dumps({"tool_input": {"file_path": str(project / "labs/linux/linux-99/lab.yaml")}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}

    def run(script: Path) -> int:
        return subprocess.run(
            [sys.executable, str(script)], input=call, env=env, capture_output=True, text=True
        ).returncode

    assert run(PLUGIN_DIR / "scripts/after_edit.py") == 0
    assert not (tmp_path / "linted").exists(), "the plugin's copy linted as well"
    assert run(project / ".claude/hooks/after_edit.py") == 2
    assert (tmp_path / "linted").exists()


@pytest.mark.skipif(not HAS_CLAUDE, reason="Claude Code is not installed")
@pytest.mark.parametrize("target", [".", "plugins/norboten-author"])
def test_claude_validates_the_manifests_strictly(target: str) -> None:
    done = subprocess.run(
        ["claude", "plugin", "validate", "--strict", target],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.fixture(scope="module")
def installed(tmp_path_factory) -> dict:
    """A throwaway Claude Code configuration with the plugin installed from this checkout."""
    home = tmp_path_factory.mktemp("claude-home").resolve()
    (home / "config").mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(home / "config"),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    for args in (
        ["plugin", "marketplace", "add", str(ROOT)],
        ["plugin", "install", "norboten-author@norboten"],
    ):
        done = subprocess.run(
            ["claude", *args], env=env, capture_output=True, text=True, timeout=120
        )
        assert done.returncode == 0, done.stdout + done.stderr
    return env


@pytest.mark.skipif(not HAS_CLAUDE, reason="Claude Code is not installed")
@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_an_installed_skill_expands_in_a_real_claude(
    skill: Path, installed: dict, tmp_path: Path
) -> None:
    sys.path.insert(0, str(ROOT))
    from automation.stand_ins import fake_anthropic

    server, script = fake_anthropic.serve(0)
    script.load([{"text": "ok"}])
    env = {
        **installed,
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-test",
    }
    name = skill.parent.name
    try:
        done = subprocess.run(
            [
                "claude",
                "-p",
                f"/norboten-author:{name} ARG-MARKER",
                "--output-format",
                "json",
                "--max-turns",
                "1",
            ],
            cwd=tmp_path,
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        server.shutdown()
    assert json.loads(done.stdout).get("is_error") is False, done.stdout[-400:]
    sent = json.dumps(script.requests[0]["messages"])
    heading = next(line for line in skill.read_text().splitlines() if line.startswith("# "))
    assert json.dumps(heading)[1:-1] in sent, f"/norboten-author:{name} did not expand"
    assert "ARG-MARKER" in sent and "$ARGUMENTS" not in sent
    agents = json.dumps(script.requests[0])
    for agent in ("lab-author", "question-author", "journal-author"):
        assert f"norboten-author:{agent}" in agents, f"{agent} is not offered to the model"


@pytest.mark.parametrize("name", ["idea", "new-lab", "new-questions"])
def test_a_writing_skill_asks_rated_or_unrated_and_keeps_rated_in_rated(name: str) -> None:
    text = (PLUGIN_DIR / "skills" / name / "SKILL.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert "--rated" in front["argument-hint"] and "--unrated" in front["argument-hint"]
    assert "default" in text and "unrated" in text
    assert "rated/README.md" in text  # the guard: an empty submodule is never written into


def test_journals_refuse_a_rated_lab() -> None:
    for path in ("skills/new-journal/SKILL.md", "agents/journal-author.md"):
        assert (
            "rated" in (PLUGIN_DIR / path).read_text()
            and "no public journal" in (PLUGIN_DIR / path).read_text()
        )


def test_the_hook_lints_a_rated_lab_too(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".claude/hooks").mkdir(parents=True)
    shutil.copy(ROOT / ".claude/hooks/after_edit.py", project / ".claude/hooks/after_edit.py")
    lab = project / "rated/linux/linux-98"
    lab.mkdir(parents=True)
    (lab / "lab.yaml").write_text("id: linux-98\n")
    (project / ".venv/bin").mkdir(parents=True)
    linter = project / ".venv/bin/norboten"
    linter.write_text(f'#!/bin/sh\necho "$3" > {tmp_path}/linted\nexit 1\n')
    linter.chmod(0o755)
    call = json.dumps({"tool_input": {"file_path": str(lab / "lab.yaml")}})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    done = subprocess.run(
        [sys.executable, str(project / ".claude/hooks/after_edit.py")],
        input=call,
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    assert (tmp_path / "linted").read_text().strip() == str(lab)


def test_rated_drafting_refuses_an_empty_submodule(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from norboten import cli

    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(tmp_path / "empty"))
    result = CliRunner().invoke(cli.app, ["dev", "draft-questions", "bash", "--rated"])
    assert result.exit_code != 0 and "not checked out" in result.output
