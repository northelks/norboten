"""The gateway as security found it: key in the unit and in a world-readable file, no auth."""

import os
import secrets
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    key = ctx.state.get("upstream_key") or "sk-norboten-" + secrets.token_hex(16)
    client = ctx.state.get("client_token") or secrets.token_urlsafe(24)
    ctx.state["upstream_key"] = key
    ctx.state["client_token"] = client

    for user in ("chatgw",):
        if not ctx.run(["id", user]).ok:
            ctx.run(
                ["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user],
                check=True,
            )
    os.makedirs("/opt/chat-gateway", exist_ok=True)
    if not os.path.exists("/opt/chat-gateway/.venv/bin/python"):
        ctx.run(["python3", "-m", "venv", "/opt/chat-gateway/.venv"], check=True, timeout=110)
    shutil.copy(os.path.join(files, "chat-gateway"), "/opt/chat-gateway/gateway.py")
    os.chmod("/opt/chat-gateway/gateway.py", 0o755)
    shutil.copy(os.path.join(files, "model-api"), "/usr/local/bin/model-api")
    os.chmod("/usr/local/bin/model-api", 0o755)

    ctx.write("/etc/model-api/key", key + "\n", mode=0o600)
    ctx.write("/etc/chat-gateway/upstream.key", key + "\n", mode=0o644)  # world-readable
    ctx.write("/etc/chat-gateway/clients.token", client + "\n", mode=0o640, group="chatgw")
    ctx.write(
        "/etc/chat-gateway/gateway.env",
        "REQUIRE_TOKEN=0\nLOG_HEADERS=1\nUPSTREAM_KEY_FILE=/etc/chat-gateway/upstream.key\n",
        mode=0o644,
    )
    unit = ctx.read(os.path.join(files, "chat-gateway.service"))
    ctx.write("/etc/systemd/system/chat-gateway.service", unit.replace("REPLACED_BY_BREAK", key))
    shutil.copy(os.path.join(files, "model-api.service"), "/etc/systemd/system/model-api.service")
    shutil.copy(os.path.join(files, "chat-proxy.conf"), "/etc/nginx/conf.d/chat-proxy.conf")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "model-api"], check=True)
    ctx.run(["systemctl", "enable", "--now", "chat-gateway"], check=True)
    ctx.run(["systemctl", "enable", "--now", "nginx"], check=True)
    ctx.run(["systemctl", "reload", "nginx"])
