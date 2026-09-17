import re

RECAP = re.compile(r"^localhost\s*:\s*(.*)$", re.MULTILINE)


def check(ctx):
    r = ctx.run(
        "cd /srv/ansible && ansible-playbook site.yml --check --diff",
        timeout=28,
        env={"ANSIBLE_NOCOLOR": "1", "LC_ALL": "C.UTF-8"},
    )
    tail = r.text[-3500:]
    m = RECAP.search(r.out)
    if r.code == 124:
        return ctx.failed("ansible-playbook --check did not finish within the time limit.", tail)
    if not m:
        return ctx.failed("ansible-playbook --check did not complete a run.", tail)
    stats = dict(re.findall(r"(\w+)=(\d+)", m.group(1)))
    counts = {k: int(stats.get(k, 0)) for k in ("changed", "skipped", "failed", "ignored")}
    if counts["failed"] or r.code != 0:
        return ctx.failed("The check-mode run fails.", tail)
    if counts["skipped"]:
        return ctx.failed(
            f"{counts['skipped']} task(s) are skipped in check mode, so --check cannot see them.",
            tail,
        )
    if counts["ignored"]:
        return ctx.failed("The check-mode run hides failing tasks with ignore_errors.", tail)
    if counts["changed"]:
        return ctx.failed(
            f"Check mode says {counts['changed']} task(s) would still change something.", tail
        )
    return ctx.passed("Check mode runs every task and finds nothing to change.", tail)
