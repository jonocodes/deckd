from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from . import PASSWORD_HEADER

# deckctl deliberately does NOT read ~/.config/deckd/password itself (that's
# the daemon's file; reaching into it would be a layering violation) — a
# remote password comes from --password or $DECKD_PASSWORD only.


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckctl")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Address deckctl will speak to the daemon on. Defaults to "
            "127.0.0.1; set to a LAN address or Tailscale name when "
            "the daemon was started with --bind on a wider surface."
        ),
    )
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
    sub.add_parser("diag")
    sub.add_parser("metrics")
    sub.add_parser("layouts")
    layout_parser = sub.add_parser("layout")
    layout_parser.add_argument(
        "layout_id", help="Layout id (its first match token), e.g. firefox or default"
    )

    args = parser.parse_args()
    base = f"http://{args.host}:{args.port}"
    password = args.password or os.environ.get("DECKD_PASSWORD")
    headers = {PASSWORD_HEADER: password} if password else {}

    if args.cmd == "status":
        _status(base, headers)
    elif args.cmd == "reload":
        _post_and_print(f"{base}/reload", headers)
    elif args.cmd == "layout":
        _post_and_print(f"{base}/layout/{args.layout_id}", headers)
    elif args.cmd == "diag":
        _get_and_print(f"{base}/diag", headers)
    elif args.cmd == "layouts":
        _get_and_print(f"{base}/layouts", headers)
    elif args.cmd == "metrics":
        _get_and_print_text(f"{base}/metrics", headers)


def _status(base: str, headers: dict[str, str]) -> None:
    """``deckctl status``: GET /health and pretty-print the bind surface.

    Issue #66: ``/health`` now carries ``bind``, ``addresses``, and
    ``url`` so an operator can confirm the daemon is listening on the
    addresses they expect. The output still ends with the raw JSON
    so a script can pipe it through ``jq`` unchanged — ``_status``
    just prepends a one-line summary when ``url`` is present.
    """
    req = urllib.request.Request(f"{base}/health", headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        body = json.loads(resp.read())
    url = body.get("url") or ""
    if url:
        print(f"listening on: {url}")
        addrs = body.get("addresses") or []
        if addrs:
            print(f"bound:        {', '.join(addrs)}")
        print()
    print(json.dumps(body, indent=2))


def _get_and_print(url: str, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        print(json.dumps(json.loads(resp.read()), indent=2))


def _get_and_print_text(url: str, headers: dict[str, str]) -> None:
    """Variant of :func:`_get_and_print` for non-JSON endpoints (e.g. ``/metrics``)."""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=3) as resp:
        body = resp.read().decode("utf-8")
        sys.stdout.write(body)
        if not body.endswith("\n"):
            sys.stdout.write("\n")


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
