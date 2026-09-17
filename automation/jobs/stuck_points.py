"""Weekly: where learners get stuck, summarised for the maintainer, the worst as a hints issue.

The ranking is the API's (`GET /telemetry/stuck-points`), counted, not guessed. Claude only turns
the top five into a few sentences for Discord; the issue title and the numbers come from the data.

    python3 -m automation.jobs.stuck_points    # .github/workflows/stuck-points.yml, Mondays
"""

from __future__ import annotations

import json

from automation.jobs.common import GitHub, claude, env, http, notice, post_discord

PROMPT = """On stdin is a JSON list of the checks Norboten learners failed most, most-failed \
first: the lab, the check, and how many failed attempts were reported. Write at most five \
sentences for the maintainer: which checks people fail most, and what that suggests about the \
hints for those checks. Use only the numbers given. Plain text, no headings."""


ASK = "Summarise the stuck points on stdin."


def main() -> None:
    api = env("NORBOTEN_API", "https://api.norboten.org").rstrip("/")
    ranked = [r for r in http("GET", f"{api}/telemetry/stuck-points") or [] if r.get("check_id")]
    if not ranked:
        notice("no stuck points reported: nothing to say")
        return
    top, worst = ranked[:5], ranked[0]

    text = claude(ASK, system=PROMPT, stdin=json.dumps(top, indent=1))["result"].strip()
    post_discord(f"**Where learners got stuck**\n{text}")

    gh = GitHub()
    title = f"hints: {worst['check_id']} in {worst['lab_id']}"
    if gh.open_issue_titled(title):
        notice(f"already open: {title}")
        return
    body = (
        f"This check has the most failed attempts reported ({worst['failures']}). The question is "
        "whether its hints lead anywhere, not whether the check is too strict.\n\n"
        f"This week's summary (Claude, from the ranking below):\n\n{text}\n\n"
        "| lab | check | failed attempts |\n|---|---|---|\n"
        + "\n".join(f"| {r['lab_id']} | {r['check_id']} | {r['failures']} |" for r in top)
    )
    issue = gh.create_issue(title, body, ["hints"])
    notice(f"opened #{issue['number']}: {title}")


if __name__ == "__main__":
    main()
