from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckctl")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("reload")
    layout_parser = sub.add_parser("layout")
    layout_parser.add_argument(
        "layout_id", help="Layout id (its first match token), e.g. firefox or default"
    )

    args = parser.parse_args()
    base = f"http://{args.host}:{args.port}"

    if args.cmd == "status":
        _get_and_print(f"{base}/health")
    elif args.cmd == "reload":
        _post_and_print(f"{base}/reload")
    elif args.cmd == "layout":
        _post_and_print(f"{base}/layout/{args.layout_id}")


def _get_and_print(url: str) -> None:
    with urllib.request.urlopen(url, timeout=3) as resp:
        print(json.dumps(json.loads(resp.read()), indent=2))


def _post_and_print(url: str) -> None:
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(json.dumps(json.loads(resp.read()), indent=2))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except json.JSONDecodeError:
            print(body)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
