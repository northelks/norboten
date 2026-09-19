"""After the full gate: an issue for every lab × image that stopped solving. No model.

`lab-validate.yml` runs every lab on every image weekly (or by hand with `all`); this runs as its
last job and reads the run's own jobs back. Gate jobs are named `gate (<lab>, <image>)` by the
matrix. A cancelled or skipped job is not a verdict, and a lab that already has an open issue gets
no second one. When more than half the gates failed, the gate itself is what broke (a workflow step,
the runner, an image), not the labs: that is one issue, not one per lab. An open issue is closed by
the first run in which its gate passed again — or, for the gate itself, did not break.

    python3 -m automation.jobs.lab_health      # the `report` job of lab-validate.yml
"""

from __future__ import annotations

import re

from automation.jobs.common import GitHub, env, notice

GATE = re.compile(r"^gate \((?P<lab>[^,]+), (?P<image>[^)]+)\)$")
LAB_ISSUE = re.compile(r"^lab (?P<lab>\S+) no longer solves on (?P<image>\S+)$")
BROKEN_GATE = "the solvability gate is broken"


def lab_issue_title(lab: str, image: str) -> str:
    return f"lab {lab} no longer solves on {image}"


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


def close_solved(gh: GitHub, judged: list[dict], broken: bool) -> None:
    """Close the open issues this run disproved: labs that solve again, and a gate that works."""
    passed = {(g["lab"], g["image"]): g["url"] for g in judged if not g["failed"]}
    for issue in gh.open_issues():
        title = issue["title"].strip()
        if title.lower() == BROKEN_GATE and not broken:
            failed = sum(g["failed"] for g in judged)
            comment = f"{failed} of {len(judged)} gate jobs failed in the last full run: it works."
        elif (m := LAB_ISSUE.match(title)) and (m["lab"], m["image"]) in passed:
            comment = f"The reference solution solves it again: {passed[m['lab'], m['image']]}"
        else:
            continue
        gh.close_issue(issue["number"], comment)
        notice(f"closed #{issue['number']}: {title}")


def main() -> None:
    gh = GitHub()
    judged = judged_gates(gh, env("GITHUB_RUN_ID"))
    if not judged:
        notice("no gate job passed or failed: nothing to judge")
        return
    failed = [g for g in judged if g["failed"]]
    broken = len(failed) * 2 > len(judged)
    close_solved(gh, judged, broken)
    if not failed:
        notice("every lab still solves")
        return
    if broken:
        if gh.open_issue_titled(BROKEN_GATE):
            notice(f"already open: {BROKEN_GATE}")
            return
        jobs = "\n".join(f"- {f['lab']} on {f['image']}: {f['url']}" for f in failed)
        body = (
            f"{len(failed)} of {len(judged)} gate jobs failed in the full run: more likely the "
            f"workflow, the runner or an image than the labs. No issue was opened per lab.\n\n"
            f"{jobs}"
        )
        issue = gh.create_issue(BROKEN_GATE, body, ["bug"])
        notice(f"opened #{issue['number']}: {BROKEN_GATE}")
        return
    for f in failed:
        title = lab_issue_title(f["lab"], f["image"])
        if gh.open_issue_titled(title):
            notice(f"already open: {title}")
            continue
        body = (
            f"The full solvability gate failed: the reference solution no longer solves "
            f"{f['lab']} on {f['image']}.\n\nThe job, with the console and journal of the failed "
            f"VM: {f['url']}"
        )
        issue = gh.create_issue(title, body, ["broken-lab"])
        notice(f"opened #{issue['number']}: {title}")


if __name__ == "__main__":
    main()
