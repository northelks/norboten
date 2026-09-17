"""The application: answers GET / with its greeting, on the port in /etc/app/app.conf."""

from http.server import BaseHTTPRequestHandler, HTTPServer

settings = {}
with open("/etc/app/app.conf") as f:
    for line in f:
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            settings[key.strip()] = value.strip()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (settings.get("greeting", "") + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(settings["port"])), Handler).serve_forever()
