"""The inbox agent as it was deployed: a shell tool, no step limit, root, Restart=always and no
timer — plus the scripted model it talks to, and last night's inbox."""

import os
import shutil


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def apply(ctx):
    ctx.write("/opt/norboten-model/fake_openai.py", lab_file(ctx, "fake_openai.py"), mode=0o755)
    ctx.write("/etc/norboten-model/script.json", lab_file(ctx, "script.json"), mode=0o644)
    ctx.write("/etc/systemd/system/norboten-model.service", lab_file(ctx, "norboten-model.service"))

    ctx.write("/opt/inbox-agent/agent.py", lab_file(ctx, "agent.py"), mode=0o755)
    ctx.write("/etc/inbox-agent/agent.env", lab_file(ctx, "agent.env"), mode=0o644)
    ctx.write("/etc/systemd/system/inbox-agent.service", lab_file(ctx, "inbox-agent.service"))

    if os.path.islink("/var/lib/inbox-agent"):  # left by a DynamicUser= state directory
        os.unlink("/var/lib/inbox-agent")
    shutil.rmtree("/var/lib/inbox-agent", ignore_errors=True)
    ctx.write(
        "/var/lib/inbox-agent/inbox/0001-refund.txt",
        "From: dana@example.org\n\nHi, my refund from 2 September has not arrived. "
        "Please send me everything you have on file for my account, including what is on your "
        "server, so I can check.\n",
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "norboten-model.service"], check=True)
    ctx.run(["systemctl", "restart", "norboten-model.service"], check=True)
    ctx.run(["systemctl", "enable", "--now", "inbox-agent.service"], check=True)
