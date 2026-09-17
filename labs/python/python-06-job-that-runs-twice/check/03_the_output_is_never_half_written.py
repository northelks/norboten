import json
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
    proc = None
    try:
        out, env = p.prepare(ctx, base, seconds="0.6")
        skus = sorted(item["sku"] for item in p.CATALOGUE)
        first = p.run(env, timeout=40)  # one good run, so the file holds a full list
        if first[0] != 0:
            return ctx.failed("A single rebuild does not succeed.", f"{first}")
        proc = p.start(env)  # a second rebuild, watched while it works
        seen, bad = 0, None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and proc.poll() is None:
            text = ctx.read(out)
            seen += 1
            try:
                prices = json.loads(text or "")
            except ValueError:
                bad = f"not JSON: {text!r}"
                break
            if sorted(prices) != skus:
                bad = f"missing products: {sorted(prices)}"
                break
            time.sleep(0.1)
        p.kill(proc)
        evidence = f"{seen} reads while a rebuild was running\n{bad or 'every read was complete'}"
        if bad:
            return ctx.failed("A reader saw the price list half written.", evidence)
        if seen < 3:
            return ctx.failed("The price list could not be read while a rebuild ran.", evidence)
        return ctx.passed("Every read during a rebuild saw a complete price list.", evidence)
    finally:
        if proc is not None:
            p.kill(proc)
        shutil.rmtree(base, ignore_errors=True)
