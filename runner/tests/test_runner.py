"""The guest runner, exercised on the host against a throwaway lab directory."""

import json
import os
import textwrap

import pytest

from norboten_runner import break_runner, check_runner, context, report


@pytest.fixture
def lab(tmp_path, monkeypatch):
    state = tmp_path / "state" / "state.json"
    monkeypatch.setattr(context, "STATE_FILE", str(state))
    d = tmp_path / "lab"
    (d / "break").mkdir(parents=True)
    (d / "check").mkdir()
    target = tmp_path / "target.txt"
    (d / "break" / "01_write.py").write_text(
        textwrap.dedent(f"""
        def apply(ctx):
            ctx.state["word"] = "inode"
            ctx.write({str(target)!r}, "broken\\n")
        """)
    )
    (d / "check" / "01_fixed.py").write_text(
        textwrap.dedent(f"""
        def check(ctx):
            text = ctx.read({str(target)!r}) or ""
            if text.strip() != ctx.state["word"]:
                return ctx.failed("target does not hold the word", text)
            return ctx.passed("fixed")
        """)
    )
    (d / "check" / "02_crashes.py").write_text("def check(ctx):\n    raise RuntimeError('boom')\n")
    (d / "check" / "03_no_result.py").write_text("def check(ctx):\n    return None\n")
    return d, target


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_break_then_check_roundtrip(lab, capsys):
    d, target = lab
    assert break_runner.main([str(d), "--learner", "nobody"]) == 0
    assert _emitted(capsys) == {"applied": ["01_write"]}

    assert check_runner.main([str(d), "--learner", "nobody"]) == 0
    results = {r["id"]: r for r in _emitted(capsys)["results"]}
    assert results["01_fixed"]["passed"] is False

    target.write_text("inode\n")
    check_runner.main([str(d), "--learner", "nobody"])
    results = {r["id"]: r for r in _emitted(capsys)["results"]}
    assert results["01_fixed"]["passed"] is True


def test_crashing_and_silent_checks_fail_safely(lab, capsys):
    d, _ = lab
    break_runner.main([str(d), "--learner", "nobody"])
    capsys.readouterr()
    check_runner.main([str(d), "--learner", "nobody"])
    results = {r["id"]: r for r in _emitted(capsys)["results"]}
    assert results["02_crashes"]["passed"] is False
    assert "boom" in results["02_crashes"]["message"]
    assert results["03_no_result"]["passed"] is False


def test_failing_break_script_reports_which(lab, capsys):
    d, _ = lab
    (d / "break" / "02_bad.py").write_text("def apply(ctx):\n    raise ValueError('nope')\n")
    assert break_runner.main([str(d), "--learner", "nobody"]) == 1
    out = _emitted(capsys)
    assert out["script"] == "02_bad"
    assert "nope" in out["error"]


def test_state_file_is_private(lab, capsys):
    d, _ = lab
    break_runner.main([str(d), "--learner", "nobody"])
    assert oct(os.stat(context.STATE_FILE).st_mode & 0o777) == "0o600"


def test_evidence_is_truncated():
    r = report.make_result("x", False, "m", "y" * 10_000)
    assert len(r["evidence"]) == report.EVIDENCE_LIMIT


def test_run_captures_and_times_out(tmp_path):
    ctx = context.Context(
        str(tmp_path), phase="live", learner="nobody", state_file=str(tmp_path / "s.json")
    )
    assert ctx.run("echo hi").out.strip() == "hi"
    assert ctx.run(["false"]).code == 1
    assert ctx.run("sleep 5", timeout=0.2).code == 124
    assert ctx.run(["definitely-not-a-command"]).code == 127
    with pytest.raises(context.CommandFailed):
        ctx.run(["false"], check=True)
