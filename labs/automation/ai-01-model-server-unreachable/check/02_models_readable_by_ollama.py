import grp
import os
import pwd
import stat


def check(ctx):
    models = ctx.run(["systemctl", "show", "-p", "Environment", "--value", "ollama"]).out
    path = "/srv/models"
    for part in models.split():
        if part.startswith("OLLAMA_MODELS="):
            path = part.split("=", 1)[1]
    try:
        st = os.stat(path)
    except OSError:
        return ctx.failed(f"The model directory {path} does not exist.")
    owner = pwd.getpwuid(st.st_uid).pw_name
    group = grp.getgrgid(st.st_gid).gr_name
    mode = stat.S_IMODE(st.st_mode)
    evidence = f"{path}: owner {owner}:{group}, mode {mode:04o}"
    if owner != "ollama":
        return ctx.failed("The model directory does not belong to the ollama account.", evidence)
    if mode & 0o002:
        return ctx.failed("The model directory is world-writable.", evidence)
    listing = ctx.run(
        f"sudo -u ollama env HOME=/var/lib/ollama OLLAMA_MODELS={path} "
        "OLLAMA_HOST=127.0.0.1:11434 /usr/local/bin/ollama list",
        timeout=60,
    )
    if "qwen2.5:0.5b" not in listing.out:
        return ctx.failed("The ollama account cannot see the model.", f"{evidence}\n{listing.text}")
    return ctx.passed("The ollama account owns and can read its models.", evidence)
