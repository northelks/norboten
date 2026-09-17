"""Attach the user's terminal to a guest serial console.

This is how a learner reaches a machine with no network: emergency mode, a failed boot, or the
bootloader during root password recovery. Ctrl-] detaches.
"""

from __future__ import annotations

import os
import select
import socket
import sys
from pathlib import Path

ESCAPE = b"\x1d"  # Ctrl-]


def attach(sock_path: Path, *, banner: str = "") -> None:
    import termios
    import tty

    if not sock_path.exists():
        raise FileNotFoundError(f"{sock_path} does not exist — is the VM running?")
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(str(sock_path))
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    if banner:
        sys.stdout.write(banner + "\r\n")
        sys.stdout.flush()
    try:
        tty.setraw(fd)
        conn.sendall(b"\r")  # wake the getty so a prompt appears
        while True:
            ready, _, _ = select.select([conn, fd], [], [])
            if conn in ready:
                data = conn.recv(4096)
                if not data:
                    break
                os.write(sys.stdout.fileno(), data)
            if fd in ready:
                data = os.read(fd, 1024)
                if ESCAPE in data:
                    before = data.split(ESCAPE, 1)[0]
                    if before:
                        conn.sendall(before)
                    break
                conn.sendall(data)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        conn.close()
        sys.stdout.write("\r\n[detached from console]\r\n")
        sys.stdout.flush()
