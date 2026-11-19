"""Bind-address resolution for the deckd daemon (issue #66).

The daemon binds its HTTP/WS surface to one or more addresses. Each
address is supplied as a string — either a literal IP (v4 or v6) or
an ``iface:<name>`` spec that resolves to every IP attached to the
named interface. The default is ``["127.0.0.1", "::1"]`` — localhost
only, so a freshly installed daemon is reachable from the local
machine but invisible on the LAN even before token auth is configured.

The module is intentionally stdlib-only and has no awareness of
aiohttp: callers translate the resolved addresses into one
``TCPSite`` per family, the rest of the surface (``/health``,
``/diag``, ``deckctl status``) reads ``Server.bind_addresses`` to
report what's actually listening.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Callable, Iterable

log = logging.getLogger("deckd.bind")

# The default bind list when neither CLI nor NixOS module specifies
# one. Both IPv4 and IPv6 loopback so the daemon is reachable from
# the local machine on either stack without leaking onto the LAN.
DEFAULT_BIND: tuple[str, ...] = ("127.0.0.1", "::1")

IFACE_PREFIX = "iface:"


@dataclass(frozen=True)
class ResolvedBind:
    """One listen address after resolution.

    ``family`` is one of ``socket.AF_INET`` / ``socket.AF_INET6`` —
    the caller needs it to open the right ``TCPSite``. ``original``
    is the spec the operator wrote (``"127.0.0.1"``, ``"::1"``,
    ``"iface:wlan0"``); ``host`` is what aiohttp sees. ``iface`` is
    ``None`` for literal addresses; for ``iface:<name>`` it carries
    the interface name so diagnostics can group addresses by source.
    """

    host: str
    family: int
    original: str
    iface: str | None = None

    @property
    def is_ipv6(self) -> bool:
        return self.family == socket.AF_INET6


def parse_bind_specs(specs: Iterable[str] | None) -> tuple[str, ...]:
    """Validate and normalise the operator-supplied bind list.

    Accepts a None / empty list and returns :data:`DEFAULT_BIND`. Does
    not resolve interface names — that happens in
    :func:`resolve_bind` once the daemon process exists.

    Validation is strict: typos are an error, not a silent fallback.
    A literal address must parse cleanly via :mod:`ipaddress`; an
    ``iface:`` spec must have a non-empty name.
    """
    if not specs:
        return DEFAULT_BIND
    seen: set[str] = set()
    out: list[str] = []
    for raw in specs:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"bind spec must be a non-empty string, got {raw!r}")
        spec = raw.strip()
        if spec in seen:
            # Dedup so the runtime doesn't open the same socket twice.
            continue
        seen.add(spec)
        if spec.startswith(IFACE_PREFIX):
            name = spec[len(IFACE_PREFIX) :].strip()
            if not name:
                raise ValueError(
                    f"bind spec {spec!r}: '{IFACE_PREFIX}' requires an interface name"
                )
            # Re-pack with the trimmed name so ``iface:  eth0  `` becomes
            # ``iface:eth0`` — easier for diagnostic output and avoids
            # confusing duplicates like ``iface:wlan0`` vs ``iface: wlan0``.
            out.append(f"{IFACE_PREFIX}{name}")
            continue
        # Literal address: accept IPv4 dotted-quad, IPv6 colon-hex,
        # and CIDR (the latter gets trimmed to the network address).
        try:
            ip = ipaddress.ip_interface(spec)
        except ValueError as exc:
            raise ValueError(
                f"bind spec {spec!r} is not a valid IP address or "
                f"'{IFACE_PREFIX}<name>' spec: {exc}"
            ) from exc
        out.append(str(ip.ip))
    return tuple(out)


def resolve_bind(specs: Iterable[str] | None) -> list[ResolvedBind]:
    """Expand bind specs to concrete ``ResolvedBind`` records.

    Pure function — no I/O beyond ``socket.getaddrinfo`` (for literal
    addresses, to learn the family) and ``socket.if_nameindex``
    (for ``iface:<name>``). Interface expansion returns one
    :class:`ResolvedBind` per IP attached to the named interface
    that is actually ``up``.

    Resolution errors are surfaced as ``ValueError``; the daemon
    fails fast at startup rather than silently falling back to a
    less-specific bind.
    """
    parsed = parse_bind_specs(specs)
    out: list[ResolvedBind] = []
    for spec in parsed:
        if spec.startswith(IFACE_PREFIX):
            name = spec[len(IFACE_PREFIX) :]
            iface_ips = _iface_addresses(name)
            if not iface_ips:
                raise ValueError(
                    f"bind spec '{spec}': interface {name!r} has no usable "
                    f"IPv4/IPv6 addresses (missing or down?)"
                )
            for host, family in iface_ips:
                out.append(
                    ResolvedBind(host=host, family=family, original=spec, iface=name)
                )
            continue
        try:
            ip = ipaddress.ip_address(spec)
        except ValueError as exc:
            raise ValueError(f"bind spec {spec!r} did not parse: {exc}") from exc
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        out.append(ResolvedBind(host=spec, family=family, original=spec))
    return out


def _iface_addresses(name: str) -> list[tuple[str, int]]:
    """Return ``[(host, family), ...]`` for every usable address on ``name``.

    Uses ``socket.if_nameindex`` to enumerate interfaces, then
    ``getaddrinfo`` on each name to learn both the v4/v6 address and
    the address family. Addresses that the kernel flags down are
    dropped — a disconnected ``wlan0`` shouldn't make the daemon bind
    a stale address.
    """
    # ``if_nameindex`` returns ``[(idx, name), ...]``; verify the
    # operator's name is real before we ask getaddrinfo to discover
    # it (which would silently return loopback on a typo on some
    # platforms).
    known = {n for _, n in socket.if_nameindex()}
    if name not in known:
        raise ValueError(
            f"interface {name!r} not found; known: "
            f"{', '.join(sorted(known)) or '(none)'}"
        )
    results: list[tuple[str, int]] = []
    try:
        infos = socket.getaddrinfo(
            name, None, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValueError(f"getaddrinfo({name!r}) failed: {exc}") from exc
    for family, *_rest, sockaddr in infos:
        raw_host = sockaddr[0]
        assert isinstance(raw_host, str)
        host: str = raw_host
        # Skip ``::`` (the IPv6 any-address) — only the operator
        # should ask for that explicitly, and only as a literal.
        if host == "::":
            continue
        # ``%iface`` scoping on link-local IPv6 addresses is kept so
        # ``iface:eth0`` resolves to ``fe80::1%eth0`` correctly.
        if "%" in host:
            host_part, _, _zone = host.partition("%")
            host = host_part
        results.append((host, family))
    return results


def url_for(
    binds: Iterable[ResolvedBind],
    port: int,
    scheme: str = "http",
    *,
    lan_host: Callable[[], str | None] | None = None,
) -> str:
    """Build a pairing URL from the first resolved bind.

    Prefers IPv4 over IPv6 because phones on the same LAN more often
    have working v4 than a clean v6 path. The port is the
    actually-listening port (``self.port`` after ``start()``
    resolved any ``port=0`` sentinel).

    A wildcard bind (``0.0.0.0`` / ``::``) is replaced with an address
    the phone can actually open, because ``http://0.0.0.0:8765/`` is
    not reachable from another device (issue #206). ``lan_host`` is
    the discovery hook — callers leave it unset; tests inject a stub
    so no real network is touched.
    """
    family_priority: dict[int, int] = {socket.AF_INET: 0, socket.AF_INET6: 1}
    sorted_binds = sorted(binds, key=lambda b: family_priority.get(b.family, 99))
    if not sorted_binds:
        return ""
    host = _url_host(sorted_binds[0], lan_host or local_lan_ipv4)
    return f"{scheme}://{host}:{port}/"


def _url_host(bind: ResolvedBind, lan_host: Callable[[], str | None]) -> str:
    """Host part of the pairing URL, substituting wildcard binds.

    IPv6 literals are wrapped in brackets so ``http://[::1]:8765/``
    reads as one URL. The wildcard substitution happens first so a
    ``::`` bind with a reachable IPv4 gets no brackets (issue #206).
    """
    if _is_wildcard(bind.host):
        return lan_host() or "127.0.0.1"
    if bind.is_ipv6:
        return f"[{bind.host}]"
    return bind.host


def local_lan_ipv4() -> str | None:
    """Best-effort IPv4 address another device on the LAN can reach.

    The default-route trick asks the kernel which source address it
    would use without sending a packet; hosts with no default route
    fall back to the addresses the host name resolves to. Returns
    ``None`` when only loopback / link-local addresses exist, so the
    caller can fall back to ``127.0.0.1`` (issue #206).
    """
    host = _default_route_ipv4()
    if host is not None:
        return host
    candidates = _hostname_ipv4_addresses()
    return candidates[0] if candidates else None


def _default_route_ipv4() -> str | None:
    """Source address of the default route via a connected UDP socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # ``connect`` on UDP only selects a route; nothing is sent.
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return host if _usable_lan_ipv4(host) else None


def _hostname_ipv4_addresses() -> list[str]:
    """Every usable IPv4 address the host name resolves to, in order."""
    try:
        infos = socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
        )
    except OSError:
        return []
    hosts: list[str] = []
    for info in infos:
        host = info[4][0]
        if not isinstance(host, str):
            continue
        if _usable_lan_ipv4(host) and host not in hosts:
            hosts.append(host)
    return hosts


def _usable_lan_ipv4(host: str) -> bool:
    """True for an IPv4 address a LAN peer could connect to."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.version == 4
        and not ip.is_unspecified
        and not ip.is_loopback
        and not ip.is_link_local
    )


def _is_wildcard(host: str) -> bool:
    """True for the IPv4/IPv6 any-address (``0.0.0.0`` / ``::``)."""
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False
