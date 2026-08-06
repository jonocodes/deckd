# Platform feature parity

deckd runs one daemon against several desktop platforms, each with a different
focus/enumeration mechanism and input-injection path. This doc is the single
reconciled view of **what works where** — the source of truth is the code
(`PlatformBackend.capabilities()` in `daemon/deckd/platform.py` and the
injection sinks in `daemon/deckd/input.py` / `daemon/deckd/platform_macos.py`);
this table exists to make drift between backends visible at a glance.

> Keep this in sync when a backend gains or loses a capability. If a row here
> disagrees with `capabilities()`, the code wins — and that disagreement is a
> bug (it's how #133 was found).

## Capability matrix

| Capability | GNOME (Wayland/X11) | KDE Plasma (Wayland) | X11 (generic) | macOS |
|---|---|---|---|---|
| Focus detection (`watch_active_app`) | ✓ GNOME Shell extension over `org.deckd.Focus` | ✓ KWin script pushes into daemon-owned cache (#31) | ✓ `xdotool` poll | ✓ `osascript` + System Events |
| Window enumeration (`watch_windows`) | ✓ extension `ListWindows` | ✗ — **advertised but unimplemented, see [#133](https://github.com/jonocodes/deckd/issues/133)** | ✗ | ✓ Quartz `CGWindowList` |
| Raise window (`raise_window`) | ✓ extension `RaiseWindow` (#127) | ✗ — **advertised but unimplemented, see [#133](https://github.com/jonocodes/deckd/issues/133)** | ✗ | ✓ AppKit + Accessibility |
| Raise app (`raise:`) | ✓ extension `RaiseApp` (#137) | ✗ | ✗ | ✗ |
| Key injection — printable | ✓ `uinput` (evdev) | ✓ `uinput` | ✓ `uinput` | ✓ `osascript keystroke` |
| Key injection — non-printable / special | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ◑ partial — `osascript key code` map |
| Combo modifiers | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ `using {command down}` |
| Pointer relative motion | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz CG event |
| Mouse click (left/right) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz CG event |
| Mouse drag (held button) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz `LeftMouseDragged` |
| Scroll (jogstrip) | ✓ `uinput` | ✓ `uinput` | ✓ `uinput` | ✓ Quartz scroll-wheel event |

Legend: ✓ works · ◑ partial · ✗ not available.

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
  interface implements focus only. Enumeration/raise parity is future work
  ([#133](https://github.com/jonocodes/deckd/issues/133) tracks both the honest
  capability advertisement and the eventual KWin-side implementation).
- **X11** — `xdotool`-based focus polling; no enumeration/raise. Input via
  `uinput` like every Linux path.
- **macOS** — `osascript` + System Events focus detection; Quartz supplies
  input (mouse, scroll, held-button drag) and on-screen window enumeration;
  AppKit + Accessibility activate and raise the selected window. osascript
  handles keystrokes (special keys are a partial `key code` map). Window
  numbers are stable for a window's lifetime and are used as opaque ids. No
  D-Bus. A macOS focus-integration test harness would be entirely separate
  from the Linux one.

## Related docs

- `docs/TESTING.md` — testing layers and the desktop-integration plan that would
  automate verification of these rows.
- `daemon/deckd/platform.py` — `capabilities()` and the focus backends.
- `daemon/deckd/platform_macos.py` — the macOS injection sink and its own
  capability docstring.
- `docs/spike-kde-wayland-focus.md` — why KDE inverts to a push model.
