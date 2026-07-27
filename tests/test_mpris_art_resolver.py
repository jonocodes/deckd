"""Unit tests for the MPRIS art URL resolver (issue #57).

The resolver is the part of the daemon's ``/mpris/<row>/art`` proxy
that turns a row's current ``mpris:artUrl`` string into
``(content_type, bytes)``. It supports three shapes — ``file://``,
``http(s)://``, ``data:`` — and rejects everything else by returning
``None`` so the proxy 404s cleanly.

The HTTP / ``data:`` shapes are stubbed via dependency injection
(``urlopen`` / ``base64``), so no network or local filesystem is
touched in the unit tests.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.mpris_art import resolve_mpris_art  # noqa: E402


def test_file_url_reads_local_bytes(tmp_path: Path) -> None:
    art = tmp_path / "cover.png"
    art.write_bytes(b"PNGDATA")
    out = resolve_mpris_art(f"file://{art}", urlopen=lambda *a, **k: None)
    assert out == ("image/png", b"PNGDATA")


def test_file_url_rejects_path_outside_file_scheme() -> None:
    # ``smb://`` is a non-``file://`` scheme — even if the rest of the
    # string looks like a path, the resolver must reject it rather than
    # open an arbitrary URL.
    assert resolve_mpris_art("smb://server/cover.jpg", urlopen=lambda *a, **k: None) is None


def test_http_url_fetches_via_injected_urlopen() -> None:
    class _Headers:
        def get_content_type(self) -> str:
            return "image/jpeg"

    class _Resp:
        def __init__(self) -> None:
            self.headers = _Headers()

        def read(self) -> bytes:
            return b"JPEGBYTES"

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *a: object) -> None:
            return None

    seen: list[str] = []

    def _fake_urlopen(req, timeout=0.0):  # type: ignore[no-untyped-def]
        seen.append(req.full_url)
        return _Resp()

    out = resolve_mpris_art("https://example.com/cover.jpg", urlopen=_fake_urlopen)
    assert out == ("image/jpeg", b"JPEGBYTES")
    assert seen == ["https://example.com/cover.jpg"]


def test_http_url_returns_none_when_urlopen_raises() -> None:
    def _boom(*a: object, **k: object) -> object:
        raise URLError("connection refused")

    assert resolve_mpris_art("https://example.com/cover.jpg", urlopen=_boom) is None


def test_data_url_decodes_base64_payload() -> None:
    payload = base64.b64encode(b"INLINEPNG").decode()
    out = resolve_mpris_art(
        f"data:image/png;base64,{payload}",
        urlopen=lambda *a, **k: None,
    )
    assert out == ("image/png", b"INLINEPNG")


def test_data_url_without_base64_marker_is_rejected() -> None:
    # ``data:image/png,AAA`` (un-encoded text) is technically valid
    # per the data: URL spec but is rare in the wild; we only ship
    # base64, so reject it for v1 — keeps the resolver small and
    # future-proofs us against malformed bytes.
    assert (
        resolve_mpris_art(
            "data:image/png,AAA", urlopen=lambda *a, **k: None
        )
        is None
    )


def test_unknown_scheme_returns_none() -> None:
    assert (
        resolve_mpris_art("ftp://server/cover.jpg", urlopen=lambda *a, **k: None)
        is None
    )


def test_empty_or_non_string_url_returns_none() -> None:
    assert resolve_mpris_art("", urlopen=lambda *a, **k: None) is None
    assert resolve_mpris_art(None, urlopen=lambda *a, **k: None) is None  # type: ignore[arg-type]


def test_malformed_data_url_returns_none() -> None:
    # ``data:`` with no media type / payload is malformed; treat as
    # no-art and 404.
    assert resolve_mpris_art("data:", urlopen=lambda *a, **k: None) is None
    assert (
        resolve_mpris_art("data:image/png", urlopen=lambda *a, **k: None) is None
    )
