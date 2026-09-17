import re

SCRIPT = "/usr/local/bin/top-talkers"


def check(ctx):
    text = ctx.read(SCRIPT)
    if text is None:
        return ctx.failed(f"{SCRIPT} does not exist.")
    first = text.splitlines()[0] if text else ""
    if not re.match(r"^#!\s*(/usr)?/bin/(env\s+)?bash\b", first):
        return ctx.failed("The script is not a Bash script.", first)
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    other = re.findall(r"\b(python3?|perl|ruby|php|node)\b", body)
    if other:
        return ctx.failed(f"The script calls {other[0]}; the task is Bash only.")
    return ctx.passed("Bash and the standard tools only.")
