import os
import shutil
import socket
import tempfile
import time

GOOD = '[{"host": "keep-me"}]\n'


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    # accepts connections (the kernel does the handshake) and never answers a request
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(8)
    try:
        output = os.path.join(base, "records.json")
        ctx.write(output, GOOD)
        env = {
            "SYNC_API": f"http://127.0.0.1:{silent.getsockname()[1]}/records",
            "SYNC_OUTPUT": output,
        }
        start = time.monotonic()
        r = ctx.run(["python3", "/opt/sync/sync.py"], env=env, timeout=22)
        took = time.monotonic() - start
        evidence = f"API never answered\nexit {r.code} after {took:.1f}s\n{r.text}"
        if r.code == 124:
            return ctx.failed(
                "Against an API that never answers, the script is still waiting.", evidence
            )
        if took > 15:
            return ctx.failed(f"The script gave up only after {took:.0f} seconds.", evidence)
        if r.code == 0:
            return ctx.failed("A stalled API is reported as success (exit 0).", evidence)
        if ctx.read(output) != GOOD:
            return ctx.failed("A stalled API replaced the existing records.", evidence)
        return ctx.passed(f"A stalled API fails the run after {took:.0f} seconds.", evidence)
    finally:
        silent.close()
        shutil.rmtree(base, ignore_errors=True)
