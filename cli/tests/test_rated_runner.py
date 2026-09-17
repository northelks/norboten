"""The rated half of the runner: collect in the guest, sign, judge elsewhere (lab-spec §13)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from norboten_runner import collect_runner, judge, signing

KEY = "ab" * 32


def _lab(tmp_path: Path) -> Path:
    (tmp_path / "collect").mkdir()
    (tmp_path / "check").mkdir()
    (tmp_path / "collect" / "01_port.py").write_text(
        "def collect(ctx):\n    return {'port': ctx.state.get('port', 0), 'phase': ctx.phase}\n"
    )
    (tmp_path / "collect" / "02_boom.py").write_text("def collect(ctx):\n    raise OSError('no')\n")
    (tmp_path / "collect" / "03_huge.py").write_text(
        "def collect(ctx):\n    return {'x': 'y' * 70000}\n"
    )
    (tmp_path / "check" / "01_port.py").write_text(
        "def judge(facts, ctx):\n"
        "    if facts['port'] == 8080:\n"
        "        return ctx.passed('right port')\n"
        "    return ctx.failed('wrong port')\n"
    )
    (tmp_path / "check" / "02_boom.py").write_text(
        "def judge(facts, ctx):\n    return ctx.passed('')\n"
    )
    (tmp_path / "check" / "03_huge.py").write_text("def judge(facts, ctx):\n    1 / 0\n")
    return tmp_path


def _collect(tmp_path, monkeypatch, capsys, state: dict) -> dict:
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    real = collect_runner.Context

    def ctx(lab_dir, **kw):
        return real(lab_dir, state_file=str(state_file), **kw)

    monkeypatch.setattr(collect_runner, "Context", ctx)
    monkeypatch.setattr(sys, "stdin", io.StringIO(KEY + "\n"))
    code = collect_runner.main(
        [str(tmp_path), "--phase", "pre_reboot", "--learner", "nobody", "--attempt", "a1",
         "--nonce", "n1"]
    )  # fmt: skip
    assert code == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_collected_record_is_signed_and_carries_no_verdict(tmp_path, monkeypatch, capsys) -> None:
    out = _collect(_lab(tmp_path), monkeypatch, capsys, {"port": 8080})
    record = out["record"]
    assert record["attempt"] == "a1" and record["nonce"] == "n1"
    assert record["facts"]["01_port"] == {"port": 8080, "phase": "pre_reboot"}
    assert "collect_error" in record["facts"]["02_boom"]
    assert "limit" in record["facts"]["03_huge"]["collect_error"]
    assert "passed" not in json.dumps(record["facts"])
    assert signing.verify(KEY, record, out["signature"])


def test_a_changed_record_or_another_key_does_not_verify(tmp_path, monkeypatch, capsys) -> None:
    out = _collect(_lab(tmp_path), monkeypatch, capsys, {"port": 1})
    forged = json.loads(json.dumps(out["record"]))
    forged["facts"]["01_port"]["port"] = 8080
    assert not signing.verify(KEY, forged, out["signature"])
    assert not signing.verify("cd" * 32, out["record"], out["signature"])
    assert not signing.verify("not hex", out["record"], out["signature"])


@pytest.mark.parametrize(("port", "passed"), [(8080, True), (22, False)])
def test_the_judge_decides_from_the_facts(tmp_path, monkeypatch, capsys, port, passed) -> None:
    lab = _lab(tmp_path)
    record = _collect(lab, monkeypatch, capsys, {"port": port})["record"]
    results = {r["id"]: r for r in judge.judge_record(str(lab), record)}
    assert results["01_port"]["passed"] is passed
    assert results["02_boom"]["passed"] is False  # a failed collector fails its check
    assert results["03_huge"]["passed"] is False
    assert list(results) == ["01_port", "02_boom", "03_huge"]


def test_a_missing_fact_fails_and_a_crashing_judge_fails(tmp_path) -> None:
    lab = _lab(tmp_path)
    results = judge.judge_record(str(lab), {"phase": "pre_reboot", "facts": {"03_huge": {}}})
    assert [r["passed"] for r in results] == [False, False, False]
    assert "crashed" in results[2]["message"]
