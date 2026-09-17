import yaml

WORKFLOW = "/home/learner/site/.github/workflows/claude-triage.yml"
ALLOWED = {"issues": {"write", "read", "none"}, "contents": {"read", "none"}}


def problems_with(permissions):
    if permissions is None:
        return ["no permissions block, so the token gets the repository's default"]
    if isinstance(permissions, str):
        return [f"permissions: {permissions}"]
    found = []
    for scope, level in permissions.items():
        if level == "none":
            continue
        if level not in ALLOWED.get(scope, set()):
            found.append(f"{scope}: {level}")
    return found


def check(ctx):
    try:
        document = yaml.safe_load(ctx.read(WORKFLOW) or "") or {}
    except yaml.YAMLError as e:
        return ctx.failed("The workflow is not valid YAML.", str(e))
    jobs = document.get("jobs") or {}
    if not jobs:
        return ctx.failed("The workflow has no jobs.")
    problems, evidence = [], [f"workflow permissions: {document.get('permissions')}"]
    for name, job in jobs.items():
        effective = job.get("permissions", document.get("permissions"))
        evidence.append(
            f"job {name}: permissions {effective}, timeout-minutes {job.get('timeout-minutes')}"
        )
        problems += [f"job {name}'s token has {p}" for p in problems_with(effective)]
        minutes = job.get("timeout-minutes")
        if not isinstance(minutes, (int, float)) or minutes > 15:
            problems.append(f"job {name} has timeout-minutes {minutes} (GitHub's default is 360)")
    if problems:
        return ctx.failed(problems[0] + ".", "\n".join(evidence))
    return ctx.passed(
        "Issues write and contents read at most, and a timeout of 15 minutes or less.",
        "\n".join(evidence),
    )
