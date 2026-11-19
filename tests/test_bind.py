"""Tests for :mod:`deckd.bind` (issue #66 LAN scope control).

Covers:
- Default bind list (``127.0.0.1`` + ``::1``)
- ``iface:<name>`` expansion
- Literal IPv4 / IPv6 validation
- Hostile inputs (typos, empty iface, ambiguous addresses)
- URL construction (v6 needs brackets)
"""
from __future__ import annotations

import socket

import pytest

from deckd.bind import (
    DEFAULT_BIND,
    IFACE_PREFIX,
    ResolvedBind,
    parse_bind_specs,
    lan_address,
    resolve_bind,
    url_for,
)


# ---------------------------------------------------------------------------
# parse_bind_specs — string-level validation only, no socket I/O
# ---------------------------------------------------------------------------


def test_parse_defaults_when_none() -> None:
    assert parse_bind_specs(None) == DEFAULT_BIND
    assert parse_bind_specs([]) == DEFAULT_BIND


def test_parse_defaults_when_blank_string() -> None:
    # An all-whitespace spec is treated as invalid (it's not a default
    # fallback — defaults only kick in for the whole list being empty).
    with pytest.raises(ValueError):
        parse_bind_specs(["   "])


def test_parse_literal_ipv4() -> None:
    assert parse_bind_specs(["127.0.0.1"]) == ("127.0.0.1",)
    assert parse_bind_specs(["0.0.0.0"]) == ("0.0.0.0",)


def test_parse_literal_ipv6() -> None:
    assert parse_bind_specs(["::1"]) == ("::1",)
    assert parse_bind_specs(["fe80::1"]) == ("fe80::1",)


def test_parse_strips_cidr_to_address() -> None:
    """A user typing ``192.168.0.0/24`` gets the network address."""
    assert parse_bind_specs(["192.168.0.0/24"]) == ("192.168.0.0",)


def test_parse_iface_spec_passes_through() -> None:
    """``iface:<name>`` is kept as-is; resolution happens later."""
    assert parse_bind_specs(["iface:wlan0"]) == ("iface:wlan0",)
    assert parse_bind_specs(["iface:  eth0  "]) == ("iface:eth0",)


def test_parse_dedups() -> None:
    assert parse_bind_specs(["127.0.0.1", "127.0.0.1"]) == ("127.0.0.1",)


def test_parse_rejects_typo() -> None:
    with pytest.raises(ValueError, match="not a valid IP"):
        parse_bind_specs(["127.0.0.0.1"])


def test_parse_rejects_empty_iface() -> None:
    with pytest.raises(ValueError, match="requires an interface name"):
        parse_bind_specs(["iface:"])


def test_parse_rejects_whitespace_only_iface() -> None:
    with pytest.raises(ValueError, match="requires an interface name"):
        parse_bind_specs(["iface:   "])


def test_parse_rejects_empty_spec() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        parse_bind_specs([""])


# ---------------------------------------------------------------------------
# resolve_bind — does I/O via getaddrinfo / if_nameindex
# ---------------------------------------------------------------------------


def test_resolve_literal_loopback() -> None:
    out = resolve_bind(["127.0.0.1"])
    assert len(out) == 1
    assert out[0].host == "127.0.0.1"
    assert out[0].family == socket.AF_INET
    assert out[0].iface is None
    assert out[0].original == "127.0.0.1"


def test_resolve_literal_ipv6_loopback() -> None:
    out = resolve_bind(["::1"])
    assert len(out) == 1
    assert out[0].family == socket.AF_INET6
    assert out[0].is_ipv6 is True


def test_resolve_defaults_to_both_loopbacks() -> None:
    out = resolve_bind(None)
    hosts = {r.host for r in out}
    # Don't assume the host has a working IPv6 stack; at minimum
    # the IPv4 loopback must be present.
    assert "127.0.0.1" in hosts
    # ``::1`` may or may not resolve on a stripped container — only
    # assert family consistency on what's there.
    for r in out:
        assert r.family in (socket.AF_INET, socket.AF_INET6)


def test_resolve_iface_returns_one_bind_per_address(monkeypatch) -> None:
    """Stub ``if_nameindex`` + ``getaddrinfo`` so the test is
    deterministic regardless of the host's network state."""
    monkeypatch.setattr(
        "socket.if_nameindex", lambda: [(1, "lo"), (2, "wlan0")]
    )
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, _port, **_: [
            (socket.AF_INET, None, None, None, ("10.0.0.5", 0)),
        ]
        if host == "wlan0"
        else [],
    )
    out = resolve_bind(["iface:wlan0"])
    assert len(out) == 1
    bind = out[0]
    assert bind.host == "10.0.0.5"
    assert bind.family == socket.AF_INET
    assert bind.iface == "wlan0"
    assert bind.original == "iface:wlan0"


def test_resolve_iface_unknown_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        "socket.if_nameindex", lambda: [(1, "lo"), (2, "wlan0")]
    )
    with pytest.raises(ValueError, match="interface 'eth9' not found"):
        resolve_bind(["iface:eth9"])


def test_resolve_iface_no_addresses_raises(monkeypatch) -> None:
    """A real interface with no usable IPs (down / link-local only)
    is a hard error — silent fallback would mask misconfiguration."""
    monkeypatch.setattr("socket.if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [])
    with pytest.raises(ValueError, match="no usable IPv4/IPv6 addresses"):
        resolve_bind(["iface:lo"])


def test_resolve_skips_unspecified_ipv6(monkeypatch) -> None:
    """``::`` (IPv6 any) on an interface must not leak into the bind
    list — only the operator asking for it literally."""
    monkeypatch.setattr("socket.if_nameindex", lambda: [(1, "lo")])
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET6, None, None, None, ("::", 0, 0, 0)),
        ],
    )
    with pytest.raises(ValueError, match="no usable IPv4/IPv6 addresses"):
        resolve_bind(["iface:lo"])


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def test_url_for_prefers_ipv4() -> None:
    binds = [
        ResolvedBind(host="::1", family=socket.AF_INET6, original="::1"),
        ResolvedBind(host="127.0.0.1", family=socket.AF_INET, original="127.0.0.1"),
    ]
    # IPv4 sorts first → no brackets.
    assert url_for(binds, 8765) == "http://127.0.0.1:8765/"


def test_url_for_brackets_ipv6() -> None:
    binds = [ResolvedBind(host="::1", family=socket.AF_INET6, original="::1")]
    assert url_for(binds, 9000) == "http://[::1]:9000/"


def test_url_for_empty_binds() -> None:
    assert url_for([], 1234) == ""


def test_url_for_respects_scheme() -> None:
    binds = [ResolvedBind(host="127.0.0.1", family=socket.AF_INET, original="127.0.0.1")]
    assert url_for(binds, 443, scheme="https") == "https://127.0.0.1:443/"


# ---------------------------------------------------------------------------
# Wildcard binds → an address a phone can open (issue #206)
# ---------------------------------------------------------------------------


def _bind(host: str, original: str | None = None, iface: str | None = None) -> ResolvedBind:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    return ResolvedBind(host=host, family=family, original=original or host, iface=iface)


@pytest.fixture
def fake_lan(monkeypatch: pytest.MonkeyPatch) -> dict[int, str | None]:
    """Replace :func:`deckd.bind.lan_address` with a per-family table
    and record every lookup in ``table["calls"]``."""
    import deckd.bind as bind_mod

    table: dict = {
        socket.AF_INET: "192.168.1.20",
        socket.AF_INET6: "2001:db8:1::20",
        "calls": [],
    }

    def fake(family: int) -> str | None:
        table["calls"].append(family)
        return table[family]

    monkeypatch.setattr(bind_mod, "lan_address", fake)
    return table


def test_url_for_substitutes_lan_ipv4_for_ipv4_wildcard(fake_lan) -> None:
    assert url_for([_bind("0.0.0.0")], 8765) == "http://192.168.1.20:8765/"


def test_url_for_substitutes_lan_ipv6_for_ipv6_wildcard(fake_lan) -> None:
    # IPv6 sockets are IPV6_V6ONLY (server._open_bind_sockets), so a bare
    # ``::`` bind only answers on v6 — a v4 URL would be refused.
    assert url_for([_bind("::")], 8765) == "http://[2001:db8:1::20]:8765/"
    assert fake_lan["calls"] == [socket.AF_INET6]


def test_url_for_dual_wildcard_prefers_ipv4(fake_lan) -> None:
    binds = [_bind("::"), _bind("0.0.0.0")]
    assert url_for(binds, 8765) == "http://192.168.1.20:8765/"


def test_url_for_wildcard_falls_back_to_same_family_loopback(fake_lan) -> None:
    fake_lan[socket.AF_INET] = None
    fake_lan[socket.AF_INET6] = None
    assert url_for([_bind("0.0.0.0")], 8765) == "http://127.0.0.1:8765/"
    assert url_for([_bind("::")], 8765) == "http://[::1]:8765/"


def test_url_for_ranks_lan_bind_above_loopback(fake_lan) -> None:
    # Loopback v4 + wildcard v6: only the v6 socket is reachable from a phone.
    binds = [_bind("127.0.0.1"), _bind("::")]
    assert url_for(binds, 8765) == "http://[2001:db8:1::20]:8765/"


def test_url_for_literal_bind_does_not_probe_lan(fake_lan) -> None:
    assert url_for([_bind("192.168.1.9")], 80) == "http://192.168.1.9:80/"
    assert url_for([_bind("::1")], 80) == "http://[::1]:80/"
    assert fake_lan["calls"] == []


def test_url_for_iface_bind_does_not_probe_lan(fake_lan) -> None:
    bind = _bind("192.168.1.9", original="iface:en0", iface="en0")
    assert url_for([bind], 80) == "http://192.168.1.9:80/"
    assert fake_lan["calls"] == []


def _no_hosts(_family: int) -> list[str]:
    return []


def test_lan_address_prefers_default_route_source() -> None:
    assert lan_address(
        socket.AF_INET,
        route_source=lambda _f: "192.168.1.20",
        host_addresses=lambda _f: ["10.0.0.9"],
    ) == "192.168.1.20"


@pytest.mark.parametrize(
    ("family", "bad"),
    [
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET, "0.0.0.0"),
        (socket.AF_INET, "169.254.10.10"),
        (socket.AF_INET, "2001:db8::5"),  # wrong family
        (socket.AF_INET6, "::1"),
        (socket.AF_INET6, "fe80::1"),
        (socket.AF_INET6, "::ffff:192.168.1.20"),  # v4-mapped
        (socket.AF_INET6, "192.168.1.20"),  # wrong family
    ],
)
def test_lan_address_rejects_unusable_candidates(family: int, bad: str) -> None:
    assert lan_address(
        family, route_source=lambda _f: bad, host_addresses=_no_hosts
    ) is None


def test_lan_address_falls_back_to_hostname_addresses() -> None:
    # No default route (isolated LAN): the probe fails, but the host's
    # own addresses still include a reachable one.
    assert lan_address(
        socket.AF_INET,
        route_source=lambda _f: None,
        host_addresses=lambda _f: ["127.0.0.1", "169.254.1.1", "10.0.0.9"],
    ) == "10.0.0.9"


def test_lan_address_none_when_nothing_usable() -> None:
    assert lan_address(
        socket.AF_INET,
        route_source=lambda _f: None,
        host_addresses=lambda _f: ["127.0.0.1"],
    ) is None


def test_iface_prefix_constant_matches_documented_shape() -> None:
    """The CLI / NixOS surface is documented as ``iface:<name>`` —
    changing the prefix is a breaking change."""
    assert IFACE_PREFIX == "iface:"
