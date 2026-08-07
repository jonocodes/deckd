# Platform feature parity

deckd runs one daemon against several desktop platforms, each with a different
focus/enumeration mechanism and input-injection path. This doc is the single
reconciled view of **what works where** — the source of truth is the code
(`PlatformBackend.capabilities()` in `daemon/deckd/platform.py` and the
injection sinks in `daemon/deckd/input.py` / `daemon/deckd/platform_macos.py`);
this table exists to make drift between backends visible at a glance.

> Keep this in sync when a backend gains or loses a capability. If a row here
> disagrees with `capabilities()`, the code wins — and that disagreement is a
> bug (it's how #133 was found). The three compositor-axis rows
> (`watch_active_app`, `watch_windows`, `raise_window`) are enforced by
> `tests/test_platform_parity.py`, which parses this table and asserts it
> matches every backend's `capabilities()` — so drift fails CI (#136).

## Capability matrix

| Capability | GNOME (Wayland/X11) | KDE Plasma (Wayland) | X11 (generic) | macOS |
|---|---|---|---|---|
| Focus detection (`watch_active_app`) | ✓ GNOME Shell extension over `org.deckd.Focus` | ✓ KWin script pushes into daemon-owned cache (#31) | ✓ `xdotool` poll | ✓ `osascript` + System Events |
| Window enumeration (`watch_windows`) | ✓ extension `ListWindows` | ✗ — not advertised; KWin-side impl is future work ([#133](https://github.com/jonocodes/deckd/issues/133)) | ✗ | ✓ Quartz `CGWindowList` — app names only (titles need Screen Recording) |
| Raise window (`raise_window`) | ✓ extension `RaiseWindow` (#127) | ✗ — not advertised; KWin-side impl is future work ([#133](https://github.com/jonocodes/deckd/issues/133)) | ✗ | ✓ AppKit + Accessibility (AX half needs the grant) |
| Window row → layout match (icon / display name) | ✓ `wm_class` matches the layout token | n/a — no enumeration | n/a | ✗ — `CGWindowList` reports `Firefox`, tokens are `firefox`; matching is case-sensitive |
| Raise app (`raise:`) | ✓ extension `RaiseApp` (#137) | ✗ | ✗ | ✗ |
| MPRIS media (chrome media icon + `nowplaying`) | ✓ session-bus MPRIS | ✓ | ✓ | ✗ — no session bus; the daemon sends `chrome_media.supported = false` and the view says "unsupported on this platform". A MediaRemote-based equivalent is [#56](https://github.com/jonocodes/deckd/issues/56) |
| `media` widget (VLC HTTP backend) | ✓ | ✓ | ✓ | ◑ unverified — plain HTTP to VLC's web interface, no platform-specific path |
| `dbus:` action | ✓ | ✓ | ✓ | ✗ — a Mac has no GNOME/KDE services to call |
| Key injection — printable | ✓ `uinput` (evdev) | ✓ `uinput` | ✓ `uinput` | ✓ `osascript keystroke` |
| Key injection — non-printable / special | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ◑ partial — `osascript key code` map |
| Combo modifiers | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ `using {command down}` |
| Pointer relative motion | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz CG event |
| Mouse click (left/right) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz CG event |
| Mouse drag (held button) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz `LeftMouseDragged` |
| Scroll (jogstrip) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ◑ Quartz scroll-wheel event — drag scrolls, momentum is quantised away ([#143](https://github.com/jonocodes/deckd/issues/143)) |

Legend: ✓ works · ◑ partial · ✗ not available.

## Verification status

A ✓ in the matrix means *the code advertises and implements it*. That is not
the same as *someone watched it work*, and the difference is where the bugs
live (#133 and the GNOME `ListWindows` bug both passed every test). Rows carry
one of three evidence levels:

- **machine-verified** — driven end-to-end against a live daemon and asserted
  programmatically.
- **human-observed** — a human used it on a real desktop and reported what
  they saw. Weaker than machine-verified, stronger than nothing.
- **unverified** — implemented, typechecked, unit-tested; nobody has watched
  it on hardware.

**macOS, last checked 2026-08-06 (macOS 15.6.1, Apple Silicon):**

| row | evidence | note |
|---|---|---|
| Focus detection | machine-verified | `/diag` reports app + title |
| Window enumeration | machine + human | 8 windows over a live `running_windows` frame; human confirms the switcher list renders |
| Raise window | machine-verified | raised Firefox, confirmed focus moved, restored |
| Pointer / drag | machine-verified | exact deltas read back off the cursor; drag lock produced 1 `mousedown`, 5 held moves, 1 `mouseup` in a browser echo page |
| Click (left / right) | machine-verified | `click` / `contextmenu` fired at the exact injected coordinates (#141) |
| Scroll (jogstrip) — drag phase | machine-verified | `scrollTop` moved on the element under the cursor; 120 hi-res units = one detent, symmetric both directions |
| Scroll (jogstrip) — momentum | **broken** ([#143](https://github.com/jonocodes/deckd/issues/143)) | daemon decay runs, but a flick's travel (~66 units) is under one line detent, so nothing reaches the app |
| Key injection (printable / combos / special) | machine-verified | `type` → textarea; `super+t`/`super+w` opened and closed a tab; `super+[`/`super+]` navigated back/forward; Esc, arrows, Enter, F-key, Tab all delivered (#141) |
| Manual control (phone IME round-trip) | **unverified** ([#141](https://github.com/jonocodes/deckd/issues/141)) | the wire-level `type` / `key` paths pass; typing on the phone's own IME still needs a human |
| MPRIS media browser | human-observed **not working**; now says so | no session bus on macOS ([#56](https://github.com/jonocodes/deckd/issues/56) tracks a native replacement). Verified live: the daemon's connect frame is `{"supported": false, …}` |
| `media` widget (VLC HTTP) | **unverified** | nobody has pointed it at a VLC on a Mac |

The Linux columns are code-and-CI truth. No dated hardware run backs them, and
the GNOME rows in particular have a history of passing tests while broken on a
live session — treat them as *unverified* until someone repeats the exercise
above on a GNOME box and dates it here.

## Reading the matrix

**Focus vs. input are two independent axes.** Focus/enumeration/raise depend on
the *compositor* (each needs a different integration: a Shell extension, a KWin
script, `xdotool`, osascript). Input injection depends on the *OS*, not the
compositor: all Linux desktops share the kernel `uinput`/evdev path
(`UinputSink`), so GNOME/KDE/X11 are identical for the whole bottom block;
macOS uses PyObjC Quartz + osascript instead. This is why the testing plan
(`docs/TESTING.md`) calls the input echo-loop (#132) compositor-agnostic while
the enumeration/raise tests (#129–#131) are GNOME-first.

**Absence is a designed empty state, not a crash.** A backend that lacks a
capability simply never produces the corresponding wire frame; the client
surfaces the "unsupported on this platform" empty state (issue #120, decision
8). The daemon gates each optional surface on `capabilities()` — so the honest
move for a backend that can't do something is to *not advertise it*. #133 is a
case where KDE advertises two capabilities it can't fulfil.

## Backend notes

- **GNOME** — richest backend. The `deckd-focus@local` Shell extension owns
  `org.deckd.Focus` and answers `GetActiveWindow` / `ListWindows` /
  `RaiseWindow`. Enumeration + raise are GNOME-only today.
- **KDE Plasma** — `KdeFocusBackend` subclasses the GNOME backend and reuses its
  poll path, but the daemon (not a KDE extension) owns `org.deckd.Focus`; the
  KWin script can only *push* focus in (`UpdateActiveWindow`), so the exported
  interface implements focus only, so `KdeFocusBackend.capabilities()`
  overrides the inherited GNOME set back down to focus-only. Enumeration/raise
  parity is future work
  ([#133](https://github.com/jonocodes/deckd/issues/133) tracks the eventual
  KWin-side implementation that would re-add the flags).
- **X11** — `xdotool`-based focus polling; no enumeration/raise. Input via
  `uinput` like every Linux path.
- **macOS** — `osascript` + System Events focus detection; Quartz supplies
  input (mouse, scroll, held-button drag) and on-screen window enumeration;
  AppKit + Accessibility activate and raise the selected window. osascript
  handles keystrokes (special keys are a partial `key code` map). Window
  numbers are stable for a window's lifetime and are used as opaque ids. No
  D-Bus. A macOS focus-integration test harness would be entirely separate
  from the Linux one.

  **The macOS column is really "✓ *given the TCC grants*".** Permissions are
  attributed to the responsible process — the terminal or launchd agent that
  started the daemon — so the same code is fully working in one process tree
  and silently inert in another. Three independent grants:

  | grant | gates | failure mode without it |
  |---|---|---|
  | Accessibility | Quartz `CGEventPost` (pointer, click, drag, scroll) + the `AXRaise` half of `raise_window` | events **silently dropped**, no error; raise activates the app then fails `kAXErrorAPIDisabled` (-25211) |
  | System Events | focus detection + `osascript keystroke` | osascript exits non-zero; `MacKeySink._check_accessibility` warns at startup |
  | Screen Recording | `kCGWindowName` in `CGWindowList` | every enumerated `title` is `None`; rows label by app name |

  This is why "it doesn't work on my Mac" is usually a *process-tree*
  question, not a code question — verify against the daemon the user
  actually runs (`/diag`, or drive `raise_window` / `pad` over its
  WebSocket), never from a fresh shell in some other app's tree.

  **Enumerated rows don't resolve to layouts.** `CGWindowList` reports the
  owner name (`Firefox`, `Slack`); layout `match` tokens are lowercase
  process names (`firefox`) because the *focus* path gets its identity from
  osascript, which reports the process name. `Layout.matches_identity` is an
  exact `in` comparison, so a row never matches — it falls back to the app
  name with no icon and no `display_name`, while the same app's layout
  switches correctly on focus. Fixing it means either case-insensitive
  identity matching or normalising the owner name in the backend; both change
  cross-platform matching semantics, so it's a decision, not a cleanup.

## Related docs

- `docs/TESTING.md` — testing layers and the desktop-integration plan that would
  automate verification of these rows.
- `daemon/deckd/platform.py` — `capabilities()` and the focus backends.
- `daemon/deckd/platform_macos.py` — the macOS injection sink and its own
  capability docstring.
- `docs/spike-kde-wayland-focus.md` — why KDE inverts to a push model.
