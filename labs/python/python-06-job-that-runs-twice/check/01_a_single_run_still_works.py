import json
import os
import shutil
import tempfile
from importlib.machinery import SourceFileLoader


def probe(ctx):
    path = os.path.join(ctx.lab_dir, "files", "probe.py")
    return SourceFileLoader("pricing_probe", path).load_module()


def check(ctx):
    p = probe(ctx)
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        out, env = p.prepare(ctx, base, seconds="0.05")
        code, stdout, stderr = p.run(env, timeout=40)
        text = ctx.read(out) or ""
        evidence = f"exit {code}\nstdout: {stdout!r}\nstderr: {stderr!r}\nprices: {text!r}"
        if code != 0:
            return ctx.failed("A single rebuild does not succeed.", evidence)
        try:
            prices = json.loads(text)
        except ValueError:
            return ctx.failed("The price list a single run wrote is not valid JSON.", evidence)
        if sorted(prices) != sorted(item["sku"] for item in p.CATALOGUE):
            return ctx.failed("The price list does not hold every product.", evidence)
        return ctx.passed("One rebuild writes the whole price list.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
