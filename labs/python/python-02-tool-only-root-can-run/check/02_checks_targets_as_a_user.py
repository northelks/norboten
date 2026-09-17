import json


def check(ctx):
    r = ctx.run(
        "PATH=/usr/local/bin:/usr/bin:/bin; netprobe check --config /etc/netprobe/targets.yaml",
        user=ctx.learner,
        timeout=25,
    )
    evidence = f"as {ctx.learner}\nexit {r.code}\n{r.text}"
    if r.code != 0:
        return ctx.failed(f"netprobe check fails for {ctx.learner}.", evidence)
    try:
        results = {item["target"]: item["open"] for item in json.loads(r.out)}
    except (ValueError, KeyError, TypeError):
        return ctx.failed("netprobe check did not print its JSON report.", evidence)
    if results.get("127.0.0.1:22") is not True:
        return ctx.failed("netprobe check did not find 127.0.0.1:22 open.", evidence)
    return ctx.passed(f"netprobe check works for {ctx.learner}.", evidence)
