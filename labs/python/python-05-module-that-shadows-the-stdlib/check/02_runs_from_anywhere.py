import os
import shutil
import tempfile
from importlib.machinery import SourceFileLoader


def _first(ctx):
    path = os.path.join(ctx.lab_dir, "check", "01_runs_from_its_own_directory.py")
    return SourceFileLoader("digest_first_check", path).load_module()


def check(ctx):
    first = _first(ctx)
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        r, line = first.run(ctx, "/", base)
        want = first.expected_line(len(first.EVENTS))
        evidence = f"cwd /\nexit {r.code}\n{r.text}\ndigest: {line!r}\nexpected: {want!r}"
        if r.code != 0:
            return ctx.failed("Started outside its own directory, the digest fails.", evidence)
        if line != want:
            return ctx.failed("From another directory the digest line is different.", evidence)
        return ctx.passed("The digest is the same from any directory.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
