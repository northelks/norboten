def check(ctx):
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "10", "ollama"]).text
    if not ctx.service_enabled("ollama"):
        return ctx.failed("The ollama service does not start at boot.", status)
    if not ctx.service_active("ollama"):
        return ctx.failed("The ollama service is not running.", status)
    user = ctx.run(["systemctl", "show", "-p", "User", "--value", "ollama"]).out.strip()
    if user != "ollama":
        return ctx.failed(f"The model server runs as {user or 'root'}.", status)
    return ctx.passed("ollama runs as its own account and starts at boot.")
