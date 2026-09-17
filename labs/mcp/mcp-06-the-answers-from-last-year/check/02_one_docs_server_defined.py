import json

HOME = "/home/learner"
REPO = f"{HOME}/handbook-bot"


def check(ctx):
    try:
        config = json.loads(ctx.read(f"{HOME}/.claude.json") or "{}")
    except ValueError:
        return ctx.failed("~/.claude.json is not valid JSON; Claude Code cannot read it.")
    local = (config.get("projects", {}).get(REPO, {}) or {}).get("mcpServers", {})
    user = config.get("mcpServers", {}) or {}
    others = [
        f"{scope}: {json.dumps(defs['docs'])[:160]}"
        for scope, defs in (("local", local), ("user", user))
        if "docs" in defs
    ]
    evidence = "\n".join(others) or "only .mcp.json defines docs"
    if others:
        return ctx.failed(
            "Another `docs` server is defined outside the repository, and wins over .mcp.json "
            "for this project.",
            evidence,
        )
    return ctx.passed("The repository's .mcp.json is the only place `docs` is defined.", evidence)
