"""The checked-in Claude Code setup: CLAUDE.md, `.claude/settings.json` and its hook.

Static checks keep it loadable and short. The live test (skipped where Claude Code is not
installed) runs the real `claude` in a scratch copy of the project against the scripted Messages
API from automation/: a scripted model edits a Python file and breaks a lab, then reads a secret
and pushes — and the test checks what the hooks and deny rules did about each, on disk and in what
the model was sent back. Each skill is expanded by the real `claude` too. No token is spent.
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

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = json.loads((ROOT / ".claude/settings.json").read_text())


def test_claude_md_stays_short() -> None:
    # every Claude Code run in the checkout loads it, the lab-author CI job included
    assert len((ROOT / "CLAUDE.md").read_text().splitlines()) <= 80


def test_hook_matchers_name_real_tools_and_their_commands_exist() -> None:
    for event, groups in SETTINGS["hooks"].items():
        for group in groups:
            # a lower-case `edit` never fires (docs/research/claude-code.md §14)
            for tool in group["matcher"].split("|"):
                assert re.fullmatch(r"[A-Z][A-Za-z]+", tool), f"{event}: {tool!r}"
            for hook in group["hooks"]:
                script = re.search(r"\$CLAUDE_PROJECT_DIR/(\S+?)\"?$", hook["command"])
                assert script and (ROOT / script.group(1)).is_file(), hook["command"]


def test_deny_rules_cover_pushes_and_every_ignored_secret() -> None:
    deny = SETTINGS["permissions"]["deny"]
    assert {"Bash(git push)", "Bash(git push *)"} <= set(deny)
    # Write(...) path rules are accepted but never consulted; Edit(...) and Read(...) are
    assert not [r for r in deny if r.startswith(("Write(", "Glob(", "MultiEdit("))]
    for secret in (".env", ".env.local", "*.pem", "*.key", "*.tfstate"):
        assert f"Read({secret})" in deny, secret
    assert "Read(/ansible/group_vars/all/vault.yml)" in deny
    assert "Read(/terraform/terraform.tfvars)" in deny
    # .env.example is documentation, and a bare .env.* rule would hide it
    assert "Read(.env.*)" not in deny


def test_the_hook_finds_the_lab_a_file_belongs_to(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / ".claude/hooks"))
    from after_edit import lab_of

    labs = tmp_path / "labs"
    for lab in ("hello", "linux/linux-01-x", "_template"):
        (labs / lab / "check").mkdir(parents=True)
        (labs / lab / "lab.yaml").write_text("id: x\n")
    (labs / "_drafts").mkdir()
    assert lab_of(labs / "hello/check/01.py", labs) == labs / "hello"
    assert lab_of(labs / "linux/linux-01-x/lab.yaml", labs) == labs / "linux/linux-01-x"
    assert lab_of(labs / "_template/lab.yaml", labs) is None
    assert lab_of(labs / "_drafts/linux-02-y.md", labs) is None
    assert lab_of(tmp_path / "README.md", labs) is None


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code is not installed")
@pytest.mark.skipif(not (ROOT / ".venv/bin/norboten").is_file(), reason="no venv to lint with")
def test_hooks_and_deny_rules_in_a_real_claude_session(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from automation.stand_ins import fake_anthropic

    project = tmp_path.resolve() / "project"
    shutil.copytree(ROOT / ".claude", project / ".claude", ignore=shutil.ignore_patterns("*.pyc"))
    shutil.copy(ROOT / "CLAUDE.md", project / "CLAUDE.md")
    shutil.copytree(ROOT / "labs/hello", project / "labs/hello")
    (project / "deploy").mkdir()
    (project / "deploy/.env").write_text("POSTGRES_PASSWORD=never-leaves-the-machine\n")
    (project / ".venv").symlink_to(ROOT / ".venv")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    manifest = (project / "labs/hello/lab.yaml").read_text()
    broken = re.sub(r"(?m)^difficulty: .*$", "difficulty: 9", manifest)
    assert broken != manifest
    steps = [
        {"tool": "Write", "input": {"file_path": str(project / "tool.py"), "content": "x=1\n"}},
        {
            "tool": "Write",
            "input": {"file_path": str(project / "labs/hello/lab.yaml"), "content": broken},
        },
        {"tool": "Read", "input": {"file_path": str(project / "deploy/.env")}},
        {"tool": "Bash", "input": {"command": "git push origin main"}},
        {"text": "done"},
    ]
    server, script = fake_anthropic.serve(0)
    script.load(steps)
    config = tmp_path / "config"
    config.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-test",
        "CLAUDE_CONFIG_DIR": str(config),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    try:
        done = subprocess.run(
            [
                "claude",
                "-p",
                "go",
                "--output-format",
                "json",
                "--no-session-persistence",
                # everything allowed on the command line: the project's deny rules still win
                "--allowedTools",
                "Read,Write,Edit,Bash",
                "--max-turns",
                "10",
            ],
            cwd=project,
            env=env,
            input="",
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
    result = json.loads(done.stdout)
    assert not result.get("is_error"), done.stdout[-600:]

    # the Python file was formatted by the hook
    assert (project / "tool.py").read_text() == "x = 1\n"

    # the broken lab was written, and the lint failure went back to the model
    assert "difficulty: 9" in (project / "labs/hello/lab.yaml").read_text()
    after_lab_write = json.dumps(script.requests[2]["messages"])
    assert "norboten dev lint labs/hello fails" in after_lab_write
    after_py_write = json.dumps(script.requests[1]["messages"])
    assert "labs/hello fails" not in after_py_write

    # the secret and the push were denied despite --allowedTools
    denied = {d["tool_name"]: d["tool_input"] for d in result["permission_denials"]}
    assert denied.get("Read", {}).get("file_path", "").endswith("deploy/.env")
    assert denied.get("Bash", {}).get("command") == "git push origin main"
    assert "never-leaves-the-machine" not in json.dumps(script.requests)
