import glob
import re


def _site_with_8080(ctx):
    for path in sorted(glob.glob("/etc/nginx/conf.d/*.conf")) + sorted(
        glob.glob("/etc/nginx/sites-enabled/*")
    ):
        text = ctx.read(path) or ""
        if re.search(r"listen\s+8080\b", text):
            return path, text
    return None, ""


def check(ctx):
    path, text = _site_with_8080(ctx)
    if path is None:
        return ctx.failed("No nginx site listens on 8080.")
    body = re.sub(r"#.*", "", text)
    if not re.search(r"proxy_buffering\s+off", body):
        return ctx.failed(
            "The proxy still buffers responses, so streamed answers arrive late.",
            f"{path}:\n{text[:800]}",
        )
    m = re.search(r"proxy_read_timeout\s+(\d+)(s|m)?", body)
    seconds = int(m.group(1)) * (60 if m and m.group(2) == "m" else 1) if m else 0
    if seconds < 300:
        return ctx.failed(
            "A long generation would be cut off: the proxy read timeout is too short.",
            f"{path}: proxy_read_timeout {m.group(0) if m else '(unset, default 60s)'}",
        )
    return ctx.passed("The proxy passes streamed answers straight through.", f"{path}")
