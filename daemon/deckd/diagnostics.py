"""Diagnostic surface for AI-assisted debugging.

Provides a single in-process collector that:

- exposes the daemon's current state in a machine-readable snapshot for
  ``GET /diag`` (focus backend, input sink, layouts, sessions, tasks,
  MPRIS, sensors)
- records the recent ring of action attempts and MPRIS events for
  ``GET /actions/recent`` and ``GET /mpris/events/recent``
- exposes a Prometheus-format counter/gauge surface for ``GET /metrics``

The module deliberately has no knowledge of the HTTP layer; it accepts
plain dataclasses and exposes plain dicts so the same data can be
serialised by ``aiohttp.web`` and inspected by tests directly.

Redaction: every value that crosses the surface is checked. The
``safe_*`` helpers below strip the password / injected-input content
that lives on incoming frames but never on outgoing snapshots.
"""
from __future__ import annotations

import asyncio
import collections
import dataclasses
import logging
import socket
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .layouts import Layout, LayoutStore
    from .media import MediaState
    from .mpris import ChromeMediaState, MprisBackend
    from .platform import AppInfo, PlatformBackend, SensorManager

log = logging.getLogger("deckd.diagnostics")


# ---------------------------------------------------------------------------
# Ring-buffer record types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ActionRecord:
    """One observed action attempt.

    Lives in the recent-action ring buffer; the wire path is
    ``GET /actions/recent``. ``command_text`` is the raw action string
    (e.g. ``"ctrl+t"``, a shell command, the ``dbus:`` value); for
    ``type:`` injections it's the literal text the user typed, which is
    kept on the local ring only — never broadcast over the WebSocket or
    to ``/diag``. Other fields are redacted to the wire path.
    """

    ts: float
    layout_id: str
    widget_id: str
    primitive: str  # "shell" | "key" | "dbus" | "terminal"
    outcome: str  # "ok" | "error" | "guard_dropped" | "no_sink" | "no_widget" | "skipped"
    command_text: str | None  # None on the wire
    error: str | None  # None on the wire

    def to_wire(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "layout_id": self.layout_id,
            "widget_id": self.widget_id,
            "primitive": self.primitive,
            "outcome": self.outcome,
        }


@dataclasses.dataclass(frozen=True)
class MprisEventRecord:
    """One observed MPRIS subsystem event.

    ``kind`` is a string the wire understands (``"player_added"``,
    ``"player_removed"``, ``"playback_changed"``, ``"metadata_changed"``,
    ``"command"``, ``"dbus_error"``). ``data`` is event-specific; never
    includes the shared password, raw input, or arbitrary URL payloads.
    """

    ts: float
    kind: str
    row_id: str | None
    data: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "kind": self.kind,
            "row_id": self.row_id,
            "data": self.data,
        }


# ---------------------------------------------------------------------------
# Metrics surface
# ---------------------------------------------------------------------------
#
# A minimal Prometheus text-format renderer. The module-level counters
# live on a single ``Metrics`` instance owned by ``Server`` so tests can
# construct a fresh one and inspect it without touching global state.
# The renderer is private to the route handler; we keep the public
# surface Python-side so callers don't need to know the wire format.


@dataclasses.dataclass
class Metrics:
    """Process-local counters for the ``/metrics`` route.

    A ``Metrics`` instance is owned by ``Server``. Counters are
    ``int`` fields; ``observe_dbcall_seconds`` is a tiny fixed-bucket
    histogram so the wire format stays simple (no client library
    required to parse it).

    Naming follows Prometheus conventions: ``deckd_<subsystem>_<noun>``
    with a ``_total`` suffix on counters, unit suffix (``_seconds``,
    ``_bytes``) where relevant, and the ``# TYPE`` line per metric.
    """

    # Liveness / general
    daemon_up: int = 1  # gauge, always 1 in production
    sessions_active: int = 0  # gauge (mirrored from server.session_count)
    uptime_started_at: float = dataclasses.field(default_factory=time.time)

    # Layout / focus
    layout_reload_total: int = 0
    layout_error_total: int = 0
    layout_reload_ok_total: int = 0
    focus_events_total: int = 0
    focus_deckd_window_guard_total: int = 0

    # Auth
    ws_auth_failures_total: int = 0
    http_auth_failures_total: int = 0

    # Actions
    action_total: dict[str, int] = dataclasses.field(
        default_factory=lambda: collections.Counter()
    )
    action_outcome_total: dict[str, int] = dataclasses.field(
        default_factory=lambda: collections.Counter()
    )

    # MPRIS
    mpris_player_added_total: int = 0
    mpris_player_removed_total: int = 0
    mpris_command_total: dict[str, int] = dataclasses.field(
        default_factory=lambda: collections.Counter()
    )
    mpris_command_error_total: dict[str, int] = dataclasses.field(
        default_factory=lambda: collections.Counter()
    )
    mpris_dbus_error_total: int = 0
    mpris_metadata_changed_total: int = 0
    mpris_playback_changed_total: int = 0
    mpris_art_errors_total: int = 0

    # Sensors / input
    sensor_stale_total: int = 0
    uinput_available: int = 0  # 1 when UinputSink wired, 0 on fallback

    # D-Bus action timing
    dbcall_seconds: collections.deque = dataclasses.field(
        default_factory=lambda: collections.deque(maxlen=512)
    )

    def record_action(self, primitive: str, outcome: str) -> None:
        self.action_total[primitive] = self.action_total.get(primitive, 0) + 1
        key = f"{primitive}/{outcome}"
        self.action_outcome_total[key] = self.action_outcome_total.get(key, 0) + 1

    def record_mpris_command(self, command: str, ok: bool) -> None:
        self.mpris_command_total[command] = self.mpris_command_total.get(command, 0) + 1
        if not ok:
            self.mpris_command_error_total[command] = (
                self.mpris_command_error_total.get(command, 0) + 1
            )

    def record_dbcall(self, seconds: float) -> None:
        self.dbcall_seconds.append(seconds)

    # -- text format ---------------------------------------------------------

    def render(self) -> str:
        """Render Prometheus text-format (version 0.0.4) output."""
        out: list[str] = []
        out.append("# HELP deckd_up Daemon process liveness")
        out.append("# TYPE deckd_up gauge")
        out.append(f"deckd_up {self.daemon_up}")
        out.append("# HELP deckd_uptime_seconds Seconds since process start")
        out.append("# TYPE deckd_uptime_seconds gauge")
        out.append(f"deckd_uptime_seconds {time.time() - self.uptime_started_at:.3f}")
        out.append("# HELP deckd_sessions_active Connected WebSocket sessions")
        out.append("# TYPE deckd_sessions_active gauge")
        out.append(f"deckd_sessions_active {self.sessions_active}")

        out.append("# HELP deckd_layout_reload_total Layout reload attempts")
        out.append("# TYPE deckd_layout_reload_total counter")
        out.append(f"deckd_layout_reload_total{self._lbl('status', 'ok')} {self.layout_reload_ok_total}")
        out.append(f"deckd_layout_reload_total{self._lbl('status', 'error')} {self.layout_reload_total - self.layout_reload_ok_total}")
        out.append("# HELP deckd_layout_error_total Layout YAML validation errors")
        out.append("# TYPE deckd_layout_error_total counter")
        out.append(f"deckd_layout_error_total {self.layout_error_total}")

        out.append("# HELP deckd_focus_events_total Focus changes seen by daemon")
        out.append("# TYPE deckd_focus_events_total counter")
        out.append(f"deckd_focus_events_total {self.focus_events_total}")
        out.append("# HELP deckd_focus_deckd_window_guard_total Times the daemon's own browser window focused")
        out.append("# TYPE deckd_focus_deckd_window_guard_total counter")
        out.append(
            f"deckd_focus_deckd_window_guard_total {self.focus_deckd_window_guard_total}"
        )

        out.append("# HELP deckd_ws_auth_failures_total WebSocket auth rejections")
        out.append("# TYPE deckd_ws_auth_failures_total counter")
        out.append(f"deckd_ws_auth_failures_total {self.ws_auth_failures_total}")
        out.append("# HELP deckd_http_auth_failures_total HTTP auth rejections")
        out.append("# TYPE deckd_http_auth_failures_total counter")
        out.append(f"deckd_http_auth_failures_total {self.http_auth_failures_total}")

        out.append("# HELP deckd_action_total Action dispatches by primitive")
        out.append("# TYPE deckd_action_total counter")
        for primitive in sorted(self.action_total):
            out.append(
                f"deckd_action_total{self._lbl('primitive', primitive)} {self.action_total[primitive]}"
            )
        out.append("# HELP deckd_action_outcome_total Action outcomes by primitive+outcome")
        out.append("# TYPE deckd_action_outcome_total counter")
        for key in sorted(self.action_outcome_total):
            primitive, outcome = key.split("/", 1)
            out.append(
                f"deckd_action_outcome_total"
                f"{self._lbl_multi(('primitive', primitive), ('outcome', outcome))} "
                f"{self.action_outcome_total[key]}"
            )

        out.append("# HELP deckd_mpris_player_added_total MPRIS players registered")
        out.append("# TYPE deckd_mpris_player_added_total counter")
        out.append(f"deckd_mpris_player_added_total {self.mpris_player_added_total}")
        out.append("# HELP deckd_mpris_player_removed_total MPRIS players unregistered")
        out.append("# TYPE deckd_mpris_player_removed_total counter")
        out.append(f"deckd_mpris_player_removed_total {self.mpris_player_removed_total}")
        out.append("# HELP deckd_mpris_metadata_changed_total MPRIS Metadata updates")
        out.append("# TYPE deckd_mpris_metadata_changed_total counter")
        out.append(
            f"deckd_mpris_metadata_changed_total {self.mpris_metadata_changed_total}"
        )
        out.append("# HELP deckd_mpris_playback_changed_total MPRIS PlaybackStatus transitions")
        out.append("# TYPE deckd_mpris_playback_changed_total counter")
        out.append(
            f"deckd_mpris_playback_changed_total {self.mpris_playback_changed_total}"
        )
        out.append("# HELP deckd_mpris_command_total MPRIS commands dispatched")
        out.append("# TYPE deckd_mpris_command_total counter")
        for command in sorted(self.mpris_command_total):
            out.append(
                f"deckd_mpris_command_total{self._lbl('command', command)} {self.mpris_command_total[command]}"
            )
        out.append("# HELP deckd_mpris_command_error_total MPRIS command errors")
        out.append("# TYPE deckd_mpris_command_error_total counter")
        for command in sorted(self.mpris_command_error_total):
            out.append(
                f"deckd_mpris_command_error_total{self._lbl('command', command)} {self.mpris_command_error_total[command]}"
            )
        out.append("# HELP deckd_mpris_dbus_error_total MPRIS D-Bus errors")
        out.append("# TYPE deckd_mpris_dbus_error_total counter")
        out.append(f"deckd_mpris_dbus_error_total {self.mpris_dbus_error_total}")
        out.append("# HELP deckd_mpris_art_errors_total MPRIS art resolution failures")
        out.append("# TYPE deckd_mpris_art_errors_total counter")
        out.append(f"deckd_mpris_art_errors_total {self.mpris_art_errors_total}")

        out.append("# HELP deckd_sensor_stale_total Sensor stale-flag flips")
        out.append("# TYPE deckd_sensor_stale_total counter")
        out.append(f"deckd_sensor_stale_total {self.sensor_stale_total}")
        out.append("# HELP deckd_uinput_available UinputSink wired (1) or fallback (0)")
        out.append("# TYPE deckd_uinput_available gauge")
        out.append(f"deckd_uinput_available {self.uinput_available}")

# D-Bus latency histogram (cumulative buckets + +Inf)
        out.append("# HELP deckd_dbcall_seconds D-Bus action call latency")
        out.append("# TYPE deckd_dbcall_seconds histogram")
        buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
        counts = [0] * len(buckets)
        for s in self.dbcall_seconds:
            for i, le in enumerate(buckets):
                if s <= le:
                    counts[i] += 1
                    break
        # Cumulative bucket counts: each bucket includes all observations
        # that fell into a lower-or-equal bucket. Prometheus readers
        # expect this monotonic form.
        cumulative: list[int] = []
        running = 0
        for c in counts:
            running += c
            cumulative.append(running)
        for le, c in zip(buckets, cumulative):
            out.append(f'deckd_dbcall_seconds_bucket{{le="{le}"}} {c}')
        out.append(f'deckd_dbcall_seconds_bucket{{le="+Inf"}} {len(self.dbcall_seconds)}')
        out.append(f"deckd_dbcall_seconds_count {len(self.dbcall_seconds)}")
        out.append(f"deckd_dbcall_seconds_sum {sum(self.dbcall_seconds):.6f}")
        return "\n".join(out) + "\n"

    @staticmethod
    def _lbl(name: str, value: str) -> str:
        # Escape \ and " inside label values per the text-format spec.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{{{name}="{escaped}"}}'

    @staticmethod
    def _lbl_multi(*pairs: tuple[str, str]) -> str:
        """Render multiple labels into a single ``{k1="v1",k2="v2"}`` block.

        Prometheus' text-format spec requires labels to live inside
        one brace group, not be split across consecutive ones.
        """
        if not pairs:
            return ""
        parts = []
        for name, value in pairs:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'{name}="{escaped}"')
        return "{" + ",".join(parts) + "}"


# ---------------------------------------------------------------------------
# Ring buffers
# ---------------------------------------------------------------------------


_DEFAULT_ACTION_BUFFER = 64
_DEFAULT_MPRIS_BUFFER = 64


class RecentActions:
    """Bounded ring of the most recent :class:`ActionRecord` entries.

    Thread-affine to the server's event loop (single-threaded), so no
    locking is needed. Cap is fixed at construction; older entries are
    dropped on overflow.
    """

    def __init__(self, cap: int = _DEFAULT_ACTION_BUFFER) -> None:
        self._cap = cap
        self._buf: collections.deque[ActionRecord] = collections.deque(maxlen=cap)

    def add(self, record: ActionRecord) -> None:
        self._buf.append(record)

    def snapshot(self, limit: int | None = None) -> list[ActionRecord]:
        if limit is None or limit >= len(self._buf):
            return list(self._buf)
        return list(self._buf)[-limit:]


class MprisEvents:
    """Bounded ring of :class:`MprisEventRecord` entries.

    Same single-loop guarantees as :class:`RecentActions`.
    """

    def __init__(self, cap: int = _DEFAULT_MPRIS_BUFFER) -> None:
        self._cap = cap
        self._buf: collections.deque[MprisEventRecord] = collections.deque(maxlen=cap)

    def add(self, record: MprisEventRecord) -> None:
        self._buf.append(record)

    def snapshot(self, limit: int | None = None) -> list[MprisEventRecord]:
        if limit is None or limit >= len(self._buf):
            return list(self._buf)
        return list(self._buf)[-limit:]


# ---------------------------------------------------------------------------
# Diag snapshot
# ---------------------------------------------------------------------------


def safe_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


async def build_diag_snapshot(
    *,
    server: "Any",  # Server, but typed structurally to avoid a cycle
    started_at: float,
    bound_port: int | None = None,
) -> dict[str, Any]:
    """Snapshot the daemon's current state for ``GET /diag``.

    Reads from the server's existing fields and reports only safe
    (non-secret) values. Builds a JSON-friendly dict; the route layer
    serialises it with ``web.json_response``.

    Async because the MPRIS sub-snapshot walks every owned row through
    the (async) ``read_state`` call on the live D-Bus backend.
    Everything else is cheap object reads.
    """
    # ``tasks_state`` collapses four well-known asyncio tasks into a
    # single small map so the snapshot stays scannable.
    focus_task = getattr(server, "_focus_task", None)
    layouts_task = getattr(server, "_layouts_task", None)
    sensor_task = getattr(server, "_sensor_task", None)
    media_task = getattr(server, "_media_task", None)

    def task_state(t: asyncio.Task[None] | None) -> str:
        if t is None:
            return "not_started"
        if t.done():
            return f"done:{t.exception() or 'no_exception'}"
        return "running"

    focus_backend = getattr(server, "focus_backend", None)
    focus_block: dict[str, Any] = {
        "backend": type(focus_backend).__name__ if focus_backend is not None else None,
        "platform": safe_str(getattr(server, "_focus_platform", None)),
        "last_app": _app_info_to_dict(getattr(server, "_last_focus", None)),
        "started_ok": getattr(server, "_focus_started_ok", None),
    }
    if focus_backend is None:
        focus_block["backend"] = None

    key_sink = getattr(server, "key_sink", None)
    sink_name = type(key_sink).__name__ if key_sink is not None else None
    input_block: dict[str, Any] = {
        "sink": sink_name,
        "uinput_devnode": _uinput_devnode(key_sink),
    }

    store = getattr(server, "layouts", None)
    layouts_block: dict[str, Any] = {
        "dir": str(getattr(server, "layouts_dir", "")),
        "overlay_dir": str(getattr(server, "overlay_dir", ""))
        if getattr(server, "overlay_dir", None) is not None
        else None,
        "ids": [l.id for l in store.layouts] if store is not None else [],
        "current_app_id": getattr(server, "_current_app_id", None),
        "current_layout_id": getattr(server, "_current_layout", None)
        and getattr(server, "_current_layout").id,
        "error": getattr(server, "_current_error", None),
    }

    sessions = list(getattr(server, "_sessions", set()))
    sessions_block = [
        {
            "remote": safe_str(getattr(s.ws, "remote", None)),
            "pinned_layout_id": s.pinned_layout_id,
            "view": s.view,
            "trace_id": s.trace_id,
        }
        for s in sessions
    ]

    sensors: "SensorManager | None" = getattr(server, "sensors", None)
    sensors_block = {
        "registered": sorted(sensors.sources) if sensors is not None else [],
        "subscribed": sorted(getattr(server, "_subscribed_sources", set())),
    }

    mpris_block = await build_mpris_diag(getattr(server, "mpris", None))

    scroll = getattr(server, "scroll", None)
    scroll_block = {
        "friction": getattr(scroll, "_momentum_friction", None),
        "cutoff": getattr(scroll, "_momentum_cutoff", None),
        "active_momenta": len(getattr(scroll, "_momentum_tasks", {})),
    }

    auth_required = getattr(server, "password", None) is not None
    auth_block: dict[str, Any] = {"enabled": auth_required}

    return {
        "ok": True,
        "version": "0.0.1",
        "uptime_s": round(time.time() - started_at, 3),
        "started_at": started_at,
        "pid": _safe_pid(),
        "hostname": _hostname(),
        "os": _os_pretty(),
        "desktop": _desktop_env(),
        "host": getattr(server, "host", None),
        "port": bound_port if bound_port is not None else getattr(server, "port", None),
        # Issue #66 LAN scope control. ``bind`` is the operator-configured
        # bind list (the raw specs — ``127.0.0.1``, ``iface:wlan0``, …);
        # ``addresses`` is the post-resolution ``[host:port, …]`` list
        # the daemon is actually listening on; ``url`` is the pairing
        # URL the phone should hit (prefers IPv4 over IPv6).
        "bind": list(getattr(server, "_bind_specs", ())),
        "addresses": [
            f"{host}:{port}"
            for host, port in _safe_bound_addresses(server, bound_port)
        ],
        "url": _pairing_url(server, bound_port or getattr(server, "port", 0)),
        "auth": auth_block,
        "focus": focus_block,
        "input": input_block,
        "scroll": scroll_block,
        "sensors": sensors_block,
        "media": mpris_block,
        "layouts": layouts_block,
        "sessions": sessions_block,
        "tasks": {
            "focus_watcher": task_state(focus_task),
            "layouts_watcher": task_state(layouts_task),
            "sensor_pump": task_state(sensor_task),
            "media_pump": task_state(media_task),
        },
    }


async def build_mpris_diag(backend: "MprisBackend | None") -> dict[str, Any]:
    """Per-MPRIS sub-snapshot for ``GET /diag``.

    Issue #72's acceptance criterion lists six required fields
    (D-Bus connectivity, discovered players, selected player,
    capabilities, playback state, metadata age, last error). ``None``
    backend -> ``available=false``. For the live case we walk every
    owned row once and summarise; nothing is allowed to leak the
    password or raw input.

    Async because the per-row ``read_state`` call is async on the
    real D-Bus backend (the fake returns synchronously, still
    awaited). Built per request, no caching — the snapshot is small
    (bounded by the number of MPRIS players, a handful on a
    typical desktop).
    """
    if backend is None:
        return {"available": False, "backend": None, "players": [], "last_error": None}
    out: dict[str, Any] = {
        "available": True,
        "backend": type(backend).__name__,
        "started_ok": getattr(backend, "_started_ok", True),
        # D-Bus connectivity: ``False`` when ``start()`` raised; a
        # freshly-constructed backend without a start attempt reports
        # ``None`` so /diag distinguishes "not tried yet" from "tried
        # and failed".
        "dbus_connected": getattr(backend, "_started_ok", None),
        "last_error": getattr(backend, "_last_error", None),
        "players": [],
        "selected_player": None,
        "any_playing": False,
        "metadata_age_buckets": {"fresh": 0, "stale": 0, "unknown": 0},
    }
    try:
        row_ids = backend.row_ids()
    except Exception as exc:
        out["last_error"] = repr(exc)
        return out
    any_playing = False
    first_with_state: str | None = None
    fresh = stale = unknown = 0
    for row_id in row_ids:
        state = await backend.read_state(row_id)
        if state is None:
            unknown += 1
            out["players"].append(
                {
                    "row_id": row_id,
                    "state": "unknown",
                    "can_go_next": None,
                    "can_go_previous": None,
                    "playing": None,
                }
            )
            continue
        if state.stale:
            stale += 1
            age = "stale"
        else:
            fresh += 1
            age = "fresh"
        if state.playing:
            any_playing = True
        if first_with_state is None:
            first_with_state = row_id
        out["players"].append(
            {
                "row_id": row_id,
                "state": age,
                "playing": state.playing,
                "can_go_next": state.can_go_next,
                "can_go_previous": state.can_go_previous,
                "app_name": state.app_name,
            }
        )
    out["selected_player"] = first_with_state
    out["any_playing"] = any_playing
    out["metadata_age_buckets"] = {"fresh": fresh, "stale": stale, "unknown": unknown}
    return out


def build_layouts_snapshot(store: "LayoutStore") -> dict[str, Any]:
    """Snapshot the loaded ``LayoutStore`` for ``GET /layouts``."""
    layouts = []
    for layout in store.layouts:
        layouts.append(
            {
                "id": layout.id,
                "match": list(layout.match),
                "display_name": layout.display_name,
                "widgets": [_safe_widget(w) for w in layout.widgets],
            }
        )
    return {"ok": True, "layouts": layouts}


def _safe_widget(widget: Any) -> dict[str, Any]:
    """Widget summary safe to send on ``/layouts``: no action bodies."""
    return {
        "id": widget.id,
        "kind": widget.kind,
        "label": widget.label,
        # Reflow extent (ADR-0010): a ``[w, h]`` span, ``"full"``, or ``None``
        # for a default 1x1 cell. There is no position — widgets pack in order.
        "size": widget.size,
        "has_action": widget.action is not None,
        "kind_specific": _widget_kind_specific(widget),
    }


def _widget_kind_specific(widget: Any) -> dict[str, Any]:
    """Per-kind summary that is safe to expose (no raw shell/dbus strings)."""
    info: dict[str, Any] = {}
    kind = widget.kind
    if kind == "meter":
        info["source"] = widget.source
    elif kind == "stats":
        info["metrics"] = [
            {"source": m.source, "label": m.label} for m in (widget.metrics or [])
        ]
    elif kind == "mediabrowser":
        info["empty_state"] = widget.empty_state
    elif kind == "media":
        info["controls"] = list(widget.controls or [])
    return info


async def build_mpris_players_snapshot(
    backend: "MprisBackend | None",
) -> dict[str, Any]:
    """Snapshot each player's safe state for ``GET /mpris/players``.

    Issue #72: this is the ``safe player state and metadata``
    endpoint, not a duplicate of the per-row ``media_state`` stream.
    Returns a redacted view per row: identity fields
    (``app_name`` / ``desktop_entry``), the playback flag, the
    capability flags (``can_go_next`` / ``can_go_previous``), and a
    metadata age bucket (``fresh`` / ``stale``). ``art_url`` is
    intentionally NOT included — it's a server-only value the proxy
    resolves; the client always pulls it via ``/mpris/{row}/art``.

    Async because the ``read_state`` call against the D-Bus is async
    on the real backend; the fake backend returns synchronously
    (still wrapped in a coroutine to satisfy the Protocol).
    """
    if backend is None:
        return {"ok": True, "available": False, "players": []}
    players: list[dict[str, Any]] = []
    try:
        row_ids = backend.row_ids()
    except Exception as exc:
        return {"ok": True, "available": True, "players": [], "error": repr(exc)}
    for row_id in row_ids:
        state = await backend.read_state(row_id)
        if state is None:
            players.append({"row_id": row_id, "available": False})
            continue
        players.append(
            {
                "row_id": row_id,
                "available": state.available,
                "stale": state.stale,
                "playing": state.playing,
                "app_name": state.app_name,
                "desktop_entry": state.desktop_entry,
                "can_go_next": state.can_go_next,
                "can_go_previous": state.can_go_previous,
                "has_art": state.art_url is not None,
            }
        )
    return {"ok": True, "available": True, "players": players}


def _app_info_to_dict(app: "AppInfo | None") -> dict[str, Any] | None:
    if app is None:
        return None
    return {
        "app_id": app.app_id,
        "wm_class": app.wm_class,
        "title": app.title,
        "pid": app.pid,
    }


def _uinput_devnode(sink: Any) -> str | None:
    """Read the UinputSink's ``devnode`` without triggering a mypy
    ``union-attr`` on the ``None`` branch.

    The production sink carries a private ``_device`` attribute with a
    ``devnode`` property; every other sink (the logging fallback) has
    neither. Returns ``None`` for the fallback path so ``/diag`` can
    serialise a JSON null cleanly.
    """
    device = getattr(sink, "_device", None)
    if device is None:
        return None
    return getattr(device, "devnode", None)


def _safe_pid() -> int | None:
    import os
    try:
        return os.getpid()
    except OSError:
        return None


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _os_pretty() -> str:
    import platform
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME") or info.get("NAME") or platform.system()
    except (OSError, AttributeError):
        return f"{platform.system()} {platform.release()}".strip()


def _desktop_env() -> str:
    import os
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        val = os.environ.get(var)
        if val:
            return val
    return "unknown"


def _safe_bound_addresses(
    server: "Any", port_override: int | None = None
) -> list[tuple[str, int]]:
    """Return ``(host, port)`` pairs the server is bound to.

    Tries ``Server._bound_addresses`` first (issue #66's source of
    truth after ``start()``). Falls back to ``(server.host,
    server.port)`` for ``_FakeServer`` test doubles that don't
    implement the new method. Returns ``[]`` when both are missing
    rather than raising — ``/diag`` must remain best-effort.

    ``port_override`` lets the caller pass the actually-listening
    port when ``server.port`` is still ``0`` (TestServer fixtures,
    ``port=0`` sentinel). Without it, ``/diag`` would report
    ``127.0.0.1:0`` instead of the real port the client should hit.
    """
    getter = getattr(server, "_bound_addresses", None)
    if callable(getter):
        try:
            pairs = list(getter())
        except Exception:
            pairs = []
        if pairs:
            if port_override is not None and port_override > 0:
                return [(host, port_override) for host, _ in pairs]
            return pairs
    host = getattr(server, "host", None)
    port = getattr(server, "port", None)
    if host and port:
        return [(host, port_override or port)]
    return []


def _pairing_url(server: "Any", port: int) -> str | None:
    """Build a single pairing URL for ``/diag``.

    Prefers IPv4 (more likely to be reachable on a phone LAN) and
    brackets IPv6 literals. Returns ``None`` when no bind resolved
    — better than a bogus ``http://:8765/`` in the diagnostic.
    Issue #66.
    """
    from .bind import ResolvedBind, url_for as _bind_url_for

    addrs = _safe_bound_addresses(server)
    if not addrs or not port:
        return None
    resolved = [
        ResolvedBind(
            host=host,
            family=socket.AF_INET6 if ":" in host else socket.AF_INET,
            original=spec,
        )
        for (host, _), spec in zip(
            addrs,
            list(getattr(server, "_bind_specs", ())),
        )
    ]
    return _bind_url_for(resolved, port) or None