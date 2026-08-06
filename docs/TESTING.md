# Testing strategy

This document captures deckd's testing layers and — more importantly — the
layer that is **not yet built**: end-to-end coverage of the "desktop" half of
this web-meets-desktop app. It exists because a whole class of bug (see
[the motivating case](#the-motivating-case)) passed every existing test and
only surfaced on a live session.

## The current ladder (what exists)

Bottom to top, fast to slow. Full commands live in the
[verification ladder](ONBOARDING.md#verification-ladder).

| Layer | Examples | What it covers | What it fakes |
|---|---|---|---|
| Unit / protocol | pydantic round-trips, reducers, label derivation | Pure logic and wire shapes | everything external |
| Daemon integration | `tests/test_*_websocket.py` | Real in-process daemon over a real WebSocket | the focus backend (`FakeFocusBackend`); gdbus/xdotool monkeypatched to canned strings |
| Client e2e (Playwright) | `client/e2e/kbd-mode.spec.ts` | Real daemon + real browser | the uinput sink is shadowed to `LoggingKeySink` (`PYTHONPATH=scripts/no-evdev`) |
| Smoke | `scripts/smoke.py` | Boots daemon, fires every action primitive | uinput (log-only) |

**The pattern to notice:** everything is verified right up to the OS boundary,
and nothing across it. Two boundaries are never exercised for real:

1. **Extension ↔ compositor** — does `ListWindows` actually enumerate? does
   `RaiseWindow` actually raise?
2. **uinput ↔ focused app** — does an injected key / click / scroll actually
   land where it was aimed?

Both are the desktop half of "web meets desktop," and both are currently
unmocked-untested.

## The motivating case

The GNOME extension's `ListWindows()` called `global.display.get_window_actors()`
— but that method lives on the Shell `global` (`Shell.Global`), not on
`global.display` (`Meta.Display` has no such method). A `? :` guard swallowed the
missing method and returned `[]`, so the running-windows list was silently empty
on **every** real GNOME session from stage 2 (#126) onward. Every test was green
because every test mocked gdbus daemon-side. It surfaced only when a human ran it
on a live GNOME 50 session while verifying #127. Fixed in commit `e166242`.

The tiers below are the tests that would have caught it.

## The missing tier: desktop integration

Tracked as four tickets, cheapest → most expensive. Dig-in order: A tickets
first (fast, no infra), then B (the real payoff), then C.

| Ticket | Tier | Scope | Cost / cadence |
|---|---|---|---|
| [#129](https://github.com/jonocodes/deckd/issues/129) | A | Live-bus contract smoke: `ListWindows` / `GetActiveWindow` / `RaiseWindow` return well-formed responses over the session bus | cheap; skip when bus absent |
| [#130](https://github.com/jonocodes/deckd/issues/130) | A | Shared window-JSON shape contract between the extension producer and the daemon parser | cheap; pure |
| [#131](https://github.com/jonocodes/deckd/issues/131) | B | Nested/headless compositor: open real windows, assert enumeration, close the loop on raise (`RaiseWindow` → `GetActiveWindow` reflects it) | medium; **nightly / opt-in, not the PR gate** |
| [#132](https://github.com/jonocodes/deckd/issues/132) | C | Input closed-loop via an echo receiver app: injected event → app records it → assert it matches | high; **nightly / opt-in** |

### Rule: keep the desktop tier off the blocking PR gate

Coming from web testing, the instinct is "run everything on every commit." Don't,
for this tier. Desktop-integration tests trade determinism for realism — a nested
GNOME session has startup races, focus-timing quirks, and version-specific API
drift. Budget for occasional flakiness, run them as a separate nightly / opt-in
`desktop-integration` workflow, and treat them as *"catch the class of bug mocks
can't"* rather than a per-commit gate. The fast pytest / vitest suites stay the
gate; the desktop tier is the safety net.

## Are these GNOME-specific?

No — they sit on a spectrum:

- **#132 (input echo loop)** is the least compositor-tied. Injection is
  kernel-level `uinput` / evdev, identical under GNOME, KDE, and X11, with a
  separate Quartz path on macOS. It tests "did the event land," independent of
  the compositor.
- **#129 / #130 (bus smoke + shape contract)** are GNOME-*first* but
  compositor-*agnostic by design*. The `org.deckd.Focus` interface and the
  window-JSON shape are deliberately byte-identical between GNOME (the extension
  owns the bus name) and KDE (the daemon owns it, the KWin script pushes in — see
  `KdeFocusBackend` in `daemon/deckd/platform.py`). The parser-side contract
  already covers both; they extend to KDE as it grows the capabilities.
- **#131 (nested compositor)** is written with a GNOME path and a later
  sway / labwc / weston path for the KWin / generic backend (#31).

**Caveat:** enumeration + raise (`ListWindows` / `RaiseWindow`) only *exist* on the
GNOME backend today — KDE inherits focus-only, and X11 / macOS have no enumeration
— so in practice these run GNOME-first until KDE catches up. macOS focus
(osascript / Quartz, no D-Bus) would need a different harness entirely, out of
scope for these four.
