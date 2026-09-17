import json
import socket
import time

REQUEST = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
           "params": {"name": "build_report", "arguments": {}}}  # fmt: skip


def check(ctx):
    ctx.run(["/usr/local/bin/reports-mcp", "restart"])
    ctx.run(["/usr/local/bin/proxy-restart"])
    body = json.dumps(REQUEST).encode()
    head = (
        "POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:8080\r\nContent-Type: application/json\r\n"
        "Accept: application/json, text/event-stream\r\nConnection: close\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode()
    started = time.monotonic()
    first_event = None
    received = b""
    try:
        with socket.create_connection(("127.0.0.1", 8080), timeout=30) as s:
            s.sendall(head + body)
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                received += chunk
                if first_event is None and b"notifications/progress" in received:
                    first_event = time.monotonic() - started
    except OSError as e:
        return ctx.failed(f"Could not talk to the proxy on :8080: {e}.")
    total = time.monotonic() - started
    status = received.split(b"\r\n", 1)[0].decode(errors="replace")
    evidence = (
        f"{status}\nfirst progress event after: "
        f"{'never' if first_event is None else f'{first_event:.1f}s'}; "
        f"stream ended after {total:.1f}s\n" + received.decode(errors="replace")[-400:]
    )
    if " 200 " not in status + " ":
        return ctx.failed(f"Through the proxy, build_report answered {status!r}.", evidence)
    if b'"result"' not in received:
        return ctx.failed("The stream ended before the report arrived.", evidence)
    if first_event is None or first_event > 1.5:
        return ctx.failed(
            "The first progress event reached the client only when the report was done: "
            "the proxy holds the stream back.",
            evidence,
        )
    return ctx.passed(
        f"Progress arrived after {first_event:.1f}s and the report after {total:.1f}s.", evidence
    )
