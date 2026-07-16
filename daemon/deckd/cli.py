from __future__ import annotations

import argparse
import json
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckctl")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("reload")

    args = parser.parse_args()
    base = f"http://{args.host}:{args.port}"

    if args.cmd == "status":
        with urllib.request.urlopen(f"{base}/health", timeout=3) as resp:
            print(json.dumps(json.loads(resp.read()), indent=2))
    elif args.cmd == "reload":
        req = urllib.request.Request(f"{base}/reload", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(json.dumps(json.loads(resp.read()), indent=2))
