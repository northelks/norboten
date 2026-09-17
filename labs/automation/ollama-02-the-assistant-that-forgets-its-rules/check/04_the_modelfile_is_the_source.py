import json
import re
import urllib.request

MODELFILE = "/srv/support-bot/Modelfile"


def file_parameters(text):
    return {
        m.group(1): m.group(2).strip('"')
        for m in re.finditer(r"^PARAMETER\s+(\S+)\s+(.+?)\s*$", text, re.M)
    }


def check(ctx):
    text = ctx.read(MODELFILE)
    if text is None:
        return ctx.failed(f"{MODELFILE} is missing.")
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/show",
        data=json.dumps({"model": "support-bot"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            shown = json.load(response)
    except OSError as e:
        return ctx.failed("Ollama does not know a model called support-bot.", str(e))
    server = {}
    for line in (shown.get("parameters") or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            server[parts[0]] = parts[-1].strip('"')
    in_file = file_parameters(text)
    evidence = f"Modelfile: {in_file}\nserver:    {server}"
    for key in ("num_ctx", "temperature"):
        if (
            key in server
            and in_file.get(key) is not None
            and float(in_file[key]) != float(server[key])
        ):
            return ctx.failed(
                f"The Modelfile says {key} {in_file[key]}; the server holds {server[key]}.",
                evidence,
            )
        if (key in server) != (key in in_file):
            return ctx.failed(
                f"{key} is set in {'the server' if key in server else 'the Modelfile'} only.",
                evidence,
            )
    revision = ctx.state.get("revision")
    if f"policy revision {revision}" not in text:
        return ctx.failed("The Modelfile no longer carries the team's rules.", evidence)
    if (shown.get("system") or "").strip() not in text:
        return ctx.failed("The system prompt on the server differs from the Modelfile's.", evidence)
    return ctx.passed("The Modelfile and the server agree.", evidence)
