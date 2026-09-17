import os
import pwd
import stat


def _key_files(ctx):
    key = ctx.state["upstream_key"]
    found = []
    for root, _dirs, files in os.walk("/etc"):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) < 4096 and key in (ctx.read(path) or ""):
                    found.append(path)
            except OSError:
                continue
    return found


def check(ctx):
    files = _key_files(ctx)
    if not files:
        return ctx.failed("The gateway has no key file under /etc any more.")
    problems = []
    for path in files:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        owner = pwd.getpwuid(st.st_uid).pw_name
        if mode & 0o077 or owner not in ("chatgw", "root"):
            problems.append(f"{path}: owner {owner}, mode {mode:04o}")
    if problems:
        return ctx.failed(
            "A file holding the upstream key is readable beyond its own service.",
            "\n".join(problems),
        )
    return ctx.passed("Every file holding the key is private.", "\n".join(files))
