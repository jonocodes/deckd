# deckd

An app-aware touch control surface for the Linux desktop. A daemon watches the focused application and pushes layouts to a browser-based client that renders touch controls and sends back semantic events.

## Language

### UI structure

**Layout**:
The per-app configuration of what to show on the client surface. A layout has a list of widgets. Defined in a YAML file matched by app identity; one layout is the default fallback.
_Avoid_: profile, config, scene

**Widget**:
A single interactive element placed on a page. Current kinds: `button`, `jogstrip`, `trackpad`.
_Avoid_: control, element, tile

**Grid placement**:
The `[x, y, w, h]` coordinates that position a widget within a page's grid. Columns and rows are defined by the layout; coordinates are zero-based.
_Avoid_: position, slot, cell

**Chrome**:
The persistent UI shell that surrounds every layout. Consists of a bottom strip (app badge, connection indicator, manual control mode button, settings button) and a right-side jogstrip. Chrome is always visible; layouts render in the remaining space. The right-side jogstrip can be disabled per-layout with `jogstrip: false`. The bottom strip's app badge optionally carries a `display_name`, a `theme` colour, and an `icon` (ADR-0007) the daemon relays opaquely from the active layout.
_Avoid_: global bar, status bar, toolbar

**App badge**:
The branded app-identity pill in the bottom chrome: optional icon + human-readable display name, optionally tinted by a theme colour. Built from the layout's `display_name` / `theme` / `icon` top-level fields, relayed verbatim by the daemon (ADR-0007). Falls back to the raw match token (`app`) and an un-tinted pill when the layout omits them.
_Avoid_: app label, app indicator, brand strip

**Manual control mode**:
A global chrome mode that replaces the layout area with a single combined surface — a trackpad for cursor movement plus a keyboard passthrough for typing into the currently-focused desktop app via the phone's own IME. Both live at the same time: dragging on the trackpad moves the cursor while the IME is open, and tapping the strip's keyboard-icon toggle raises/dismisses the soft keyboard. The strip at the top of the surface also hosts the few keys mobile IMEs can't produce (Esc, Tab, arrows). Literal glyphs travel as `type` messages, named keys as `key` messages. Injection is ASCII-only under a US-layout assumption, lands on whatever window holds desktop focus, and the daemon drops it while its own client window is focused (feedback-loop guard). Not app-specific; the daemon-side guard makes the mode safe on a desktop browser (where typing would otherwise self-loop).
_Avoid_: cursor mode, mouse mode, virtual keyboard, on-screen keyboard, IME forwarding

### Widget kinds

**Button**:
A widget that fires a single action on tap.

**JogStrip**:
A widget for high-resolution relative scroll input. The user drags a finger; the daemon emits `REL_WHEEL_HI_RES` deltas via uinput. Release with velocity triggers momentum (daemon-side decay).
_Avoid_: scroll strip, slider

**Trackpad**:
A widget for relative pointer movement. Finger movement maps to `REL_X`/`REL_Y` deltas. Supports tap (left click), two-finger tap (right click), and tap-and-a-half drag lock.
_Avoid_: touchpad, pad widget

### Actions

**Action**:
What the daemon does when a widget is activated. Primitives: `key` (uinput keystroke), `shell` (subprocess), `dbus` (D-Bus method call). Nothing app-specific is ever hard-coded; all behavior lives in config.
_Avoid_: command, handler, binding

### App identity

**AppInfo**:
The identity of the currently focused application as reported by the platform backend: `app_id` (Wayland-native), `wm_class` (XWayland), `title`, `pid`. Used to select the matching layout.
_Avoid_: window info, focus info, app context

**Match**:
The list of `app_id` / `wm_class` strings in a layout's YAML that determine which focused app activates that layout. The daemon falls back to the `default` layout when no match is found.
_Avoid_: trigger, selector, rule

### System boundary

**Platform backend**:
The OS-specific implementation of input injection (`inject_scroll`, `inject_pointer`, `click`, `inject_key`) and focus watching (`watch_active_app`). Isolated behind a protocol so macOS or other platforms slot in without touching the rest of the daemon.
_Avoid_: OS adapter, backend driver

**Client**:
Any process that connects to the daemon over WebSocket and renders a layout. Currently: the web app (phone/tablet browser). Future: ESP32 hardware client. The daemon is agnostic to which client type is connected.
_Avoid_: frontend, app, device
