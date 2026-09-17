"""Record a terminal session as asciicast v2, without getting in its way.

The learner's shell runs in a pseudo-terminal; we sit in the middle copying bytes and writing down
what crossed. That is the only honest way to record a session: a wrapper that interpreted commands
itself would be wrong about pipes, editors, `less`, tab completion and colour.

The format is asciicast v2 (github.com/asciinema/asciinema/blob/develop/doc/asciicast-v2.md): one
JSON header line, then one `[time, "o"|"i", data]` array per line. It is the format the player on
the site reads, and `asciinema play` reads it too, so a recording is not locked in here.

Two things are lifted out of the stream as it goes:

* **commands** — the bytes the learner typed up to each Enter. This is what they *typed*, not what
  the shell ran: a heredoc, or anything typed inside vim, is not a command and is not claimed to
  be one.
* **idle** — long gaps are recorded as they happened. The player squeezes them; the recording does
  not lie about them.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import io
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import sys
import termios
import time
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

#: How much PTY output to read at once. Big enough for a screen repaint.
CHUNK = 65536

#: Control characters that end a typed line.
ENTER = (b"\r", b"\n")


@dataclass
class Frame:
    at: float  # seconds since the recording started
    kind: str  # "o" output, "i" input
    data: str

    def as_event(self) -> list:
        return [round(self.at, 6), self.kind, self.data]


@dataclass
class Command:
    at: float
    text: str


@dataclass
class Recording:
    """The header plus everything captured. Serialises to an asciicast v2 file."""

    width: int
    height: int
    started_at: float
    title: str = ""
    frames: list[Frame] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    duration: float = 0.0

    def header(self) -> dict:
        return {
            "version": 2,
            "width": self.width,
            "height": self.height,
            "timestamp": int(self.started_at),
            "title": self.title,
            "env": {"TERM": os.environ.get("TERM", "xterm-256color"), "SHELL": "/bin/bash"},
        }

    def asciicast(self) -> str:
        lines = [json.dumps(self.header())]
        lines += [json.dumps(f.as_event()) for f in self.frames]
        return "\n".join(lines) + "\n"

    def write(self, path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.asciicast())


def terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _fd(stream) -> int:
    """A stream's file descriptor, or -1 when it has none.

    Not every stdio is a file: a test harness, a GUI launcher or a redirect can hand us an object
    with no descriptor at all. Recording still works — there is just no terminal to mirror to.
    """
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        return -1
    return fd if isinstance(fd, int) and fd >= 0 else -1


def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty()) and _fd(stream) >= 0
    except (AttributeError, OSError, ValueError):
        return False


class _RawStdin:
    """cbreak on the real terminal while the child owns the screen; a no-op when piped."""

    def __init__(self) -> None:
        self.fd = _fd(sys.stdin) if _is_tty(sys.stdin) else -1
        self.saved = None

    def __enter__(self) -> _RawStdin:
        if self.fd >= 0:
            self.saved = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
        return self

    def __exit__(self, *exc) -> None:
        if self.fd >= 0 and self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


def record(
    argv: Sequence[str],
    *,
    title: str = "",
    on_frames: Callable[[list[Frame], list[Command]], None] | None = None,
    flush_every: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[Recording, int]:
    """Run `argv` in a PTY, mirroring it to this terminal, and record it.

    `on_frames` is called at most every `flush_every` seconds with what is new — that is how the
    live stream is fed without waiting for the session to end. It must not raise; a failing upload
    is not a reason to kill someone's shell.

    Returns (recording, exit status).
    """
    cols, rows = terminal_size()
    rec = Recording(width=cols, height=rows, started_at=time.time(), title=title)

    pid, master = pty.fork()
    if pid == 0:  # the child: become the shell and never come back
        try:
            os.execvp(argv[0], list(argv))
        finally:  # pragma: no cover - only reached if exec failed
            os._exit(127)

    _set_winsize(master, cols, rows)

    pending_frames: list[Frame] = []
    pending_commands: list[Command] = []
    typed = bytearray()
    last_flush = clock()
    start = clock()

    def resized(*_) -> None:
        c, r = terminal_size()
        rec.width, rec.height = c, r
        with _suppress_oserror():
            _set_winsize(master, c, r)

    previous_winch = None
    if _is_tty(sys.stdin):
        previous_winch = signal.signal(signal.SIGWINCH, resized)

    def flush(force: bool = False) -> None:
        nonlocal last_flush
        now = clock()
        if not force and now - last_flush < flush_every:
            return
        last_flush = now
        if on_frames and (pending_frames or pending_commands):
            batch, commands = list(pending_frames), list(pending_commands)
            pending_frames.clear()
            pending_commands.clear()
            with contextlib.suppress(Exception):  # an upload must never break the session
                on_frames(batch, commands)

    stdin_fd = _fd(sys.stdin)
    stdout_fd = _fd(sys.stdout)
    watching = [master, stdin_fd] if stdin_fd >= 0 else [master]
    try:
        with _RawStdin():
            while True:
                try:
                    readable, _, _ = select.select(watching, [], [], 0.2)
                except InterruptedError:  # a SIGWINCH landed mid-select
                    continue

                if master in readable:
                    try:
                        data = os.read(master, CHUNK)
                    except OSError as e:
                        if e.errno != errno.EIO:
                            raise
                        data = b""
                    if not data:
                        break
                    frame = Frame(clock() - start, "o", data.decode("utf-8", "replace"))
                    rec.frames.append(frame)
                    pending_frames.append(frame)
                    if stdout_fd >= 0:
                        with _suppress_oserror():
                            os.write(stdout_fd, data)

                if stdin_fd >= 0 and stdin_fd in readable:
                    data = os.read(stdin_fd, CHUNK)
                    if not data:
                        # Our input is gone (a pipe, or the terminal closed). Pass the EOF on
                        # once and stop watching, or select would report it ready forever.
                        watching.remove(stdin_fd)
                        with _suppress_oserror():
                            os.write(master, b"\x04")
                    else:
                        os.write(master, data)
                        for command in _typed_lines(typed, data):
                            pending_commands.append(Command(clock() - start, command))
                            rec.commands.append(pending_commands[-1])

                flush()
    finally:
        if previous_winch is not None:
            signal.signal(signal.SIGWINCH, previous_winch)
        with _suppress_oserror():
            os.close(master)

    rec.duration = clock() - start
    flush(force=True)
    _, status = os.waitpid(pid, 0)
    return rec, os.waitstatus_to_exitcode(status)


def drive(
    argv: Sequence[str],
    script: Sequence[str],
    *,
    title: str = "",
    cols: int = 100,
    rows: int = 28,
    type_delay: float = 0.045,
    settle: float = 0.5,
    line_timeout: float = 60.0,
    on_command: Callable[[str], None] | None = None,
) -> Recording:
    """Run a session from a script instead of a keyboard, and record it.

    This is how the recordings on the site are made: a real shell, on a real VM, doing real work —
    only the typing is scheduled rather than human. Each line is typed at `type_delay` per
    character, then we wait for the output to go quiet before the next one, so the pauses in the
    recording are the machine's own.

    A line starting with `#wait ` sleeps instead of typing, which is how a recording shows a
    reboot or a timer firing.
    """
    rec = Recording(width=cols, height=rows, started_at=time.time(), title=title)
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.execvp(argv[0], list(argv))
        finally:  # pragma: no cover
            os._exit(127)
    _set_winsize(master, cols, rows)

    start = time.monotonic()

    def pump(until_quiet: float, deadline: float) -> None:
        """Copy output until it has been quiet for `until_quiet`, or the deadline passes."""
        last = time.monotonic()
        while True:
            timeout = max(0.0, min(until_quiet, deadline - time.monotonic()))
            readable, _, _ = select.select([master], [], [], timeout)
            now = time.monotonic()
            if readable:
                try:
                    data = os.read(master, CHUNK)
                except OSError:
                    return
                if not data:
                    return
                rec.frames.append(Frame(now - start, "o", data.decode("utf-8", "replace")))
                last = now
                continue
            if now - last >= until_quiet or now >= deadline:
                return

    def type_line(line: str) -> None:
        for char in line:
            os.write(master, char.encode())
            pump(0.0, time.monotonic() + type_delay)
            time.sleep(type_delay)
        os.write(master, b"\r")

    try:
        pump(settle, time.monotonic() + 20)  # the prompt
        steps = iter(script)
        for raw in steps:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("//"):
                continue
            if line.startswith("#wait "):
                seconds = float(line.split(" ", 1)[1])
                pump(seconds, time.monotonic() + seconds)
                continue

            type_line(line)
            # A heredoc's body is part of the command that opened it, not a command of its own.
            terminator = _heredoc_terminator(line)
            while terminator is not None:
                body = next(steps, None)
                if body is None:
                    break
                type_line(body.rstrip("\n"))
                if body.strip() == terminator:
                    terminator = None

            rec.commands.append(Command(time.monotonic() - start, line))
            if on_command:
                on_command(line)
            pump(settle, time.monotonic() + line_timeout)
        os.write(master, b"exit\r")
        pump(settle, time.monotonic() + 10)
    finally:
        with _suppress_oserror():
            os.close(master)
        with _suppress_oserror():
            os.waitpid(pid, 0)

    rec.duration = time.monotonic() - start
    return rec


_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _heredoc_terminator(line: str) -> str | None:
    """The word that closes a heredoc opened on this line, if it opens one."""
    match = _HEREDOC.search(line)
    return match.group(2) if match else None


def _typed_lines(buffer: bytearray, data: bytes) -> list[str]:
    """Accumulate keystrokes and return the lines completed by this chunk."""
    out: list[str] = []
    for byte in data:
        char = bytes([byte])
        if char in ENTER:
            text = buffer.decode("utf-8", "replace").strip()
            buffer.clear()
            if text:
                out.append(text)
        elif char in (b"\x7f", b"\x08"):  # backspace
            if buffer:
                buffer.pop()
        elif char == b"\x03":  # Ctrl-C abandons the line
            buffer.clear()
        elif byte >= 0x20:
            buffer.extend(char)
    return out


class _suppress_oserror:
    """The terminal or the PTY can go away under us; that is the end of the session, not a crash."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, *_) -> bool:
        return bool(kind and issubclass(kind, OSError))
