"""The message exists, owned by root, mode 0600. The secret word is random per session."""

import os
import secrets

WORDS = ["kernel", "inode", "daemon", "socket", "systemd", "journal", "cgroup", "procfs"]


def apply(ctx):
    word = ctx.state.get("secret") or secrets.choice(WORDS)
    ctx.state["secret"] = word
    os.makedirs("/srv/hello", exist_ok=True)
    os.chmod("/srv/hello", 0o755)
    ctx.write(
        "/srv/hello/message.txt",
        "If you can read this, you found your way past a permission check.\n"
        "Every lab here works like that: something is refused, and you find out why.\n"
        f"The secret word is: {word}\n",
        mode=0o600,
    )
