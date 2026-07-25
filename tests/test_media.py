"""Unit tests for the VLC HTTP media backend command building."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.media import (
    ItunesArtResolver,
    MediaManager,
    MediaState,
    VlcHttpBackend,
    _art_token,
    effective_art_token,
)


class _CapturingBackend(VlcHttpBackend):
    """VlcHttpBackend that records requested paths instead of doing HTTP."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def _request(self, path: str) -> dict:  # type: ignore[override]
        self.paths.append(path)
        return {}


@pytest.mark.asyncio
async def test_seek_builds_absolute_seconds_request() -> None:
    """A seek must hit VLC's ``command=seek`` with an absolute second value.

    Regression for #45: seek was unhandled and raised, which tore down the
    websocket session and bounced the client's position slider back to 0.
    """
    backend = _CapturingBackend()
    await backend.command("seek", 137.6)
    assert backend.paths == ["/requests/status.json?command=seek&val=138"]


@pytest.mark.asyncio
async def test_seek_clamps_negative_to_zero() -> None:
    backend = _CapturingBackend()
    await backend.command("seek", -5)
    assert backend.paths == ["/requests/status.json?command=seek&val=0"]


@pytest.mark.asyncio
async def test_volume_and_rate_still_work() -> None:
    backend = _CapturingBackend()
    await backend.command("volume", 50)
    await backend.command("rate", 1.5)
    assert backend.paths == [
        "/requests/status.json?command=volume&val=128",
        "/requests/status.json?command=rate&val=1.5",
    ]


@pytest.mark.asyncio
async def test_unsupported_command_raises() -> None:
    backend = _CapturingBackend()
    with pytest.raises(ValueError):
        await backend.command("bogus", 1)


def test_art_token_stable_and_absent() -> None:
    # Same art url -> same token; different url -> different; none -> None.
    a = _art_token("file:///home/u/.cache/vlc/art/one.jpg")
    assert a and a == _art_token("file:///home/u/.cache/vlc/art/one.jpg")
    assert a != _art_token("file:///home/u/.cache/vlc/art/two.jpg")
    assert _art_token(None) is None
    assert _art_token("") is None


class _ArtBackend(VlcHttpBackend):
    """Backend whose read() sees a status payload carrying art, and whose art
    fetch returns fixed bytes — no real HTTP."""

    def _request(self, path: str) -> dict:  # type: ignore[override]
        return {
            "state": "playing",
            "information": {
                "category": {"meta": {"title": "Song", "artwork_url": "file:///art/x.png"}},
            },
        }

    def _request_raw(self, path: str) -> tuple[str, bytes]:  # type: ignore[override]
        assert path == "/art"
        return "image/png", b"PNGDATA"


@pytest.mark.asyncio
async def test_read_exposes_art_token_and_art_fetches_bytes() -> None:
    backend = _ArtBackend()
    state = await backend.read()
    assert state.art_token is not None
    assert await backend.art() == ("image/png", b"PNGDATA")


@pytest.mark.asyncio
async def test_art_returns_none_when_fetch_fails() -> None:
    class _Failing(VlcHttpBackend):
        def _request_raw(self, path: str) -> tuple[str, bytes]:  # type: ignore[override]
            raise OSError("connection refused")

    assert await _Failing().art() is None


# --- online (iTunes) art resolution -----------------------------------------


def _state(**kw: object) -> MediaState:
    base = dict(available=True, title="Song", artist="Band", album="Record")
    base.update(kw)
    return MediaState(**base)  # type: ignore[arg-type]


def test_effective_art_token_prefers_vlc_then_identity() -> None:
    # VLC art wins outright.
    assert effective_art_token(_state(art_token="vlcart"), ["vlc", "itunes"]) == "vlcart"
    # No VLC art + itunes enabled + metadata -> a derived identity token.
    tok = effective_art_token(_state(art_token=None), ["vlc", "itunes"])
    assert tok and tok.startswith("id:")
    # No VLC art, itunes NOT enabled -> no token (client shows placeholder).
    assert effective_art_token(_state(art_token=None), ["vlc"]) is None
    # itunes enabled but no metadata -> no token.
    assert effective_art_token(MediaState(available=True), ["vlc", "itunes"]) is None


class _FakeResolver(ItunesArtResolver):
    def __init__(self, *, results: list[dict], image: tuple[str, bytes]) -> None:
        super().__init__()
        self._results = results
        self._image = image
        self.searches: list[str] = []
        self.image_fetches: list[str] = []

    def _get_json(self, url: str) -> dict:  # type: ignore[override]
        self.searches.append(url)
        return {"results": self._results}

    def _get_image(self, url: str) -> tuple[str, bytes]:  # type: ignore[override]
        self.image_fetches.append(url)
        return self._image


@pytest.mark.asyncio
async def test_itunes_resolver_upsizes_and_caches() -> None:
    resolver = _FakeResolver(
        results=[{"artworkUrl100": "https://is.example/a/100x100bb.jpg"}],
        image=("image/jpeg", b"JPEG"),
    )
    art = await resolver.resolve(_state())
    assert art == ("image/jpeg", b"JPEG")
    # Asked for the large render, not the 100px thumb.
    assert resolver.image_fetches == ["https://is.example/a/600x600bb.jpg"]
    # A second lookup for the same identity is served from cache (no new HTTP).
    await resolver.resolve(_state())
    assert len(resolver.searches) == 1


@pytest.mark.asyncio
async def test_itunes_resolver_caches_misses() -> None:
    resolver = _FakeResolver(results=[], image=("image/jpeg", b""))
    assert await resolver.resolve(_state()) is None
    assert await resolver.resolve(_state()) is None
    assert len(resolver.searches) == 1  # miss cached, not retried


@pytest.mark.asyncio
async def test_manager_art_falls_back_to_itunes() -> None:
    resolver = _FakeResolver(
        results=[{"artworkUrl100": "https://is.example/a/100x100bb.jpg"}],
        image=("image/jpeg", b"JPEG"),
    )
    manager = MediaManager(art_resolver=resolver)
    # Seed the latest state as if a read happened, with no VLC art.
    manager._latest["w"] = _state(art_token=None)
    art = await manager.art(
        "w", host="127.0.0.1", port=8080, password_ref=None, sources=["vlc", "itunes"]
    )
    assert art == ("image/jpeg", b"JPEG")


@pytest.mark.asyncio
async def test_manager_art_skips_itunes_when_not_enabled() -> None:
    resolver = _FakeResolver(
        results=[{"artworkUrl100": "https://is.example/a/100x100bb.jpg"}],
        image=("image/jpeg", b"JPEG"),
    )
    manager = MediaManager(art_resolver=resolver)
    manager._latest["w"] = _state(art_token=None)
    art = await manager.art("w", host="127.0.0.1", port=8080, password_ref=None, sources=["vlc"])
    assert art is None
    assert resolver.searches == []
