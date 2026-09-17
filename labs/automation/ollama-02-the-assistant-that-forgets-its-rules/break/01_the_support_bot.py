"""Ollama with a support-bot model built from a Modelfile whose context window is too small for
its own system prompt and whose temperature is high, and a chat backend that shrinks it again."""

import os
import secrets
import shutil
import time
import urllib.request


def rules(revision):
    lines = [f"You are the support assistant of Norboten Billing (policy revision {revision})."]
    topics = ("refund dates", "invoice corrections", "card data", "account deletion", "discounts")
    for n in range(1, 40):
        topic = topics[n % len(topics)]
        lines.append(
            f"Rule {n}: on {topic}, never promise a date or an outcome; say the billing team "
            "will reply within two working days, and ask for the invoice number."
        )
    return "\n".join(lines)


def modelfile(revision, num_ctx, temperature):
    return (
        "FROM qwen2.5:0.5b\n"
        f"PARAMETER num_ctx {num_ctx}\n"
        f"PARAMETER temperature {temperature}\n"
        f'SYSTEM """{rules(revision)}\n"""\n'
    )


def wait_for_ollama():
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2).close()
            return
        except OSError:
            time.sleep(1)


def apply(ctx):
    revision = ctx.state.get("revision") or secrets.token_hex(3)
    ctx.state["revision"] = revision
    ctx.save_state()

    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "ollama.service"), "/etc/systemd/system/ollama.service"
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "ollama"], check=True)
    wait_for_ollama()

    ctx.write("/srv/support-bot/Modelfile", modelfile(revision, 256, 1.2), mode=0o644)
    ctx.run(
        ["ollama", "create", "support-bot", "-f", "/srv/support-bot/Modelfile"],
        check=True,
        timeout=120,
    )
    # last week's "fix": the context raised in the file, and the model never rebuilt
    ctx.write("/srv/support-bot/Modelfile", modelfile(revision, 2048, 1.2), mode=0o644)
    with open(os.path.join(ctx.lab_dir, "files", "ask")) as f:
        ctx.write("/opt/support-chat/ask", f.read(), mode=0o755)
