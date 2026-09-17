import yaml

WORKFLOW = "/home/learner/site/.github/workflows/claude-triage.yml"


def triggers(document):
    on = document.get("on", document.get(True))  # YAML 1.1 reads a bare `on` as true
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(on)
    return dict(on or {})


def check(ctx):
    text = ctx.read(WORKFLOW)
    if text is None:
        return ctx.failed(f"{WORKFLOW} is missing.")
    try:
        events = triggers(yaml.safe_load(text) or {})
    except yaml.YAMLError as e:
        return ctx.failed("The workflow is not valid YAML.", str(e))
    evidence = f"on: {events}"
    others = sorted(set(events) - {"issues", "workflow_dispatch"})
    if others:
        return ctx.failed(f"The job also starts on: {', '.join(others)}.", evidence)
    if "issues" not in events:
        return ctx.failed("The job no longer starts for new issues at all.", evidence)
    types = (events["issues"] or {}).get("types") if isinstance(events["issues"], dict) else None
    if types != ["opened"]:
        shown = ", ".join(types) if types else "every issue activity"
        return ctx.failed(f"Issue events start the job for: {shown}.", evidence)
    return ctx.passed("Only a newly opened issue starts the job.", evidence)
