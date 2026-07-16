from __future__ import annotations

import asyncio
import logging
from typing import Protocol

log = logging.getLogger("deckd.input")


class ScrollSink(Protocol):
    def emit_scroll(self, delta: int) -> None:
        """Emit one high-resolution vertical wheel delta."""

    def close(self) -> None:
        """Release any OS resources held by the sink."""


class LoggingScrollSink:
    """Fallback sink used when python-evdev or /dev/uinput is unavailable."""

    def emit_scroll(self, delta: int) -> None:
        log.info("[scroll log] REL_WHEEL_HI_RES=%s", delta)

    def close(self) -> None:
        pass


class UinputScrollSink:
    def __init__(self) -> None:
        try:
            from evdev import UInput, ecodes
        except ImportError as exc:
            raise RuntimeError(
                "evdev is not installed; install deckd with the uinput extra"
            ) from exc

        class WriteOnlyUInput(UInput):
            def _find_device(self, fd: int):
                return None

        self._ecodes = ecodes
        capabilities = {
            ecodes.EV_REL: [
                ecodes.REL_WHEEL,
                ecodes.REL_WHEEL_HI_RES,
            ],
        }
        self._device = WriteOnlyUInput(capabilities, name="deckd scroll")
        self._wheel_remainder = 0
        log.info("created write-only uinput scroll device at %s", self._device.devnode)

    def emit_scroll(self, delta: int) -> None:
        if delta == 0:
            return
        self._device.write(self._ecodes.EV_REL, self._ecodes.REL_WHEEL_HI_RES, delta)

        # Keep legacy wheel consumers moving without throwing away sub-notch
        # precision for compositors that understand REL_WHEEL_HI_RES.
        self._wheel_remainder += delta
        detents = int(self._wheel_remainder / 120)
        if detents:
            self._wheel_remainder -= detents * 120
            self._device.write(self._ecodes.EV_REL, self._ecodes.REL_WHEEL, detents)
        self._device.syn()
        log.debug("[scroll] REL_WHEEL_HI_RES=%s", delta)

    def close(self) -> None:
        self._device.close()


def make_scroll_sink() -> ScrollSink:
    try:
        return UinputScrollSink()
    except Exception as exc:
        log.warning("uinput scroll unavailable; falling back to logging only: %s", exc)
        return LoggingScrollSink()


class ScrollController:
    def __init__(
        self,
        sink: ScrollSink | None = None,
        *,
        momentum_friction: float = 0.90,
        momentum_cutoff: int = 20,
    ) -> None:
        self._sink = sink if sink is not None else make_scroll_sink()
        self._momentum_tasks: dict[str, asyncio.Task[None]] = {}
        self._momentum_friction = momentum_friction
        self._momentum_cutoff = momentum_cutoff
        self._closed = False

    def jog(self, widget_id: str, delta: int) -> None:
        if self._closed:
            return
        self._cancel_momentum(widget_id)
        self._sink.emit_scroll(delta)

    def jog_end(self, widget_id: str, velocity: int) -> None:
        if self._closed:
            return
        self._cancel_momentum(widget_id)
        if abs(velocity) < self._momentum_cutoff:
            return
        self._momentum_tasks[widget_id] = asyncio.create_task(
            self._run_momentum(widget_id, velocity)
        )

    async def _run_momentum(self, widget_id: str, velocity: int) -> None:
        frame_s = 1 / 60
        remainder = 0.0
        try:
            while abs(velocity) >= self._momentum_cutoff:
                await asyncio.sleep(frame_s)
                delta = velocity * frame_s + remainder
                whole = int(delta)
                remainder = delta - whole
                if whole:
                    self._sink.emit_scroll(whole)
                velocity = int(velocity * self._momentum_friction)
        finally:
            self._momentum_tasks.pop(widget_id, None)

    def _cancel_momentum(self, widget_id: str) -> None:
        task = self._momentum_tasks.pop(widget_id, None)
        if task is not None:
            task.cancel()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = list(self._momentum_tasks.values())
        self._momentum_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sink.close()
