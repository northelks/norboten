"""Start a rebuild the way the timer does — shared by this lab's checks."""

import contextlib
import json
import os
import subprocess

CATALOGUE = [
    {"sku": "BOLT-M6", "cost": 0.40},
    {"sku": "NUT-M6", "cost": 0.25},
    {"sku": "WASHER-6", "cost": 0.10},
    {"sku": "SPANNER-13", "cost": 6.50},
]


def prepare(ctx, base, seconds="0.4"):
    """A catalogue, an empty price list and the environment a run needs."""
    catalogue = os.path.join(base, "catalogue.json")
    out = os.path.join(base, "prices.json")
    with open(catalogue, "w", encoding="utf-8") as f:
        json.dump(CATALOGUE, f)
    with open(out, "w", encoding="utf-8") as f:
        f.write("{}\n")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "PRICING_CATALOGUE": catalogue,
        "PRICING_OUT": out,
        "PRICING_LOCK": os.path.join(base, "rebuild.lock"),
        "PRICING_SECONDS_PER_PRODUCT": seconds,
    }
    return out, env


def start(env):
    return subprocess.Popen(
        ["python3", "/opt/pricing/rebuild.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def run(env, timeout=60):
    proc = start(env)
    out, err = proc.communicate(timeout=timeout)
    return proc.returncode, out, err


def kill(proc):
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)
