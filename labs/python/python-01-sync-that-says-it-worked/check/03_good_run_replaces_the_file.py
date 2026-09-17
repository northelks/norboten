import json
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

RECORDS = [{"host": f"probe{i}"} for i in range(4)]


class Good(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(RECORDS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    server = HTTPServer(("127.0.0.1", 0), Good)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        output = os.path.join(base, "records.json")
        ctx.write(output, "[]\n", mode=0o644)
        before = os.stat(output).st_ino
        env = {"SYNC_API": f"http://127.0.0.1:{server.server_port}/records", "SYNC_OUTPUT": output}
        r = ctx.run(["python3", "/opt/sync/sync.py"], env=env, timeout=25)
        text = ctx.read(output) or ""
        leftovers = sorted(set(os.listdir(base)) - {"records.json"})
        evidence = f"exit {r.code}\n{r.text}\noutput: {text[:300]!r}\nother files: {leftovers}"
        if r.code != 0:
            return ctx.failed("A good run did not exit 0.", evidence)
        try:
            data = json.loads(text)
        except ValueError:
            return ctx.failed("A good run did not leave valid JSON.", evidence)
        if data != RECORDS:
            return ctx.failed("A good run did not write the API's records.", evidence)
        if os.stat(output).st_ino == before:
            return ctx.failed(
                "The records were rewritten in place: a reader can see a half-written file.",
                evidence,
            )
        if leftovers:
            return ctx.failed("A good run left temporary files beside the output.", evidence)
        if os.stat(output).st_mode & 0o044 != 0o044:
            return ctx.failed("The new file is not readable by the services that use it.", evidence)
        return ctx.passed("A good run replaces the records in one step.", evidence)
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(base, ignore_errors=True)
