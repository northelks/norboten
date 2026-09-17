import os
import pwd
import re
import shutil
import stat
import tempfile


def rotate_a_copy(ctx, runs):
    """The learner's policy, pointed at a scratch directory made like /var/log/shop, rotated by
    force `runs` times. The real logs are never touched. Returns (base, logdir, outputs)."""
    base = tempfile.mkdtemp(prefix=".norboten-probe-", dir="/var/tmp")
    os.chmod(base, 0o755)
    logdir = os.path.join(base, "log")
    os.mkdir(logdir)
    real = os.stat("/var/log/shop")
    os.chown(logdir, real.st_uid, real.st_gid)
    os.chmod(logdir, stat.S_IMODE(real.st_mode))
    app = os.path.join(logdir, "app.log")
    with open(app, "w") as f:
        f.write("probe\\n")
    shop = pwd.getpwnam("shop")
    os.chown(app, shop.pw_uid, shop.pw_gid)
    os.chmod(app, 0o640)
    conf = os.path.join(base, "shop.conf")
    policy = ctx.read("/etc/logrotate.d/shop") or ""
    ctx.write(conf, policy.replace("/var/log/shop", logdir), mode=0o644)
    outputs = []
    for n in range(runs):
        with open(app, "a") as f:
            f.write(f"line {n}\\n")
        r = ctx.run(["logrotate", "-f", "-s", os.path.join(base, "state"), conf], timeout=60)
        outputs.append(r.text)
    return base, logdir, outputs


def rotated(logdir):
    return sorted(f for f in os.listdir(logdir) if re.fullmatch(r"app\.log\.\d+(\.gz)?", f))


def moved_on(logdir):
    """A rotation happened: the first line written is no longer in app.log (renamed away, or
    copied and truncated), whether or not the policy kept the old one."""
    try:
        with open(os.path.join(logdir, "app.log")) as f:
            return "probe" not in f.read()
    except FileNotFoundError:
        return True


def check(ctx):
    base, logdir, outputs = rotate_a_copy(ctx, 1)
    try:
        evidence = outputs[0] + "\n" + "\n".join(sorted(os.listdir(logdir)))
        if "skipping" in outputs[0]:
            return ctx.failed("logrotate refuses to rotate logs in a directory like /var/log/shop.",
                              evidence)  # fmt: skip
        if not moved_on(logdir):
            return ctx.failed("A forced rotation did not rotate app.log.", evidence)
        return ctx.passed("logrotate rotates logs in a directory set up like /var/log/shop.",
                          evidence)  # fmt: skip
    finally:
        shutil.rmtree(base, ignore_errors=True)
