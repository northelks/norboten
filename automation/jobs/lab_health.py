"""After the nightly gate: an issue for every lab × image that stopped solving. No model.

`lab-validate.yml` runs every lab on every image on a schedule; this runs as its last job and reads
the run's own jobs back. Gate jobs are named `gate (<lab>, <image>)` by the matrix. A cancelled or
skipped job is not a verdict, and a lab that already has an open issue gets no second one.

    python3 -m automation.jobs.lab_health      # the `report` job of lab-validate.yml
"""

from __future__ import annotations

import re

from automation.jobs.common import GitHub, env, notice

GATE = re.compile(r"^gate \((?P<lab>[^,]+), (?P<image>[^)]+)\)$")


def failed_gates(gh: GitHub, run_id: str) -> list[dict]:
    failed, page = [], 1
    while True:
        jobs = gh.call(
            "GET", f"/repos/{{repo}}/actions/runs/{run_id}/jobs", per_page=100, page=page
        ).get("jobs", [])
        for job in jobs:
            m = GATE.match(job["name"])
            if m and job.get("conclusion") == "failure":
                failed.append({**m.groupdict(), "url": job.get("html_url", "")})
        if len(jobs) < 100:
            return failed
        page += 1


def main() -> None:
    gh = GitHub()
    failed = failed_gates(gh, env("GITHUB_RUN_ID"))
    if not failed:
        notice("every lab still solves")
        return
    for f in failed:
        title = f"lab {f['lab']} no longer solves on {f['image']}"
        if gh.open_issue_titled(title):
            notice(f"already open: {title}")
            continue
        body = (
            f"The nightly solvability gate failed: the reference solution no longer solves "
            f"{f['lab']} on {f['image']}.\n\nThe job, with the console and journal of the failed "
            f"VM: {f['url']}"
        )
        issue = gh.create_issue(title, body, ["broken-lab"])
        notice(f"opened #{issue['number']}: {title}")


if __name__ == "__main__":
    main()
