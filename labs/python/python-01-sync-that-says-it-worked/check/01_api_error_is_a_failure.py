import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

GOOD = '[{"host": "keep-me"}]\n'


class Broken(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_error(500, "database unavailable")

    def log_message(self, *args):
        pass


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    server = HTTPServer(("127.0.0.1", 0), Broken)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        output = os.path.join(base, "records.json")
        ctx.write(output, GOOD)
        env = {"SYNC_API": f"http://127.0.0.1:{server.server_port}/records", "SYNC_OUTPUT": output}
        r = ctx.run(["python3", "/opt/sync/sync.py"], env=env, timeout=25)
        after = ctx.read(output)
        evidence = f"API answered 500\nexit {r.code}\n{r.text}\noutput now: {after!r}"
        if after != GOOD:
            return ctx.failed("An API error replaced the existing records.", evidence)
        if r.code == 0:
            return ctx.failed("An API error is reported as success (exit 0).", evidence)
        return ctx.passed("An API error fails the run and keeps the old records.", evidence)
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(base, ignore_errors=True)
