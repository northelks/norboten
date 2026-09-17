"""A few QEMU monitor (QMP) commands, over the socket Lima creates for each instance."""

from __future__ import annotations

import json
import socket
from pathlib import Path


class QmpError(RuntimeError):
    pass


def command(sock_path: Path, name: str, arguments: dict | None = None, timeout: float = 10) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
        f = s.makefile("rw")
        f.readline()  # greeting
        for msg in (
            {"execute": "qmp_capabilities"},
            {"execute": name, "arguments": arguments or {}},
        ):
            f.write(json.dumps(msg) + "\n")
            f.flush()
            while True:
                reply = json.loads(f.readline())
                if "return" in reply or "error" in reply:
                    break
        if "error" in reply:
            raise QmpError(reply["error"].get("desc", str(reply["error"])))
        return reply["return"]
    except OSError as e:
        raise QmpError(f"QMP {name} failed: {e}") from e
    finally:
        s.close()


def hard_reset(sock_path: Path) -> None:
    """Press the reset button: no shutdown, no filesystem sync — like the exam's power control."""
    command(sock_path, "system_reset")
