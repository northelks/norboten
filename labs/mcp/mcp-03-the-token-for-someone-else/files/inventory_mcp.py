#!/usr/bin/env python3
"""inventory — the fleet's host list as a remote MCP server: Streamable HTTP, JSON responses.

POST http://127.0.0.1:8931/mcp with `Authorization: Bearer <token>`. The token must be signed by
this machine's identity provider (lab-idp); what else it must be is decided by
/etc/inventory-mcp/config.json:

  issuer      the "iss" a token must carry
  audience    the "aud" a token must carry — this server's own URL. null: any audience at all
  verify_exp  false: a token is accepted after its "exp"

Started and stopped with `sudo inventory-mcp start|stop|restart|status`; it reads its settings
when it starts. Log: /var/log/inventory-mcp.log.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = "/etc/inventory-mcp/config.json"
KEY = "/etc/lab-idp/signing.key"
HOSTS = "/var/lib/inventory/hosts.json"

logging.basicConfig(
    filename="/var/log/inventory-mcp.log", level=logging.INFO, format="%(asctime)s %(message)s"
)
log = logging.getLogger("inventory")


def unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify(token: str, conf: dict, key: bytes) -> tuple[bool, str]:
    try:
        header, payload, signature = token.split(".")
        claims = json.loads(unb64(payload))
    except ValueError:
        return False, "malformed token"
    expected = hmac.new(key, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, unb64(signature)):
        return False, "bad signature"
    if claims.get("iss") != conf.get("issuer"):
        return False, f"issuer {claims.get('iss')!r}"
    audience = conf.get("audience")
    if audience is not None:
        aud = claims.get("aud")
        if aud != audience and not (isinstance(aud, list) and audience in aud):
            return False, f"token is for {aud!r}, not this server"
    if conf.get("verify_exp", True) and claims.get("exp", 0) < time.time():
        return False, "token expired"
    return True, str(claims.get("sub"))


def list_hosts() -> dict:
    with open(HOSTS) as f:
        hosts = json.load(f)
    lines = [f"{h['name']}  {h['role']}  {h['os']}" for h in hosts]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


class Handler(BaseHTTPRequestHandler):
    server_version = "inventory-mcp/1.2"

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: dict | None = None, headers: dict | None = None) -> None:
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(405, {"error": "use POST"}, {"Allow": "POST"})

    do_DELETE = do_GET

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            self._send(404, {"error": "not found"})
            return
        conf = self.server.conf
        scheme, _, token = self.headers.get("Authorization", "").partition(" ")
        ok, who = (
            verify(token.strip(), conf, self.server.key)
            if scheme == "Bearer"
            else (False, "no token")
        )
        if not ok:
            log.info("refused: %s", who)
            self._send(
                401,
                {"error": "invalid_token", "error_description": who},
                {"WWW-Authenticate": f'Bearer error="invalid_token", error_description="{who}"'},
            )
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            message = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, {"error": "not JSON"})
            return
        method, message_id = message.get("method", ""), message.get("id")
        if message_id is None:
            self._send(202)
            return
        params = message.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "inventory", "version": "1.2.0"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "list_hosts",
                        "description": "List the fleet's hosts: name, role, operating system",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        elif method == "tools/call" and params.get("name") == "list_hosts":
            log.info("list_hosts for %s", who)
            result = list_hosts()
        else:
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "error": {"code": -32601, "message": "unknown"},
                },
            )
            return
        self._send(200, {"jsonrpc": "2.0", "id": message_id, "result": result})


def main() -> None:
    with open(CONFIG) as f:
        conf = json.load(f)
    with open(KEY, "rb") as f:
        key = f.read().strip()
    server = ThreadingHTTPServer(
        (conf.get("bind", "127.0.0.1"), int(conf.get("port", 8931))), Handler
    )
    server.conf, server.key = conf, key
    log.info(
        "listening; audience %r, verify_exp %r", conf.get("audience"), conf.get("verify_exp", True)
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
