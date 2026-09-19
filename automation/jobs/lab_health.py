"""After the weekly gate: an issue for every lab × image that stopped solving. No model.

`lab-validate.yml` runs every lab on every image on a schedule; this runs as its last job and reads
the run's own jobs back. Gate jobs are named `gate (<lab>, <image>)` by the matrix. A cancelled or
skipped job is not a verdict, and a lab that already has an open issue gets no second one. When more
than half the gates failed, the gate itself is what broke (a workflow step, the runner, an image),
not the labs: that is one issue, not one per lab.

    python3 -m automation.jobs.lab_health      # the `report` job of lab-validate.yml
"""

from __future__ import annotations

import re

from automation.jobs.common import GitHub, env, notice

GATE = re.compile(r"^gate \((?P<lab>[^,]+), (?P<image>[^)]+)\)$")
BROKEN_GATE = "the solvability gate is broken"


def judged_gates(gh: GitHub, run_id: str) -> list[dict]:
    """Every gate job of the run that passed or failed; cancelled and skipped ones are left out."""
    judged, page = [], 1
    while True:
        jobs = gh.call(
            "GET", f"/repos/{{repo}}/actions/runs/{run_id}/jobs", per_page=100, page=page
        ).get("jobs", [])
        for job in jobs:
            m = GATE.match(job["name"])
            if m and job.get("conclusion") in ("success", "failure"):
                judged.append(
                    {
                        **m.groupdict(),
                        "failed": job["conclusion"] == "failure",
                        "url": job.get("html_url", ""),
                    }
                )
        if len(jobs) < 100:
            return judged
        page += 1


def main() -> None:
    gh = GitHub()
    judged = judged_gates(gh, env("GITHUB_RUN_ID"))
    failed = [g for g in judged if g["failed"]]
    if not failed:
        notice("every lab still solves")
        return
    if len(failed) * 2 > len(judged):
        if gh.open_issue_titled(BROKEN_GATE):
            notice(f"already open: {BROKEN_GATE}")
            return
        jobs = "\n".join(f"- {f['lab']} on {f['image']}: {f['url']}" for f in failed)
        body = (
            f"{len(failed)} of {len(judged)} gate jobs failed in the weekly run: more likely the "
            f"workflow, the runner or an image than the labs. No issue was opened per lab.\n\n"
            f"{jobs}"
        )
        issue = gh.create_issue(BROKEN_GATE, body, ["bug"])
        notice(f"opened #{issue['number']}: {BROKEN_GATE}")
        return
    for f in failed:
        title = f"lab {f['lab']} no longer solves on {f['image']}"
        if gh.open_issue_titled(title):
            notice(f"already open: {title}")
            continue
        body = (
            f"The weekly solvability gate failed: the reference solution no longer solves "
            f"{f['lab']} on {f['image']}.\n\nThe job, with the console and journal of the failed "
            f"VM: {f['url']}"
        )
        issue = gh.create_issue(title, body, ["broken-lab"])
        notice(f"opened #{issue['number']}: {title}")


if __name__ == "__main__":
    main()
