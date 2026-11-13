"""Agent status tiles (issue #180): a view-only fleet view of AI coding agents.

The daemon holds a source-agnostic snapshot of :class:`AgentStatus`
entries and pushes it to every session as an ``agents`` frame. Each
orchestrator plugs in behind :class:`AgentSource`, whose only job is to
translate its native states into the six-value :data:`AgentState` enum
(see ``docs/research/agent-orchestrator-status.md`` §6 for the mapping
table across Paseo, T3 Code, opencode, Claude Code hooks, …).

The first — and so far only — source is :class:`PaseoAgentSource`,
which subscribes to the Paseo daemon's WebSocket. It authenticates
with the same-user ``$PASEO_HOME/local-credential`` token, so no
password configuration is needed. The protocol is Paseo's own, not a
documented public API: the source logs the server version and fails
soft (no tiles) on anything it doesn't recognise.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import aiohttp

log = logging.getLogger(__name__)

#: Tile state, in roll-up priority order: the first is the most urgent.
#: Mirrors Paseo's own ``deriveAgentStateBucket`` with ``offline``
#: added for liveness. Sources that can't tell "finished, unseen" from
#: "idle" just never emit ``done``.
AgentState = Literal["needs_input", "error", "working", "done", "idle", "offline"]

AGENT_STATE_PRIORITY: tuple[AgentState, ...] = (
    "needs_input",
    "error",
    "working",
    "done",
    "idle",
    "offline",
)


@dataclass(frozen=True)
class AgentStatus:
    """One agent tile, already translated out of the source's vocabulary.

    ``(source, id)`` is the identity. ``detail`` is a short reason
    (the tool awaiting approval, an error kind) and must never carry a
    prompt or transcript text. ``since`` is epoch seconds for when the
    agent entered ``state``, or ``None`` when the source can't say.
    """

    source: str
    id: str
    title: str
    state: AgentState
    cwd: str | None = None
    detail: str | None = None
    since: float | None = None


def sort_agents(agents: list[AgentStatus]) -> list[AgentStatus]:
    """Most urgent first, then most recently changed, then title.

    The client renders in wire order, so this is the one place the
    tile order is decided.
    """
    rank = {state: i for i, state in enumerate(AGENT_STATE_PRIORITY)}
    return sorted(
        agents,
        key=lambda a: (rank[a.state], -(a.since or 0.0), a.title.lower(), a.id),
    )


class AgentSource(Protocol):
    """Anything that can stream full agent snapshots.

    Each yielded list replaces the previous one wholesale; the server
    dedupes and broadcasts. A source that loses its upstream should
    yield ``[]`` (no tiles) rather than leave stale tiles on screen.
    """

    name: str

    def watch(self) -> AsyncIterator[list[AgentStatus]]: ...


# -- Paseo -------------------------------------------------------------------

#: Default WebSocket endpoint of a local Paseo daemon.
PASEO_DEFAULT_URL = "ws://127.0.0.1:6767/ws"

#: Paseo protocol version this bridge speaks (``hello.protocolVersion``).
PASEO_PROTOCOL_VERSION = 1

_DETAIL_MAX = 60


def paseo_home() -> Path:
    """``$PASEO_HOME``, else ``~/.paseo`` — where Paseo keeps its state."""
    return Path(os.environ.get("PASEO_HOME") or Path.home() / ".paseo")


def _iso_to_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _DETAIL_MAX else text[: _DETAIL_MAX - 1] + "…"


def paseo_state(agent: Mapping[str, Any]) -> AgentState | None:
    """Map one Paseo agent snapshot onto :data:`AgentState`.

    Follows Paseo's own ``deriveAgentStateBucket`` precedence. Returns
    ``None`` for agents that shouldn't get a tile at all: ``closed``
    (persisted, no live runtime — Paseo keeps hundreds of these) and
    archived ones.
    """
    status = agent.get("status")
    if status == "closed" or agent.get("archivedAt"):
        return None
    reason = agent.get("attentionReason")
    if agent.get("pendingPermissions") or reason == "permission":
        return "needs_input"
    if status == "error" or reason == "error":
        return "error"
    if status in ("running", "initializing"):
        return "working"
    if agent.get("requiresAttention"):
        return "done"
    if status == "idle":
        return "idle"
    # An unknown future status: show it rather than hide it, but make
    # no claim about what it means.
    return "idle"


def _paseo_detail(agent: Mapping[str, Any], state: AgentState) -> str | None:
    if state == "needs_input":
        perms = agent.get("pendingPermissions") or []
        first = perms[0] if perms and isinstance(perms[0], Mapping) else {}
        kind = first.get("kind")
        if kind == "question":
            return "Has a question"
        if kind == "plan":
            return "Plan ready for review"
        # Name the tool only. ``title`` / ``input`` / ``detail`` can
        # carry the command or file contents, which don't belong on a
        # glanceable screen.
        tool = first.get("name")
        if isinstance(tool, str) and tool:
            return _truncate(f"Approve {tool}")
        return "Waiting for approval"
    if agent.get("status") == "initializing":
        return "Starting"
    return None


def paseo_agent_status(agent: Mapping[str, Any]) -> AgentStatus | None:
    """Translate one Paseo ``AgentSnapshotPayload`` into an entry, or
    ``None`` when the agent should have no tile."""
    agent_id = agent.get("id")
    if not isinstance(agent_id, str) or not agent_id:
        return None
    state = paseo_state(agent)
    if state is None:
        return None
    cwd = agent.get("cwd") if isinstance(agent.get("cwd"), str) else None
    title = agent.get("title")
    if not isinstance(title, str) or not title.strip():
        title = Path(cwd).name if cwd else agent_id[:7]
    since = _iso_to_epoch(agent.get("attentionTimestamp")) if agent.get("requiresAttention") else None
    if since is None:
        since = _iso_to_epoch(agent.get("updatedAt"))
    return AgentStatus(
        source="paseo",
        id=agent_id,
        # Untruncated: it doubles as the browser-window title an
        # ``agent:paseo`` deck token matches (issue #180). The client clamps.
        title=title.strip(),
        state=state,
        cwd=cwd,
        detail=_paseo_detail(agent, state),
        since=since,
    )


class PaseoProtocolError(Exception):
    """The Paseo daemon answered with something this bridge can't use."""


class PaseoAgentSource:
    """Subscribe to a Paseo daemon's agent list over its WebSocket.

    Handshake (Paseo 0.12, protocol 1):

    1. ``hello`` with ``auth: {kind: "localCredential", token}``;
    2. wait for the ``server_info`` status frame — sending a session
       message before it makes the server close with code 4002;
    3. ``fetch_agents_request`` with ``subscribe: {}`` → a full
       ``fetch_agents_response`` snapshot, then ``agent_update``
       upsert/remove pushes.

    Everything else on the socket (notably a steady flood of
    ``agent_stream`` timeline frames) is ignored. On any disconnect the
    source yields ``[]`` and reconnects with capped backoff, re-reading
    the credential each time because a Paseo restart rotates it.
    """

    name = "paseo"

    def __init__(
        self,
        *,
        url: str = PASEO_DEFAULT_URL,
        home: Path | None = None,
        retry_initial_s: float = 1.0,
        retry_max_s: float = 30.0,
        session_factory: Callable[[], aiohttp.ClientSession] = aiohttp.ClientSession,
    ) -> None:
        self.url = url
        self.home = home if home is not None else paseo_home()
        self.retry_initial_s = retry_initial_s
        self.retry_max_s = retry_max_s
        self._session_factory = session_factory
        self._client_id = f"deckd-{uuid.uuid4()}"
        #: Last ``server_info.version`` seen, for ``/diag``-style logging.
        self.server_version: str | None = None

    def _read_token(self) -> str:
        return (self.home / "local-credential").read_text().strip()

    async def watch(self) -> AsyncIterator[list[AgentStatus]]:
        delay = self.retry_initial_s
        quiet = False
        while True:
            connected = False
            try:
                # ``aclosing`` so closing ``watch()`` also closes the inner
                # session generator — and with it the Paseo socket —
                # instead of leaving it open until garbage collection.
                async with contextlib.aclosing(self._session()) as session:
                    async for snapshot in session:
                        connected = True
                        yield snapshot
            except asyncio.CancelledError:
                raise
            except (OSError, aiohttp.ClientError, asyncio.TimeoutError, PaseoProtocolError, ValueError) as exc:
                # Paseo not running is the common case on a machine that
                # just doesn't use it: say so once, then go quiet.
                if not quiet:
                    log.info("paseo agent source unavailable (%s); retrying quietly", exc)
                    quiet = True
                else:
                    log.debug("paseo agent source retry failed: %s", exc)
            if connected:
                delay = self.retry_initial_s
                quiet = False
                # Upstream gone: drop the tiles rather than leave stale ones.
                yield []
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.retry_max_s)

    async def _session(self) -> AsyncGenerator[list[AgentStatus], None]:
        token = self._read_token()
        async with self._session_factory() as http, http.ws_connect(self.url, heartbeat=30) as ws:
            await ws.send_json(
                {
                    "type": "hello",
                    "clientId": self._client_id,
                    "clientType": "cli",
                    "protocolVersion": PASEO_PROTOCOL_VERSION,
                    "auth": {"kind": "localCredential", "token": token},
                }
            )
            agents: dict[str, AgentStatus] = {}
            subscribed = False
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                frame = json.loads(msg.data)
                if frame.get("type") == "hello.rejected":
                    raise PaseoProtocolError(f"hello rejected: {frame.get('reason')}")
                inner = frame.get("message") if frame.get("type") == "session" else None
                if not isinstance(inner, Mapping):
                    continue
                kind = inner.get("type")
                payload = inner.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                if kind == "status" and payload.get("status") == "server_info" and not subscribed:
                    self.server_version = str(payload.get("version") or "?")
                    log.info("paseo agent source connected (paseo %s)", self.server_version)
                    await ws.send_json(
                        {
                            "type": "session",
                            "message": {
                                "type": "fetch_agents_request",
                                "requestId": f"deckd-{uuid.uuid4()}",
                                "filter": {"includeArchived": False},
                                "subscribe": {},
                            },
                        }
                    )
                    subscribed = True
                elif kind == "fetch_agents_response":
                    agents = {}
                    for entry in payload.get("entries") or []:
                        agent = entry.get("agent") if isinstance(entry, Mapping) else None
                        if isinstance(agent, Mapping):
                            status = paseo_agent_status(agent)
                            if status is not None:
                                agents[status.id] = status
                    yield sort_agents(list(agents.values()))
                elif kind == "agent_update":
                    if payload.get("kind") == "remove":
                        agents.pop(str(payload.get("agentId")), None)
                    else:
                        agent = payload.get("agent")
                        if not isinstance(agent, Mapping) or not isinstance(agent.get("id"), str):
                            continue
                        status = paseo_agent_status(agent)
                        if status is None:
                            agents.pop(agent["id"], None)
                        else:
                            agents[status.id] = status
                    if subscribed:
                        yield sort_agents(list(agents.values()))
