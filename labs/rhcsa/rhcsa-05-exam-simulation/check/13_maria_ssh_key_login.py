def check(ctx):
    r = ctx.run(
        [
            "su",
            "-",
            "maria",
            "-c",
            "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
            "-o ConnectTimeout=5 maria@localhost true",
        ],
        timeout=20,
    )
    if not r.ok:
        return ctx.failed("maria cannot ssh to localhost with a key.", r.text[-1500:])
    return ctx.passed("maria logs in to localhost with her key.")
