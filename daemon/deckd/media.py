from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("deckd.media")


@dataclass(frozen=True)
class MediaState:
    available: bool
    stale: bool = False
    playing: bool | None = None
    position: float | None = None
    duration: float | None = None
    volume: int | None = None
    rate: float | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    # A stable token derived from the current artwork, or None when the item
    # has no art. It changes when the art changes, so the client can point an
    # <img> at the daemon's art proxy and cache-bust on track change.
    art_token: str | None = None
    # MPRIS-only fields populated only by :class:`deckd.mpris.DbusMprisBackend`
    # (issue #52). VLC keeps them ``None``. The browser renders
    # ``desktop_entry`` as the app badge and uses ``can_go_next`` /
    # ``can_go_previous`` to gate the matching transport buttons.
    desktop_entry: str | None = None
    can_go_next: bool | None = None
    can_go_previous: bool | None = None


def _art_token(artwork_url: object) -> str | None:
    """A short, stable id for a piece of art. None when there is no art, so
    the client falls back to the placeholder rather than requesting a 404."""
    if not isinstance(artwork_url, str) or not artwork_url:
        return None
    return hashlib.sha1(artwork_url.encode()).hexdigest()[:16]


def _identity(state: "MediaState") -> str:
    """A track's identity for online art lookup / caching: artist|album|title."""
    return "|".join(p for p in (state.artist, state.album, state.title) if p)


def effective_art_token(state: "MediaState", sources: list[str]) -> str | None:
    """The token the client should see, given the enabled art sources. VLC's
    own art wins; otherwise, if online lookup is enabled and the track has any
    identifying metadata, derive a token from that identity so the client still
    requests art (the daemon resolves it lazily on that request)."""
    if state.art_token is not None:
        return state.art_token
    if "itunes" in sources:
        ident = _identity(state)
        if ident:
            return "id:" + hashlib.sha1(ident.encode()).hexdigest()[:16]
    return None


class ItunesArtResolver:
    """Looks up cover art from the iTunes Search API (no key, no auth). Results
    are cached in-memory by track identity, including misses (cached as None),
    so a given track is looked up at most once."""

    _USER_AGENT = "deckd/1.0 (+https://github.com/jonocodes/deckd)"
    # iTunes returns 100px thumbs; the mzstatic CDN honours arbitrary sizes in
    # the ``<N>x<N>bb`` path segment.
    _ART_SIZE = 600

    def __init__(self, cache_cap: int = 128) -> None:
        self._cache: dict[str, tuple[str, bytes] | None] = {}
        self._cache_cap = cache_cap

    async def resolve(self, state: "MediaState") -> tuple[str, bytes] | None:
        ident = _identity(state)
        if not ident:
            return None
        if ident in self._cache:
            return self._cache[ident]
        result = await asyncio.to_thread(self._resolve_sync, state.artist, state.album, state.title)
        if len(self._cache) >= self._cache_cap:
            self._cache.pop(next(iter(self._cache)))
        self._cache[ident] = result
        return result

    def clear(self) -> None:
        self._cache.clear()

    # -- overridable HTTP seams (so tests can stub the network) -------------

    def _get_json(self, url: str) -> dict:
        request = Request(url, headers={"User-Agent": self._USER_AGENT})
        with urlopen(request, timeout=4.0) as response:
            return json.loads(response.read())

    def _get_image(self, url: str) -> tuple[str, bytes]:
        request = Request(url, headers={"User-Agent": self._USER_AGENT})
        with urlopen(request, timeout=4.0) as response:
            return response.headers.get_content_type(), response.read()

    def _resolve_sync(
        self, artist: str | None, album: str | None, title: str | None
    ) -> tuple[str, bytes] | None:
        # Prefer artist+album (album entity); fall back to artist+track.
        term = " ".join(p for p in (artist, album or title) if p).strip()
        if not term:
            return None
        entity = "album" if album else "song"
        url = "https://itunes.apple.com/search?" + urlencode(
            {"term": term, "entity": entity, "limit": 1}
        )
        try:
            data = self._get_json(url)
        except Exception as exc:
            log.debug("iTunes search failed for %r: %s", term, exc)
            return None
        results = data.get("results") or []
        if not results:
            return None
        art_url = results[0].get("artworkUrl100")
        if not isinstance(art_url, str) or not art_url:
            return None
        # iTunes returns a 100px thumb; ask for a larger render.
        art_url = art_url.replace("100x100bb", f"{self._ART_SIZE}x{self._ART_SIZE}bb")
        try:
            return self._get_image(art_url)
        except Exception as exc:
            log.debug("iTunes art fetch failed for %r: %s", art_url, exc)
            return None


class MediaBackend:
    async def read(self) -> MediaState:
        raise NotImplementedError

    async def command(self, command: str, value: float) -> None:
        raise NotImplementedError

    async def art(self) -> tuple[str, bytes] | None:
        """Return ``(content_type, bytes)`` for the current item's art, or
        None when there is none / it can't be fetched."""
        return None


class VlcHttpBackend(MediaBackend):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        password_ref: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.password_ref = password_ref

    def _password(self) -> str | None:
        return os.environ.get(self.password_ref) if self.password_ref else None

    def _authorized_request(self, path: str) -> Request:
        request = Request(f"http://{self.host}:{self.port}{path}")
        password = self._password()
        if password is not None:
            token = base64.b64encode(f":{password}".encode()).decode()
            request.add_header("Authorization", f"Basic {token}")
        return request

    def _request(self, path: str) -> dict:
        with urlopen(self._authorized_request(path), timeout=1.0) as response:
            return json.loads(response.read())

    def _request_raw(self, path: str) -> tuple[str, bytes]:
        with urlopen(self._authorized_request(path), timeout=2.0) as response:
            return response.headers.get_content_type(), response.read()

    async def read(self) -> MediaState:
        try:
            data = await asyncio.to_thread(self._request, "/requests/status.json")
        except Exception as exc:
            log.debug("VLC HTTP state unavailable: %s", exc)
            return MediaState(available=False, stale=True)
        information = data.get("information", {})
        meta = information.get("meta", {})
        category_meta = information.get("category", {}).get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        if not isinstance(category_meta, dict):
            category_meta = {}
        combined_meta = {**category_meta, **meta}
        length = data.get("length")
        time = data.get("time")
        volume = data.get("volume")
        artwork_url = combined_meta.get("artwork_url")
        return MediaState(
            available=True,
            stale=False,
            playing=data.get("state") == "playing",
            position=float(time) if isinstance(time, (int, float)) else None,
            duration=float(length) if isinstance(length, (int, float)) else None,
            volume=round(float(volume) / 256 * 100) if isinstance(volume, (int, float)) else None,
            rate=float(data["rate"]) if isinstance(data.get("rate"), (int, float)) else None,
            title=combined_meta.get("title"),
            artist=combined_meta.get("artist"),
            album=combined_meta.get("album"),
            art_token=_art_token(artwork_url),
        )

    async def art(self) -> tuple[str, bytes] | None:
        try:
            return await asyncio.to_thread(self._request_raw, "/art")
        except Exception as exc:
            log.debug("VLC art unavailable: %s", exc)
            return None

    async def command(self, command: str, value: float) -> None:
        if command == "volume":
            params = {"command": "volume", "val": str(round(value / 100 * 256))}
        elif command == "rate":
            params = {"command": "rate", "val": str(max(0.1, value))}
        elif command == "seek":
            # VLC's seek takes an absolute time in seconds; the client already
            # sends the slider value in seconds (min=0, max=duration).
            params = {"command": "seek", "val": str(max(0, round(value)))}
        else:
            raise ValueError(f"unsupported media command: {command}")
        await asyncio.to_thread(self._request, f"/requests/status.json?{urlencode(params)}")


class MediaManager:
    def __init__(self, art_resolver: ItunesArtResolver | None = None) -> None:
        self._backends: dict[str, MediaBackend] = {}
        self._latest: dict[str, MediaState] = {}
        self._art_resolver = art_resolver or ItunesArtResolver()

    def backend_for(self, key: str, *, host: str, port: int, password_ref: str | None) -> MediaBackend:
        backend = self._backends.get(key)
        if backend is None:
            backend = VlcHttpBackend(host, port, password_ref)
            self._backends[key] = backend
        return backend

    async def read(self, key: str, *, host: str, port: int, password_ref: str | None) -> MediaState:
        state = await self.backend_for(key, host=host, port=port, password_ref=password_ref).read()
        self._latest[key] = state
        return state

    async def command(self, key: str, command: str, value: float, *, host: str, port: int, password_ref: str | None) -> None:
        await self.backend_for(key, host=host, port=port, password_ref=password_ref).command(command, value)

    async def art(
        self,
        key: str,
        *,
        host: str,
        port: int,
        password_ref: str | None,
        sources: list[str],
    ) -> tuple[str, bytes] | None:
        """Resolve the current item's art through the enabled sources in
        order: VLC's own art first (only attempted when the last read reported
        art), then the online catalogue as a fallback."""
        state = self._latest.get(key)
        if "vlc" in sources and state is not None and state.art_token is not None:
            art = await self.backend_for(key, host=host, port=port, password_ref=password_ref).art()
            if art is not None:
                return art
        if "itunes" in sources and state is not None:
            art = await self._art_resolver.resolve(state)
            if art is not None:
                return art
        return None

    def stop(self) -> None:
        self._backends.clear()
        self._latest.clear()
        self._art_resolver.clear()
