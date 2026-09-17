"""Recording a terminal: the PTY, the asciicast it produces, and what counts as a command."""

import json

import pytest

from norboten.play.recorder import Command, Frame, Recording, _typed_lines, drive, record
from norboten.play.session import Play


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path))


def _text(rec: Recording) -> str:
    return "".join(f.data for f in rec.frames)


def test_a_recording_captures_the_programs_output():
    rec, code = record(["sh", "-c", "printf 'ledger is running\\n'"])
    assert code == 0
    assert "ledger is running" in _text(rec)
    assert rec.duration > 0


def test_a_failing_command_keeps_its_exit_status():
    _, code = record(["sh", "-c", "exit 3"])
    assert code == 3


def test_the_asciicast_is_a_header_then_one_event_per_line():
    rec, _ = record(["sh", "-c", "printf 'a\\nb\\n'"])
    lines = rec.asciicast().strip().splitlines()
    header = json.loads(lines[0])
    assert header["version"] == 2
    assert header["width"] == rec.width and header["height"] == rec.height
    for line in lines[1:]:
        at, kind, _data = json.loads(line)
        assert kind in ("o", "i")
        assert at >= 0


def test_the_recording_is_written_where_asciinema_can_read_it(tmp_path):
    rec = Recording(width=80, height=24, started_at=0.0, title="t")
    rec.frames.append(Frame(0.5, "o", "hello\r\n"))
    target = tmp_path / "plays" / "x.cast"
    rec.write(target)
    lines = target.read_text().strip().splitlines()
    assert json.loads(lines[0])["title"] == "t"
    assert json.loads(lines[1]) == [0.5, "o", "hello\r\n"]


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (b"ls -la\r", ["ls -la"]),
        (b"cd /etc\n", ["cd /etc"]),
        (b"one\rtwo\r", ["one", "two"]),
        (b"  spaced  \r", ["spaced"]),
        (b"\r\r\r", []),  # bare enters are not commands
        (b"systemctl\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7f\x7fdf -h\r", ["df -h"]),  # backspace
        (b"rm -rf /\x03df\r", ["df"]),  # Ctrl-C abandons the line
    ],
)
def test_what_counts_as_a_typed_command(keys, expected):
    assert _typed_lines(bytearray(), keys) == expected


def test_a_command_is_only_counted_when_enter_lands():
    buffer = bytearray()
    assert _typed_lines(buffer, b"systemctl resta") == []
    assert _typed_lines(buffer, b"rt ledger\r") == ["systemctl restart ledger"]


def test_batches_are_handed_over_as_the_session_runs():
    seen: list[tuple[int, int]] = []

    def on_frames(frames: list[Frame], commands: list[Command]) -> None:
        seen.append((len(frames), len(commands)))

    rec, _ = record(
        ["sh", "-c", "printf 'x\\n'"], on_frames=on_frames, flush_every=0.0, clock=_fake_clock()
    )
    assert seen, "the recorder never flushed"
    assert sum(n for n, _ in seen) == len(rec.frames)


def _fake_clock():
    """A clock that always moves, so flush_every=0 flushes every time."""
    ticks = iter(range(1, 10_000))
    return lambda: float(next(ticks)) / 10


def test_a_failing_uploader_does_not_break_the_session():
    def explode(frames, commands):
        raise RuntimeError("the API is down")

    rec, code = record(["sh", "-c", "printf 'still here\\n'"], on_frames=explode, flush_every=0.0)
    assert code == 0
    assert "still here" in _text(rec)


# -- scripted recording (how the site's canned sessions are made) --------------------------------


def test_a_scripted_session_runs_real_commands():
    rec = drive(
        ["sh"],
        ["echo alpha", "#wait 0.2", "echo beta"],
        title="scripted",
        cols=90,
        rows=24,
        type_delay=0.0,
        settle=0.15,
    )
    text = _text(rec)
    assert "alpha" in text and "beta" in text
    assert [c.text for c in rec.commands] == ["echo alpha", "echo beta"]
    assert rec.width == 90 and rec.height == 24


def test_a_scripted_session_skips_comments_and_blank_lines():
    rec = drive(["sh"], ["", "// a note", "echo only"], type_delay=0.0, settle=0.15)
    assert [c.text for c in rec.commands] == ["echo only"]


def test_the_commands_are_reported_as_they_run():
    seen: list[str] = []
    drive(
        ["sh"],
        ["echo one", "echo two"],
        type_delay=0.0,
        settle=0.15,
        on_command=seen.append,
    )
    assert seen == ["echo one", "echo two"]


# -- the saved log ------------------------------------------------------------------------------


def test_saving_writes_the_cast_and_the_command_log(tmp_path):
    play = Play(inst=None, lab_id="hello", title="A Message")
    play.changes.append({"path": "/etc", "diff": "--- a\n+++ b\n", "command": "vi /etc/hosts"})
    rec = Recording(width=80, height=24, started_at=1_700_000_000.0)
    rec.frames.append(Frame(0.1, "o", "hi"))
    rec.commands.append(Command(0.2, "ls"))
    rec.duration = 1.5

    cast = play.save(rec)
    assert cast.exists() and cast.suffix == ".cast"
    log = json.loads(cast.with_suffix(".log.json").read_text())
    assert log["lab_id"] == "hello"
    assert log["commands"] == [{"at": 0.2, "text": "ls"}]
    assert log["changes"][0]["command"] == "vi /etc/hosts"
    assert log["duration"] == 1.5
