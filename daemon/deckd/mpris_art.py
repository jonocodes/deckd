"""MPRIS album-art URL resolver (issue #57).

The daemon's ``/mpris/<row>/art`` proxy turns a row's current
``mpris:artUrl`` string into ``(content_type, bytes)`` for the
client. This module owns the shape-by-shape resolution:

- ``file:///…`` — read the local file the URL points at. This is the
  common case (Firefox / Chromium / Spotify write cover art into the
  user's cache, and MPRIS players surface that path).
- ``http://…`` / ``https://…`` — fetch server-side so the phone
  needs no outbound network or credentials.
- ``data:image/…;base64,…`` — decode the inline payload.

Anything else / missing / malformed returns ``None`` so the proxy
404s cleanly and the client falls back to the disc glyph. The
resolver never accepts a client-supplied URL — the ``/mpris/<row>/art``
route's row id is the only thing the served URL is keyed on, and the
URL the resolver reads is the one the row's current ``Metadata``
reported (the caller passes it in).

The HTTP / file I/O seams are passed in (``urlopen`` / open) so unit
tests don't need a real network or filesystem. Production wires the
stdlib ``urllib.request.urlopen`` and ``pathlib.Path.open``.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import mimetypes
import os
import pathlib
from typing import Any, Callable
from urllib.request import Request, urlopen

log = logging.getLogger("deckd.mpris_art")

# The set of artUrl shapes the ``/mpris/<row>/art`` proxy knows how
# to fetch (issue #57). Anything else / missing -> ``art_token``
# stays ``None`` and the proxy 404s, so the client falls back to the
# ``Disc`` glyph rather than requesting a URL we can't serve.
# Centralised here so :func:`is_supported_art_url` (used by the
# backend to gate the ``art_token`` write) and
# :func:`resolve_mpris_art` (which dispatches on the scheme) can't
# drift apart.
_SUPPORTED_SCHEMES: tuple[str, ...] = ("file://", "http://", "https://", "data:")


# Resolver seam. Returns ``(content_type, bytes)`` or ``None``. The
# real resolver is :func:`resolve_mpris_art`; tests inject a stub to
# avoid filesystem / network I/O.
Resolver = Callable[[str], "tuple[str, bytes] | None"]


def _content_type_from_url(url: str) -> str:
    """Guess a content type from a URL's extension.

    Falls back to ``application/octet-stream`` when the path has no
    extension or the extension is unknown. The HTTP path also
    consults the upstream ``Content-Type`` header (preferred); the
    file / data paths use this guess instead because they have no
    upstream to ask.
    """
    guess, _ = mimetypes.guess_type(url)
    return guess or "application/octet-stream"


def _read_file(url: str) -> tuple[str, bytes] | None:
    """``file://`` arm: strip the scheme, read the local file.

    Returns ``None`` for a missing / unreadable / non-file path so
    the proxy 404s rather than serving a 500. ``os.path.isfile`` is
    a cheap pre-check that avoids the broader exception path on the
    common "file vanished between MPRIS metadata and our fetch" case
    (a player that writes / unlinks its art cache frequently).
    """
    path = url[len("file://") :]
    if not os.path.isfile(path):
        return None
    try:
        with pathlib.Path(path).open("rb") as fp:
            return _content_type_from_url(path), fp.read()
    except OSError as exc:
        log.debug("MPRIS art file read failed for %s: %s", path, exc)
        return None


def _read_http(
    url: str, urlopen: Callable[..., Any] = urlopen
) -> tuple[str, bytes] | None:
    """``http(s)://`` arm: fetch server-side.

    The phone never sees the upstream URL directly; some MPRIS
    players ship art from authenticated CDNs and the phone has no
    way to carry those credentials. ``User-Agent`` is set so a CDN
    that does user-agent gating doesn't drop the request.
    """
    request = Request(url, headers={"User-Agent": "deckd/1.0"})
    try:
        with urlopen(request, timeout=4.0) as response:  # type: ignore[misc]
            content_type = response.headers.get_content_type()
            return content_type, response.read()
    except Exception as exc:  # network errors, HTTPError, etc.
        log.debug("MPRIS art http fetch failed for %s: %s", url, exc)
        return None


def _read_data(url: str) -> tuple[str, bytes] | None:
    """``data:`` arm: decode the inline base64 payload.

    Only ``data:<mediatype>;base64,<payload>`` is supported — see the
    companion test for the rationale. A malformed URL or invalid
    base64 returns ``None`` so the proxy 404s.
    """
    if not url.startswith("data:") or ";base64," not in url:
        return None
    head, _, payload = url.partition(";base64,")
    media_type = head[len("data:") :] or "application/octet-stream"
    try:
        return media_type, base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        log.debug("MPRIS art data URL decode failed: %s", exc)
        return None


def is_supported_art_url(url: Any) -> bool:
    """True when ``url`` is a string whose scheme the resolver knows
    how to fetch (``file://`` / ``http://`` / ``https://`` /
    ``data:``). Single source of truth for the supported scheme
    set — :mod:`deckd.mpris` uses it to gate the ``art_token`` /
    cache write so a non-supported URL never produces a token the
    client would request and 404 on."""
    return (
        isinstance(url, str)
        and bool(url)
        and any(url.startswith(scheme) for scheme in _SUPPORTED_SCHEMES)
    )


def resolve_mpris_art(
    url: str | None,
    *,
    urlopen: Callable[..., Any] = urlopen,
) -> tuple[str, bytes] | None:
    """Resolve a row's ``mpris:artUrl`` to ``(content_type, bytes)``.

    Returns ``None`` for any of the failure modes: ``url`` isn't a
    string, the scheme isn't one of the three supported, the file
    is missing, the network is down, the data URL is malformed. The
    proxy treats every ``None`` as a 404 so the client falls back to
    the disc glyph rather than seeing a broken ``<img>``.

    The ``urlopen`` keyword is the seam tests use to inject a
    stubbed HTTP response — production leaves it as the stdlib
    ``urllib.request.urlopen``.
    """
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("file://"):
        return _read_file(url)
    if url.startswith("http://") or url.startswith("https://"):
        return _read_http(url, urlopen=urlopen)
    if url.startswith("data:"):
        return _read_data(url)
    return None


async def resolve_mpris_art_async(url: str | None) -> tuple[str, bytes] | None:
    """Async wrapper around :func:`resolve_mpris_art`.

    The file / data arms are CPU-only; only the HTTP arm benefits
    from ``asyncio.to_thread``. Kept as a single entry point so the
    proxy's awaitable surface is uniform across the three shapes
    (and so the unit tests can exercise the sync resolver without
    an event loop).
    """
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return await asyncio.to_thread(resolve_mpris_art, url)
    return resolve_mpris_art(url)
