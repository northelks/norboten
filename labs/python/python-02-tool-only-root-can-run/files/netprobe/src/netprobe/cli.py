"""netprobe check --config targets.yaml"""

import argparse
import json
import socket
import sys

import yaml

from netprobe import __version__


def probe(target: str, timeout: float) -> bool:
    host, _, port = target.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="netprobe")
    parser.add_argument("--version", action="version", version=f"netprobe {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="probe every target in a YAML file")
    check.add_argument("--config", required=True)
    check.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args(argv)

    with open(args.config) as f:
        targets = yaml.safe_load(f)["targets"]
    results = [{"target": t, "open": probe(t, args.timeout)} for t in targets]
    json.dump(results, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
