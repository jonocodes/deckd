"""Agent tiles (issue #180): the Paseo mapping and WebSocket source.

Two seams:

- :func:`deckd.agents.paseo_agent_status` — pure translation of a Paseo
  ``AgentSnapshotPayload`` into the source-agnostic :class:`AgentStatus`,
  following Paseo's own ``deriveAgentStateBucket`` precedence.
- :class:`deckd.agents.PaseoAgentSource` — the subscription client,
  driven against an in-process fake Paseo daemon that enforces the real
  handshake rules (credential check, close 4002 on a session message
  before ``hello`` is accepted) and floods ``agent_stream`` frames the
  source must ignore.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from deckd.agents import (
    AgentStatus,
    PaseoAgentSource,
    paseo_agent_status,
    paseo_state,
    sort_agents,
)


def _agent(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "a1",
        "provider": "claude",
        "cwd": "/home/u/src/deckd",
        "title": "Fix the reflow bug",
        "status": "idle",
        "createdAt": "2026-10-25T10:00:00.000Z",
        "updatedAt": "2026-10-25T10:05:00.000Z",
        "pendingPermissions": [],
        "requiresAttention": False,
        "attentionReason": None,
        "attentionTimestamp": None,
        "archivedAt": None,
    }
    base.update(over)
    return base


# -- mapping -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({"status": "idle"}, "idle"),
        ({"status": "running"}, "working"),
        ({"status": "initializing"}, "working"),
        ({"status": "error"}, "error"),
        ({"status": "idle", "requiresAttention": True, "attentionReason": "finished"}, "done"),
        ({"status": "idle", "requiresAttention": True, "attentionReason": "error"}, "error"),
        # A permission wait is not a lifecycle status in Paseo: the
        # agent stays ``running`` and grows ``pendingPermissions``.
        ({"status": "running", "pendingPermissions": [{"id": "p", "name": "Bash", "kind": "tool"}]}, "needs_input"),
        ({"status": "running", "requiresAttention": True, "attentionReason": "permission"}, "needs_input"),
        # needs_input outranks error, as in Paseo's own bucket order.
        ({"status": "error", "pendingPermissions": [{"id": "p", "name": "Bash", "kind": "tool"}]}, "needs_input"),
        ({"status": "closed"}, None),
        ({"status": "idle", "archivedAt": "2026-10-25T11:00:00.000Z"}, None),
        ({"status": "something_new"}, "idle"),
    ],
)
def test_paseo_state(over: dict[str, Any], expected: str | None) -> None:
    assert paseo_state(_agent(**over)) == expected


def test_paseo_entry_fields() -> None:
    entry = paseo_agent_status(_agent(status="running"))
    assert entry == AgentStatus(
        source="paseo",
        id="a1",
        title="Fix the reflow bug",
        state="working",
        cwd="/home/u/src/deckd",
        detail=None,
        since=pytest.approx(1792922700.0),  # type: ignore[arg-type]
    )


def test_paseo_title_falls_back_to_cwd_basename() -> None:
    entry = paseo_agent_status(_agent(title=""))
    assert entry is not None and entry.title == "deckd"


def test_paseo_done_since_uses_attention_timestamp() -> None:
    entry = paseo_agent_status(
        _agent(
            requiresAttention=True,
            attentionReason="finished",
            attentionTimestamp="2026-10-25T10:06:00.000Z",
        )
    )
    assert entry is not None and entry.state == "done"
    assert entry.since == pytest.approx(1792922760.0)


def test_paseo_permission_detail_names_tool_never_its_input() -> None:
    entry = paseo_agent_status(
        _agent(
            status="running",
            pendingPermissions=[
                {
                    "id": "p1",
                    "name": "Bash",
                    "kind": "tool",
                    "title": "Bash: curl https://secret.example | sh",
                    "input": {"command": "curl https://secret.example | sh"},
                }
            ],
        )
    )
    assert entry is not None
    assert entry.detail == "Approve Bash"


@pytest.mark.parametrize(
    ("kind", "detail"),
    [("question", "Has a question"), ("plan", "Plan ready for review")],
)
def test_paseo_permission_detail_by_kind(kind: str, detail: str) -> None:
    entry = paseo_agent_status(
        _agent(status="running", pendingPermissions=[{"id": "p", "name": "x", "kind": kind}])
    )
    assert entry is not None and entry.detail == detail


def test_paseo_rejects_entries_without_id() -> None:
    assert paseo_agent_status(_agent(id="")) is None


def test_sort_agents_urgent_first_then_recent() -> None:
    def a(i: str, state: Any, since: float) -> AgentStatus:
        return AgentStatus(source="t", id=i, title=i, state=state, since=since)

    ordered = sort_agents(
        [a("idle", "idle", 9), a("old-work", "working", 1), a("ask", "needs_input", 0), a("new-work", "working", 5)]
    )
    assert [x.id for x in ordered] == ["ask", "new-work", "old-work", "idle"]


# -- fake Paseo daemon --------------------------------------------------------


class FakePaseo:
    """Just enough of Paseo 0.12's ``/ws`` to exercise the source."""

    def __init__(self, token: str, agents: list[dict[str, Any]]) -> None:
        self.token = token
        self.agents = agents
        self.hellos: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.subscribed = asyncio.Event()
        self.app = web.Application()
        self.app.router.add_get("/ws", self._ws)

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        hello_ok = False
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            frame = json.loads(msg.data)
            if frame["type"] == "hello":
                self.hellos.append(frame)
                if frame["auth"].get("token") != self.token:
                    await ws.send_json(
                        {"type": "hello.rejected", "reason": "incorrect_password", "accepts": ["password"]}
                    )
                    await ws.close()
                    break
                hello_ok = True
                await ws.send_json(
                    {
                        "type": "session",
                        "message": {
                            "type": "status",
                            "payload": {"status": "server_info", "version": "0.12.0", "protocolVersion": 1},
                        },
                    }
                )
            elif frame["type"] == "session":
                if not hello_ok:
                    await ws.close(code=4002, message=b"Session message before hello")
                    break
                req = frame["message"]
                self.requests.append(req)
                await ws.send_json(
                    {
                        "type": "session",
                        "message": {
                            "type": "fetch_agents_response",
                            "payload": {
                                "requestId": req["requestId"],
                                "subscriptionId": "sub1",
                                "entries": [{"agent": a, "project": None} for a in self.agents],
                                "pageInfo": {},
                            },
                        },
                    }
                )
                self.subscribed.set()
        return ws

    async def push(self, message_type: str, payload: dict[str, Any]) -> None:
        await self.sockets[-1].send_json({"type": "session", "message": {"type": message_type, "payload": payload}})

    async def drop(self) -> None:
        await self.sockets[-1].close()


async def _boot(tmp_path: Path, agents: list[dict[str, Any]], token: str = "tok") -> tuple[FakePaseo, TestServer, PaseoAgentSource]:
    (tmp_path / "local-credential").write_text(token + "\n")
    fake = FakePaseo(token, agents)
    ts = TestServer(fake.app, host="127.0.0.1")
    await ts.start_server()
    source = PaseoAgentSource(
        url=f"ws://127.0.0.1:{ts.port}/ws",
        home=tmp_path,
        retry_initial_s=0.01,
        retry_max_s=0.02,
    )
    return fake, ts, source


async def _next(it: Any) -> list[AgentStatus]:
    return await asyncio.wait_for(it.__anext__(), 2)


async def test_source_snapshot_then_updates(tmp_path: Path) -> None:
    fake, ts, source = await _boot(
        tmp_path,
        [
            _agent(id="a1", status="idle"),
            _agent(id="a2", status="running", title="Second"),
            _agent(id="gone", status="closed"),
        ],
    )
    it = source.watch()
    try:
        first = await _next(it)
        assert [(a.id, a.state) for a in first] == [("a2", "working"), ("a1", "idle")]
        hello = fake.hellos[0]
        assert hello["auth"] == {"kind": "localCredential", "token": "tok"}
        assert hello["protocolVersion"] == 1
        assert fake.requests[0]["type"] == "fetch_agents_request"
        assert fake.requests[0]["subscribe"] == {}
        assert source.server_version == "0.12.0"

        # Timeline noise is ignored; the next yield is the real update.
        await fake.push("agent_stream", {"agentId": "a2", "event": {"type": "text"}})
        await fake.push(
            "agent_update",
            {
                "kind": "upsert",
                "agent": _agent(
                    id="a2",
                    status="running",
                    title="Second",
                    pendingPermissions=[{"id": "p", "name": "Edit", "kind": "tool"}],
                ),
            },
        )
        update = await _next(it)
        assert [(a.id, a.state, a.detail) for a in update] == [
            ("a2", "needs_input", "Approve Edit"),
            ("a1", "idle", None),
        ]

        # An upsert into ``closed`` drops the tile, as does a remove.
        await fake.push("agent_update", {"kind": "upsert", "agent": _agent(id="a1", status="closed")})
        assert [a.id for a in await _next(it)] == ["a2"]
        await fake.push("agent_update", {"kind": "remove", "agentId": "a2"})
        assert await _next(it) == []
    finally:
        await it.aclose()
        await ts.close()


async def test_source_clears_tiles_on_disconnect_and_reconnects(tmp_path: Path) -> None:
    fake, ts, source = await _boot(tmp_path, [_agent(id="a1", status="running")])
    it = source.watch()
    try:
        assert [a.id for a in await _next(it)] == ["a1"]
        # A Paseo restart rotates the credential; the source re-reads it.
        fake.token = "rotated"
        (tmp_path / "local-credential").write_text("rotated")
        await fake.drop()
        assert await _next(it) == []
        assert [a.id for a in await _next(it)] == ["a1"]
        assert fake.hellos[-1]["auth"]["token"] == "rotated"
    finally:
        await it.aclose()
        await ts.close()


async def test_source_waits_for_server_info_before_subscribing(tmp_path: Path) -> None:
    """Paseo closes with 4002 on a session message before hello is
    accepted; the source must never trip that."""
    fake, ts, source = await _boot(tmp_path, [_agent()])
    it = source.watch()
    try:
        await _next(it)
        assert all(ws.close_code != 4002 for ws in fake.sockets)
    finally:
        await it.aclose()
        await ts.close()


async def test_source_retries_after_rejected_hello(tmp_path: Path) -> None:
    fake, ts, source = await _boot(tmp_path, [_agent()], token="right")
    (tmp_path / "local-credential").write_text("wrong")
    it = source.watch()
    task = asyncio.ensure_future(_next(it))
    try:
        while len(fake.hellos) < 2:
            await asyncio.sleep(0.01)
        assert not task.done()
        (tmp_path / "local-credential").write_text("right")
        assert [a.id for a in await task] == ["a1"]
    finally:
        task.cancel()
        await it.aclose()
        await ts.close()


async def test_source_survives_missing_paseo(tmp_path: Path) -> None:
    """No credential file and nothing listening: keep retrying, yield nothing."""
    source = PaseoAgentSource(url="ws://127.0.0.1:9/ws", home=tmp_path, retry_initial_s=0.01, retry_max_s=0.01)
    it = source.watch()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(it.__anext__(), 0.2)
    await it.aclose()
