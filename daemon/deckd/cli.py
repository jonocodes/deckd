from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

from . import PASSWORD_HEADER

# deckctl deliberately does NOT read ~/.config/deckd/password itself (that's
# the daemon's file; reaching into it would be a layering violation) — a
# remote password comes from --password or $DECKD_PASSWORD only.


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckctl")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Shared password for the daemon (falls back to $DECKD_PASSWORD). "
            "Required whenever the daemon runs with auth on; not needed if the "
            "daemon was started with --no-auth."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("reload")
    layout_parser = sub.add_parser("layout")
    layout_parser.add_argument(
        "layout_id", help="Layout id (its first match token), e.g. firefox or default"
    )

    args = parser.parse_args()
    base = f"http://{args.host}:{args.port}"
    password = args.password or os.environ.get("DECKD_PASSWORD")
    headers = {PASSWORD_HEADER: password} if password else {}

    if args.cmd == "status":
        _get_and_print(f"{base}/health", headers)
    elif args.cmd == "reload":
        _post_and_print(f"{base}/reload", headers)
    elif args.cmd == "layout":
        _post_and_print(f"{base}/layout/{args.layout_id}", headers)


def _get_and_print(url: str, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        print(json.dumps(json.loads(resp.read()), indent=2))


def _post_and_print(url: str, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, method="POST", headers=headers)
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
