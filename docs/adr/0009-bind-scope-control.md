# Bind scope control: localhost by default, opt-in LAN

The daemon's HTTP/WS surface is an input-injection primitive. Until
now it bound to a single address set by `--host` (default `127.0.0.1`),
which left two sharp edges on the table:

1. IPv6-only clients (some Android phones on a modern network, most
   Tailscale setups) couldn't reach it without an out-of-band
   `0.0.0.0` opt-in.
2. The default `127.0.0.1` wasn't *visibly* safer than `--host 0.0.0.0`
   — the operator had to know it was the default and that the
   `lan = bool` spike flag existed in the NixOS module.

This ADR records the new bind surface: a list of address specs that
defaults to localhost-only on both stacks, accepts per-interface
binding, fails fast on typos, and exposes what's actually listening
through `/health`, `/diag`, and `deckctl status`.

## Decisions

### The bind surface is a list, not a single host

`Server.__init__` now takes `bind: Sequence[str]` alongside the
legacy `host: str` (which is preserved as a single-spec shortcut so
the existing test fixtures and the spike module keep working without
changes). Each spec is one of:

- a literal IPv4/IPv6 address (`127.0.0.1`, `::1`, `0.0.0.0`,
  `fe80::1`);
- a CIDR that gets trimmed to its network address
  (`192.168.0.0/24` → `192.168.0.0`);
- `iface:<name>`, which resolves to every usable IP on the named
  interface via `socket.getaddrinfo` after a `if_nameindex` sanity
  check.

The list replaces `--host`. The CLI flag is `--bind <ADDR>`, repeatable.
Multiple flags produce one `--bind` per item. `bind=None` or no flag
defaults to `("127.0.0.1", "::1")` — localhost only on both stacks.

### All bound sockets share one port

The naive `aiohttp.TCPSite(runner, host, port=0)` lets each site pick
its own ephemeral port, which means `/diag` reports a different port
per address and a phone can't pair. `Server.start` instead pre-creates
one `socket.socket` per resolved bind, binds the first against the
operator's port (or `0`), and re-binds every subsequent socket to the
first's actually-assigned port. All sites then share a single port;
`/diag` reports one.

This works for both literal addresses and `iface:` expansion. IPv6
sockets set `IPV6_V6ONLY` so a single v6 socket can't accidentally
swallow v4 traffic and confuse the diagnostic.

### Validation is strict, no silent fallback

`parse_bind_specs` rejects:

- non-string specs and empty / whitespace-only strings;
- addresses that don't parse via `ipaddress.ip_interface`;
- `iface:` specs without a name;
- duplicate specs (silently deduped, with the survivor logged).

`resolve_bind` rejects:

- `iface:<name>` for unknown interfaces (enumerated via
  `if_nameindex` so a typo doesn't silently become loopback on some
  platforms);
- `iface:<name>` with no usable addresses (the interface is down or
  has only the IPv6 any-address `::`).

Errors are `ValueError`; `__main__` catches them as `argparse.error`
so the operator sees a one-line message and a non-zero exit.

### Token auth is unchanged; LAN scoping is an additional gate

Issue #66 is explicit: "Token auth remains in effect; LAN scoping does
not replace it." `auth.py`, the password gate, and the
`X-Deckd-Password` header check are untouched. A daemon bound to
`0.0.0.0` still requires every non-localhost client to present the
shared password. The bind list reduces *accidental* exposure (a fresh
install doesn't listen on the LAN); it does not change the
*intentional* surface an attacker would have to clear.

### The bind surface is exposed for tooling

Three places surface it:

- `GET /health` (open-auth): adds `bind` (raw specs), `addresses`
  (resolved `[host:port, …]`, IPv6 bracketed), and `url` (single
  pairing URL, IPv4 wins).
- `GET /diag` (open-auth): mirrors the same three fields for the
  AI-debugging surface.
- `deckctl status`: prints `listening on: <url>` and
  `bound: <addresses>` above the JSON body.

`Server._bound_addresses` is the source of truth: after `start()` it
walks `_bind_resolved` (the post-resolution list), before it falls
back to `(self.host, self._bound_port(req))` — which itself uses the
request transport so the diagnostic works under `aiohttp.test_utils`
where `self.port` is `0`.

### NixOS module mirrors the CLI list

`packaging/nixos/deckd-spike.nix`'s `services.deckd-spike` option
swaps the old `lan = bool` (which only knew about `--host 0.0.0.0`)
for `bind = listOf str`, default `[ "127.0.0.1" "::1" ]`. Each list
item becomes one `--bind <ADDR>` flag in the generated `ExecStart`
script. A module user opting in to LAN exposure sets
`bind = [ "0.0.0.0" ]`; one restricting to a single Tailscale
interface sets `bind = [ "iface:tailscale0" ]`. The `lan` flag is
removed — the module had no users yet.

## Out of scope (deferred, deliberately)

- **mDNS / service discovery** — operators still type the URL into
  the phone, or use the existing `tailscale serve` pattern. Auto-
  discovery is a real feature but it's not part of "limit the daemon
  to a chosen network interface" and would need its own ticket.
- **Per-address auth exemptions** — e.g. "skip the password check
  for connections from 127.0.0.1". Issue #66's AC explicitly says
  "Token auth remains in effect", and the rest of the auth model
  relies on no source-address exemption (so a TLS terminator can
  pass auth through transparently). Adding even a loopback exemption
  would break that.
- **Hot reload of the bind list** — `start()` reads the bind specs
  once. Operators changing bind addresses have to restart the daemon.
  This matches every other config knob (layouts, password, port) and
  avoids the question of how to close an existing listener cleanly.

## Consequences

- `Server.__init__`'s `host=` parameter is now optional and slightly
  legacy; new code should pass `bind=`. The legacy parameter keeps
  working so the spike module and existing test fixtures don't have
  to change in lock-step.
- The daemon's CLI surface changes (`--host` is gone; `--bind` is
  repeatable). The Justfile's `run-daemon-lan` and `dev-daemon-lan`
  recipes switched to `--bind 0.0.0.0`; no other recipe touched the
  bind flag.
- `/health` and `/diag` grow three fields (`bind`, `addresses`, `url`).
  Every existing assertion (`body["host"]`, `body["port"]`) keeps
  passing — the new fields are additive. The shape is stable across
  the daemon's life: `bind` is what the operator asked for,
  `addresses` is what's actually listening.
- Operators get a small, clearly-named knob for the
  accidental-exposure risk: the default is localhost-only on both
  v4 and v6, and the NixOS module enforces the same default.
  Opting in to wider exposure is one explicit flag.
