#!/usr/bin/env python3
"""files — a folder as an MCP server, over stdio: list_directory, read_file, and write_file.

What it may show is decided by /etc/mcp-files/config.json:

  roots            directories a path must lie in; a relative path is taken from the first
  follow_symlinks  true: a path is checked as written, so a link inside a root may lead anywhere;
                   false: a path is checked where it really leads (os.path.realpath)
  show_hidden      false: a name starting with "." is neither listed nor read
  read_only        true (the default): write_file is not offered at all

Logs go to stderr; stdout carries JSON-RPC and nothing else.
"""

import json
import os
import sys

CONFIG = "/etc/mcp-files/config.json"
MAX_BYTES = 64 * 1024


def log(message):
    print(f"files: {message}", file=sys.stderr, flush=True)


def config():
    with open(CONFIG) as f:
        conf = json.load(f)
    return {
        "roots": [os.path.abspath(os.path.expanduser(r)) for r in conf.get("roots", [])],
        "follow_symlinks": bool(conf.get("follow_symlinks", False)),
        "show_hidden": bool(conf.get("show_hidden", False)),
        "read_only": bool(conf.get("read_only", True)),
    }


class Refused(Exception):
    pass


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def resolve(path, conf):
    if not conf["roots"]:
        raise Refused("no roots are configured")
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(conf["roots"][0], path)
    lexical = os.path.abspath(path)
    if conf["follow_symlinks"]:
        checked, roots = lexical, conf["roots"]
    else:
        checked, roots = os.path.realpath(lexical), [os.path.realpath(r) for r in conf["roots"]]
    if not any(inside(checked, root) for root in roots):
        raise Refused(f"{path} is outside the folders this server shares")
    if not conf["show_hidden"]:
        for root in roots:
            if inside(checked, root):
                rest = os.path.relpath(checked, root)
                if any(
                    part.startswith(".") and part not in (".", "..") for part in rest.split("/")
                ):
                    raise Refused(f"{path} is hidden")
    return lexical


def text(body, error=False):
    result = {"content": [{"type": "text", "text": body}]}
    if error:
        result["isError"] = True
    return result


def list_directory(args, conf):
    path = resolve(args.get("path") or ".", conf)
    names = sorted(os.listdir(path))
    if not conf["show_hidden"]:
        names = [n for n in names if not n.startswith(".")]
    lines = [n + ("/" if os.path.isdir(os.path.join(path, n)) else "") for n in names]
    return text("\n".join(lines) or "(empty)")


def read_file(args, conf):
    path = resolve(args.get("path") or "", conf)
    with open(path, errors="replace") as f:
        return text(f.read(MAX_BYTES))


def write_file(args, conf):
    path = resolve(args.get("path") or "", conf)
    with open(path, "w") as f:
        f.write(str(args.get("content", "")))
    return text(f"wrote {path}")


TOOLS = {
    "list_directory": (list_directory, "List a folder the server shares"),
    "read_file": (read_file, "Read a text file from a folder the server shares"),
    "write_file": (write_file, "Write a text file in a folder the server shares"),
}


def offered(conf):
    return [name for name in TOOLS if name != "write_file" or not conf["read_only"]]


def call(name, args):
    conf = config()
    if name not in offered(conf):
        raise KeyError(name)
    try:
        return TOOLS[name][0](args or {}, conf)
    except Refused as e:
        log(f"refused {name}: {e}")
        return text(f"refused: {e}", error=True)
    except OSError as e:
        return text(f"error: {e.strerror}", error=True)


def reply(message_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": message_id}
    message["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main():
    log(f"starting; roots {config()['roots']}")
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    }
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        message_id, method = message.get("id"), message.get("method")
        params = message.get("params") or {}
        if method == "initialize":
            version = params.get("protocolVersion", "2025-06-18")
            reply(
                message_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "files", "version": "2.3.0"},
                },
            )
        elif method == "tools/list":
            tools = [
                {"name": name, "description": TOOLS[name][1], "inputSchema": schema}
                for name in offered(config())
            ]
            reply(message_id, {"tools": tools})
        elif method == "tools/call":
            try:
                reply(message_id, call(params.get("name"), params.get("arguments")))
            except KeyError:
                reply(message_id, error={"code": -32602, "message": "unknown tool"})
        elif message_id is not None:
            reply(message_id, error={"code": -32601, "message": f"unknown method {method}"})


if __name__ == "__main__":
    main()
