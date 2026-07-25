from __future__ import annotations

import asyncio
import base64
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


class MediaBackend:
    async def read(self) -> MediaState:
        raise NotImplementedError

    async def command(self, command: str, value: float) -> None:
        raise NotImplementedError


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

    def _request(self, path: str) -> dict:
        url = f"http://{self.host}:{self.port}{path}"
        request = Request(url)
        password = self._password()
        if password is not None:
            token = base64.b64encode(f":{password}".encode()).decode()
            request.add_header("Authorization", f"Basic {token}")
        with urlopen(request, timeout=1.0) as response:
            return json.loads(response.read())

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
        )

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
    def __init__(self) -> None:
        self._backends: dict[str, MediaBackend] = {}
        self._latest: dict[str, MediaState] = {}

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

    def stop(self) -> None:
        self._backends.clear()
        self._latest.clear()
