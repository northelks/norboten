TEAM = ("alice", "bob", "carol")

OUTSIDER = "dave"


def check(ctx):
    groups = {u: ctx.run(["id", "-nG", u]).out.split() for u in (*TEAM, OUTSIDER)}
    evidence = "\n".join(f"{u}: {' '.join(g)}" for u, g in groups.items())
    missing = [u for u in TEAM if "reports" not in groups[u]]
    if missing:
        return ctx.failed(f"Not in the group reports: {', '.join(missing)}.", evidence)
    if "reports" in groups[OUTSIDER]:
        return ctx.failed("dave is in reports, and he is not on the team.", evidence)
    return ctx.passed("alice, bob and carol are in reports; dave is not.", evidence)
