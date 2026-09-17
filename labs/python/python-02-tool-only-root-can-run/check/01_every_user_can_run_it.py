def check(ctx):
    r = ctx.run(
        "PATH=/usr/local/bin:/usr/bin:/bin; command -v netprobe && netprobe --version",
        user=ctx.learner,
        timeout=20,
    )
    evidence = f"as {ctx.learner}, PATH=/usr/local/bin:/usr/bin:/bin\nexit {r.code}\n{r.text}"
    if r.code == 127 or not r.out.strip():
        return ctx.failed(f"{ctx.learner} cannot find netprobe on the normal PATH.", evidence)
    if r.code != 0:
        return ctx.failed(f"netprobe --version fails for {ctx.learner}.", evidence)
    if "netprobe 1.4.0" not in r.text:
        return ctx.failed("netprobe runs but does not report version 1.4.0.", evidence)
    return ctx.passed(f"{ctx.learner} can run netprobe.", evidence)
