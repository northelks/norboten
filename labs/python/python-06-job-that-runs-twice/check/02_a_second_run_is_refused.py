import os
import shutil
import tempfile
import time
from importlib.machinery import SourceFileLoader


def probe(ctx):
    path = os.path.join(ctx.lab_dir, "files", "probe.py")
    return SourceFileLoader("pricing_probe", path).load_module()


def check(ctx):
    p = probe(ctx)
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    first = None
    try:
        out, env = p.prepare(ctx, base, seconds="1.0")
        before = ctx.read(out)
        first = p.start(env)
        time.sleep(1.2)  # the first run is in the middle of its products
        started = time.monotonic()
        code, stdout, stderr = p.run(env, timeout=20)
        took = time.monotonic() - started
        during = ctx.read(out)
        evidence = (
            f"second run while the first was working\nexit {code} after {took:.1f}s\n"
            f"stdout: {stdout!r}\nstderr: {stderr!r}\n"
            f"prices before: {before!r}\nprices after the second run: {during!r}"
        )
        if code == 0:
            return ctx.failed("A second rebuild ran while the first was still working.", evidence)
        if took > 2:
            return ctx.failed(
                f"The second rebuild waited {took:.0f}s instead of refusing.", evidence
            )
        if not stderr.strip():
            return ctx.failed("The refused rebuild says nothing on standard error.", evidence)
        return ctx.passed(f"A second rebuild is refused in {took:.1f}s, with a message.", evidence)
    finally:
        if first is not None:
            p.kill(first)
        shutil.rmtree(base, ignore_errors=True)
