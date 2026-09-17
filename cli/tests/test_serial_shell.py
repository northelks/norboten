"""SerialShell against a fake console that behaves like sulogin followed by a root shell."""

import contextlib
import re
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from norboten.lima.serial_shell import SerialShell, SerialShellError


def _console(sock_path: Path, password: str) -> threading.Thread:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def serve() -> None:
        with contextlib.suppress(OSError):  # the client hangs up when a test expects a failure
            _serve()

    def _serve() -> None:
        conn, _ = server.accept()
        conn.sendall(b"Give root password for maintenance\r\n(or press Control-D to continue): ")
        buf, logged_in = b"", False
        while True:
            data = conn.recv(65536)
            if not data:
                break
            buf += data
            while b"\r" in buf:
                line, buf = buf.split(b"\r", 1)
                text = line.decode()
                if not logged_in:
                    if text == password:
                        logged_in = True
                        conn.sendall(b"\r\nsh-5.2# ")
                    elif text:
                        conn.sendall(
                            b"\r\nLogin incorrect\r\nGive root password for maintenance\r\n"
                            b"(or press Control-D to continue): "
                        )
                    continue
                conn.sendall(text.encode() + b"\r\n")  # the tty echoes what was typed
                if text.strip():
                    command = re.sub(r"\bid -u\b", "echo 0", text)  # pretend to be root
                    out = subprocess.run(["sh", "-c", command], capture_output=True).stdout
                    conn.sendall(out.replace(b"\n", b"\r\n"))
                conn.sendall(b"sh-5.2# ")
        conn.close()
        server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


@pytest.fixture
def sock(tmp_path_factory) -> Path:
    # AF_UNIX paths are limited to ~104 bytes; pytest's tmp paths on macOS are longer
    import tempfile

    return Path(tempfile.mkdtemp(prefix="nbs")) / "c.sock"


def test_logs_in_through_sulogin_and_frames_output(sock):
    _console(sock, "norboten")
    with SerialShell(sock, timeout=10) as shell:
        shell.login()
        assert shell.run("echo hello; echo world") == "hello\nworld\n"
        code, out = shell.run_status("echo oops >&2; exit_code() { return 3; }; exit_code")
        assert code == 3 and "oops" in out


def test_a_failing_command_raises(sock):
    _console(sock, "norboten")
    with SerialShell(sock, timeout=10) as shell:
        shell.login()
        with pytest.raises(SerialShellError):
            shell.run("false")


def test_upload_round_trips_binary_data(sock, tmp_path):
    _console(sock, "norboten")
    payload = bytes(range(256)) * 20  # several acknowledged chunks
    dest = tmp_path / "bundle.bin"
    with SerialShell(sock, timeout=10) as shell:
        shell.login()
        shell.upload(payload, str(dest))
    assert dest.read_bytes() == payload


def test_a_wrong_password_never_yields_a_shell(sock):
    _console(sock, "secret")
    with SerialShell(sock, timeout=2) as shell, pytest.raises(SerialShellError):
        shell.login(timeout=4)
