import re

import yaml

WORKFLOW = "/home/learner/site/.github/workflows/claude-triage.yml"
EXPANDED = re.compile(r"\$\{\{\s*(secrets\.[A-Za-z0-9_]+|github\.event\.[A-Za-z0-9_.]+)\s*\}\}")


def check(ctx):
    try:
        document = yaml.safe_load(ctx.read(WORKFLOW) or "") or {}
    except yaml.YAMLError as e:
        return ctx.failed("The workflow is not valid YAML.", str(e))
    found, evidence = [], []
    for name, job in (document.get("jobs") or {}).items():
        for n, step in enumerate(job.get("steps") or [], 1):
            script = step.get("run")
            if not isinstance(script, str):
                continue
            label = step.get("name") or f"step {n}"
            for match in EXPANDED.finditer(script):
                found.append(f"{name} / {label}: ${{{{ {match.group(1)} }}}}")
    evidence = "\n".join(found) or "no expressions of secrets or event text inside run scripts"
    if found:
        return ctx.failed(
            f"{len(found)} expression(s) of a secret or of issue text are pasted into a shell "
            f"script, first: {found[0]}.",
            evidence,
        )
    return ctx.passed("Secrets and event fields reach the scripts only through env.", evidence)
