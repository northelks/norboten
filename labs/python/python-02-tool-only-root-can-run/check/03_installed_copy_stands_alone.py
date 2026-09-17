import glob

VENV = "/opt/netprobe/venv"
CODE = "import netprobe, netprobe.cli, yaml; print(netprobe.__file__)"


def check(ctx):
    r = ctx.run([f"{VENV}/bin/python", "-I", "-c", CODE], user=ctx.learner, timeout=20)
    site = glob.glob(f"{VENV}/lib/python3*/site-packages")
    editable = [
        p for s in site for p in glob.glob(f"{s}/__editable__*") + glob.glob(f"{s}/*netprobe*.pth")
    ]
    evidence = f"netprobe imported from: {r.text}\neditable hooks: {editable}"
    if r.code != 0:
        return ctx.failed(f"The venv's Python cannot import netprobe as {ctx.learner}.", evidence)
    location = r.out.strip()
    if not location.startswith(f"{VENV}/lib/"):
        return ctx.failed(f"The venv loads netprobe from {location}, outside the venv.", evidence)
    if editable:
        return ctx.failed("The venv still carries an editable install hook.", evidence)
    return ctx.passed("netprobe is installed as a real copy inside the venv.", evidence)
