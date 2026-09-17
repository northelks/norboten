"""A root shell over a guest's serial console, for a machine that has no network.

The solvability gate needs this for `boot_after_break` labs (docs/open-questions.md Q18): after the
break and one more boot, a lab such as rhcsa-03 stops at a maintenance prompt, with no SSH. The
serial port still has a login prompt or sulogin, and the golden images' root password is known, so
the gate can log in there, ship the runner across in small acknowledged chunks, and run the checks.

Commands are framed by markers the shell prints, never by prompts: a marker is split in the typed
command (`printf 'NB%sB' token`) so the echo of the command cannot be mistaken for its output.
"""

from __future__ import annotations

import base64
import re
import secrets
import socket
import time
from pathlib import Path

ROOT_PASSWORD = "norboten"  # docs/lab-spec.md section 3: the golden images' root password
_CHUNK = 900  # base64 characters per acknowledged write: well under a tty's 4096-byte line limit


class SerialShellError(RuntimeError):
    pass


class SerialShell:
    def __init__(self, sock_path: Path, *, timeout: float = 10.0) -> None:
        if not sock_path.exists():
            raise SerialShellError(f"{sock_path} does not exist — is the VM running?")
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(str(sock_path))
        self._sock.settimeout(0.2)
        self._buf = ""
        self.timeout = timeout
        self.transcript: list[str] = []

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> SerialShell:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low level --------------------------------------------------------------------------

    def _send(self, text: str) -> None:
        self._sock.sendall(text.encode())

    def _read_until(self, pattern: re.Pattern[str], timeout: float) -> re.Match[str]:
        deadline = time.monotonic() + timeout
        while True:
            match = pattern.search(self._buf)
            if match:
                return match
            if time.monotonic() > deadline:
                tail = self._buf[-800:]
                raise SerialShellError(
                    f"timed out waiting for {pattern.pattern!r}; console:\n{tail}"
                )
            try:
                data = self._sock.recv(65536)
            except TimeoutError:
                continue
            if not data:
                raise SerialShellError("the serial console closed")
            text = data.decode(errors="replace").replace("\r", "")
            self._buf += text
            self.transcript.append(text)

    def _consume(self, match: re.Match[str]) -> None:
        self._buf = self._buf[match.end() :]

    # -- a shell ----------------------------------------------------------------------------

    def login(self, password: str = ROOT_PASSWORD, timeout: float = 60.0) -> None:
        """Get a root shell from whatever the console shows: sulogin, a getty, or a shell."""
        prompts = re.compile(
            r"(Give root password for maintenance|Password:|login:\s*$|[#$]\s*$)", re.M
        )
        self._send("\r")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            match = self._read_until(prompts, timeout=max(1.0, deadline - time.monotonic()))
            seen = match.group(1)
            self._consume(match)
            if seen.startswith("Give root password"):
                self._read_until(re.compile(r"\):\s*"), timeout=5)  # "(or press Control-D …):"
                self._buf = ""
                self._send(password + "\r")
            elif seen == "Password:":
                self._send(password + "\r")
            elif seen.startswith("login"):
                self._send("root\r")
            else:
                if self.run("id -u", timeout=10).strip() == "0":
                    return
                raise SerialShellError("got a shell on the console, but not as root")
        raise SerialShellError("no root shell on the serial console")

    def run(self, command: str, timeout: float | None = None) -> str:
        """Run a command, return its combined output. Raises if the exit status is not zero."""
        code, out = self.run_status(command, timeout)
        if code != 0:
            raise SerialShellError(f"{command[:80]!r} exited {code}: {out[-500:]}")
        return out

    def run_status(self, command: str, timeout: float | None = None) -> tuple[int, str]:
        token = secrets.token_hex(4)
        begin = re.compile(rf"NB{token}B\n")
        end = re.compile(rf"NB{token}E (\d+)\n")
        self._buf = ""
        framed = f"{{ {command}; }} 2>&1"
        self._send(f"printf 'NB%sB\\n' {token}; {framed}; printf 'NB%sE %s\\n' {token} $?\r")
        start = self._read_until(begin, timeout or self.timeout)
        self._consume(start)
        finish = self._read_until(end, timeout or self.timeout)
        output = self._buf[: finish.start()]
        self._consume(finish)
        return int(finish.group(1)), output

    def upload(self, data: bytes, dest: str) -> None:
        """Write bytes to a file in the guest, in chunks each acknowledged before the next."""
        encoded = base64.b64encode(data).decode()
        self.run(f"umask 077; : > {dest}.b64")
        for i in range(0, len(encoded), _CHUNK):
            self.run(f"printf '%s' '{encoded[i : i + _CHUNK]}' >> {dest}.b64")
        self.run(f"base64 -d < {dest}.b64 > {dest} && rm -f {dest}.b64")
