def check(ctx):
    ls = ctx.run(["ls", "-Zd", "/srv/status", "/srv/status/index.html"]).out
    if "httpd_sys_content_t" not in ls and "httpd_sys_rw_content_t" not in ls:
        return ctx.failed("The site files do not carry a context nginx may read.", ls)
    # restorecon in dry-run mode lists every file whose label differs from the policy's rules:
    # a label set with chcon alone would be listed, and lost at the next relabel.
    pending = ctx.run(["restorecon", "-R", "-n", "-v", "/srv/status"]).out.strip()
    if pending:
        return ctx.failed(
            "The labels are right now but the policy disagrees — a relabel would undo them.",
            pending,
        )
    return ctx.passed("The site's contexts come from the policy itself.", ls)
