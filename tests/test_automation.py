"""The operational jobs: each one rehearsed end to end, and the workflows that run them held to the
rules that keep a model in CI cheap and harmless.

The rehearsal scenarios run a real `claude` against a scripted stand-in model
(automation/rehearse.py) and are skipped where Claude Code is not installed; `make jobs-rehearsal`
runs them all and fails instead of skipping.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation import rehearse  # noqa: E402
from automation.jobs import release  # noqa: E402

WORKFLOWS = {
    p.name: yaml.safe_load(p.read_text()) for p in (ROOT / ".github/workflows").glob("*.yml")
}
PINNED = yaml.safe_load((ROOT / ".github/actions/claude-code/action.yml").read_text())


@pytest.mark.skipif(sys.platform == "win32", reason="the jobs run on Linux runners")
@pytest.mark.parametrize("scenario", list(rehearse.SCENARIOS))
def test_rehearsal(scenario: str) -> None:
    if scenario in rehearse.NEEDS_CLAUDE and shutil.which("claude") is None:
        pytest.skip("Claude Code is not installed")
    rehearse.run_one(scenario)


def _steps(workflow: dict):
    for name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            yield name, job, step


def test_every_job_module_a_workflow_runs_exists() -> None:
    ran = set()
    for workflow in WORKFLOWS.values():
        for _, _, step in _steps(workflow):
            for module in re.findall(r"python3 -m (automation\.jobs\.\w+)", step.get("run", "")):
                ran.add(module)
                assert (ROOT / (module.replace(".", "/") + ".py")).is_file(), module
    modules = {f"automation.jobs.{p.stem}" for p in (ROOT / "automation/jobs").glob("*.py")}
    assert ran == modules - {"automation.jobs.common", "automation.jobs.__init__"}


def test_claude_jobs_are_capped_pinned_and_use_the_subscription_token() -> None:
    claude_jobs = 0
    for file, workflow in WORKFLOWS.items():
        for name, job in workflow["jobs"].items():
            steps = job.get("steps", [])
            if not any(s.get("uses") == "./.github/actions/claude-code" for s in steps):
                continue
            claude_jobs += 1
            where = f"{file}:{name}"
            assert job.get("timeout-minutes", 999) <= 20, f"{where}: a timeout"
            assert job["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
            text = yaml.safe_dump(job)
            assert "ANTHROPIC_API_KEY" not in text, f"{where}: the subscription token, not a key"
            assert "--bare" not in text, f"{where}: --bare ignores CLAUDE_CODE_OAUTH_TOKEN"
            assert "--dangerously-skip-permissions" not in text and "bypassPermissions" not in text
            if "concurrency" not in workflow and "concurrency" not in job:
                raise AssertionError(f"{file}: runs must not pile up")
    assert claude_jobs == 4  # triage, stuck-points, lab-author, release notes


def test_the_installed_claude_code_is_pinned() -> None:
    version = PINNED["inputs"]["version"]["default"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    notes = " ".join((ROOT / "docs/research/claude-code.md").read_text().split())
    assert f"against Claude Code **{version}**" in notes


def test_the_lab_author_subagent_cannot_reach_a_shell() -> None:
    text = (ROOT / ".claude/agents/lab-author.md").read_text()
    front = yaml.safe_load(text.split("---")[1])
    assert front["name"] == "lab-author"
    assert [t.strip() for t in front["tools"].split(",")] == ["Read", "Glob", "Grep", "Write"]
    assert front["model"] == "sonnet" and front["maxTurns"] <= 20


def test_a_rated_lab_request_is_declined_before_any_model_runs(monkeypatch) -> None:
    from automation.jobs import lab_author

    calls: list[tuple] = []
    monkeypatch.setattr(
        lab_author,
        "event",
        lambda: {
            "label": {"name": "lab-request"},
            "issue": {"number": 7, "title": "x", "labels": [{"name": "rated"}]},
        },
    )
    monkeypatch.setattr(lab_author, "draft", lambda *a: calls.append(("draft", a)))
    monkeypatch.setattr(lab_author.GitHub, "__init__", lambda self: None)  # no token, no network
    monkeypatch.setattr(lab_author.GitHub, "call", lambda self, *a, **k: calls.append(a))
    lab_author.main()
    assert calls == [
        ("POST", "/repos/{repo}/issues/7/comments", {"body": lab_author.DECLINE_RATED})
    ]


def test_triage_waits_for_people_not_bots() -> None:
    job = WORKFLOWS["triage.yml"]["jobs"]["triage"]
    assert "Bot" in job["if"]


def test_the_nightly_gate_runs_everything_and_reports() -> None:
    labs = WORKFLOWS["lab-validate.yml"]
    assert labs[True]["schedule"]  # YAML reads the key `on` as True
    pick = labs["jobs"]["matrix"]["steps"][-1]["run"]
    assert "github.event_name == 'schedule'" in pick and "--all" in pick
    report = labs["jobs"]["report"]
    assert "schedule" in report["if"] and "always()" in report["if"]


def test_manifest_fields_reads_what_an_announcement_names() -> None:
    fields = release.manifest_fields(
        "schema_version: 1\nid: linux-02-disk\ntitle: 'The Disk: Full'\ntrack: linux\n"
        "difficulty: 3\nchecks:\n  - id: 01_x\n"
    )
    assert fields == {
        "id": "linux-02-disk",
        "title": "The Disk: Full",
        "track": "linux",
        "difficulty": "3",
    }


def test_the_content_announcer_names_what_a_push_added(monkeypatch) -> None:
    from automation.jobs import announce_content as job

    diff = "\n".join(
        [
            "A\tlabs/linux/linux-07-a-lab/lab.yaml",
            "M\tlabs/linux/linux-01-disk-full/check/01_x.py",
            "A\tlabs/_drafts/not-a-lab.md",
            "A\tjournals/selinux.md",
            "A\tquizzes/selinux.yaml",
            "A\tdocs/architecture.md",
            "A\trated/linux/secret/lab.yaml",
        ]
    )
    shown = {
        "labs/linux/linux-07-a-lab/lab.yaml": "id: linux-07-a-lab\ntitle: A Lab\n",
        "journals/selinux.md": "---\ntitle: SELinux, in practice\n---\n",
        "quizzes/selinux.yaml": "topic: selinux\ntitle: SELinux\n",
    }

    def fake_git(*args: str) -> str:
        if args[0] == "diff":
            return diff
        assert args[0] == "show"
        return shown[args[1].split(":", 1)[1]]

    monkeypatch.setattr(job, "git", fake_git)
    items = job.added("before", "after")
    assert [i["slug"] for i in items] == ["linux-07-a-lab", "selinux", "selinux"]
    assert [i["kind"] for i in items] == ["lab", "journal", "question bank"]
    text = job.message(items, "https://norboten.org")
    assert "https://norboten.org/labs/linux-07-a-lab/" in text
    assert "SELinux, in practice" in text
    assert "rated" not in text, "the private half is never announced"
