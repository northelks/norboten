import hashlib

REPO = "/home/learner/billing"
ORIGIN = "/srv/git/billing.git"
APPLIED = "migrations/0002_add_due_date.sql"


def check(ctx):
    want = ctx.state.get("applied_sha256")
    if not want:
        return ctx.failed("The lab's applied migration was never recorded; start the lab again.")
    local = ctx.read(f"{REPO}/{APPLIED}") or ""
    remote = ctx.run(["git", "--git-dir", ORIGIN, "show", f"main:{APPLIED}"])
    evidence = (
        f"working tree:\n{local}\norigin main:\n{remote.out if remote.ok else remote.err}\n"
        + ctx.run(["git", "--git-dir", ORIGIN, "log", "--oneline", "-5", "main"]).out
    )
    if hashlib.sha256(local.encode()).hexdigest() != want:
        return ctx.failed(f"{APPLIED} in ~/billing is not what production ran.", evidence)
    if not remote.ok or hashlib.sha256(remote.out.encode()).hexdigest() != want:
        return ctx.failed(f"{APPLIED} on origin's main is not what production ran.", evidence)
    return ctx.passed(f"{APPLIED} matches what production ran, locally and on origin.", evidence)
