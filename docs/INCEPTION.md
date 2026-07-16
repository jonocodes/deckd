# deckd — Design & Context Document

**Status:** Pre-implementation design. This document captures the full design exploration and all decisions made. It is intended as a complete handoff to an implementation-planning session.

**One-line pitch:** deckd is an application-aware touch control surface for the Linux desktop — a Stream Deck-like deck of buttons, sliders, scroll strips, and a trackpad mode, rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

**Owner context:** Solo personal project. Primary target machine is a NixOS desktop running GNOME on Wayland. Owner is an experienced software developer (Python, Go, infra, NixOS) but a hardware novice. Planning-first, documentation-oriented workflow. macOS support is explicitly deferred but must not be architecturally foreclosed.

---

## 1. Vision and scope

The device/app shows a small grid of touch controls that change based on which application currently has focus on the desktop. Editing in VS Code shows one set of buttons; a browser shows another (including a scroll strip); a DAW might show sliders. Beyond buttons, the surface supports richer input modes: a scroll strip that behaves like a high-resolution mouse wheel, and a trackpad mode that moves the real mouse cursor.

**v1 scope (decided):**

- Client is a **web app** (no custom hardware in v1). Runs fullscreen in a phone/tablet browser, or in a desktop browser tab for development.
- Daemon runs on the Linux desktop, GNOME/Wayland first.
- Widgets: buttons, pages, scroll strip (jog), trackpad mode, a settings page (brightness concept reserved for future hardware; on a phone the OS manages the screen).
- App-aware layout switching driven by focused-window detection.
- Actions: keystroke injection, shell commands, D-Bus calls — all defined in config, never special-cased in code.

**Explicitly deferred:** dedicated LCD hardware (Section 9 preserves that path), macOS backend (Section 10), Windows, any streaming-specific integrations (OBS etc. — those are just config entries).

**Names:** daemon = `deckd`, CLI = `deckctl`. Chosen to match the owner's naming conventions (short, functional, daemon-suffixed; reads well as `deckd.service`).

---

## 2. Architecture

Two components, sharp boundary:

```
┌──────────────────────────┐         WebSocket (JSON)        ┌──────────────────────┐
│  Client (browser, React) │ ◄─────────────────────────────► │  deckd (Python)      │
│  "dumb renderer"         │   layouts down, events up       │  "all the brains"    │
└──────────────────────────┘                                 └──────┬───────────────┘
                                                                    │
                                              ┌─────────────────────┼──────────────────────┐
                                              │                     │                      │
                                        /dev/uinput            D-Bus (session          D-Bus (system
                                        (input injection)      bus: focus,             bus: logind
                                                               screensaver,            PrepareForSleep)
                                                               Night Light, idle)
```

**Core principle — semantics over the wire.** The daemon sends *layout descriptions* ("six buttons with these labels/icons, a scroll strip here"); the client renders them natively and sends back *semantic events* ("button 3 tapped", "jog delta +40", "pad moved dx,dy"). The client never knows what an action does; the daemon never renders pixels. This is what makes the client swappable (phone browser today, dedicated hardware later, another machine's browser tomorrow) and the daemon portable (the OS-touching parts are isolated).

**Core principle — the daemon is app-agnostic.** deckd's core has zero knowledge of any particular application. "Open Spotify", "OBS scene 3", "mute call" are entries in layout config files that fire a generic action (keystroke / shell / D-Bus) — never special-cased Python. This is a deliberate rejection of the feature-creep failure mode observed in WebDeck (community criticism: "contains lots of random logic (bloatware) by default related to OBS, Spotify, your GPU").

**Platform abstraction layer.** All OS-specific behavior lives behind a small interface so macOS later is "one more backend class", not a fork:

```python
class PlatformBackend(Protocol):
    def inject_scroll(self, hi_res_delta: int) -> None: ...
    def inject_pointer(self, dx: int, dy: int) -> None: ...
    def click(self, button: Button, pressed: bool) -> None: ...
    def inject_key(self, keysym_combo: str) -> None: ...
    async def watch_active_app(self) -> AsyncIterator[AppInfo]: ...
    async def watch_power_events(self) -> AsyncIterator[PowerEvent]: ...
```

Everything above this line (protocol, widget logic, layout engine, WebSocket server, policy) is shared, platform-independent code.

---

## 3. Input injection (Linux) — the load-bearing mechanism

This was researched and validated. On GNOME/Wayland, synthetic input **cannot** go through Wayland protocols:

- `zwlr_virtual_pointer_v1` is a wlroots protocol (Sway, Hyprland). **Mutter does not implement it.** GNOME has historically declined external input-injection protocols on security grounds. Dead end on this target.
- X11 tools (`xdotool`) only work in X11 sessions; the target is Wayland.

**The working route is the kernel: `/dev/uinput`.** Create a virtual input device that appears to the system as a real mouse. libinput reads it; the compositor sees genuine input; events go to the window under the pointer; GNOME cannot distinguish it from physical hardware. This is the same mechanism `ydotool` uses, but deckd talks to uinput directly via `python-evdev` for full control over event timing and magnitude (ydotool's granularity is too coarse for smooth finger-tracked scrolling).

**One combined virtual device** carrying all capabilities (do not create separate devices — libinput should treat it as a single coherent mouse so acceleration and focus behave consistently):

```python
from evdev import UInput, ecodes as e

cap = {
    e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_WHEEL_HI_RES],
    e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
}
ui = UInput(cap, name="deckd-virtual-input")
# pointer move:  ui.write(e.EV_REL, e.REL_X, dx); ui.write(e.EV_REL, e.REL_Y, dy); ui.syn()
# hi-res scroll: ui.write(e.EV_REL, e.REL_WHEEL_HI_RES, delta); ui.syn()   # 120 units = 1 notch
```

Keystroke injection for button actions uses the same mechanism with `EV_KEY` keycodes added to capabilities (or a second keyboard-typed uinput device if mixing pointer+keyboard capabilities proves awkward — implementation detail to settle in the spike).

**Permissions.** `/dev/uinput` is root-only by default. Fix with a udev rule and group membership so the daemon runs unprivileged:

```
# /etc/udev/rules.d/99-uinput.rules
KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"
```

On NixOS, express declaratively: `services.udev.extraRules`, `boot.kernelModules = [ "uinput" ]`, add user to `input` group, daemon as a `systemd.user.services` unit. All reproducible across machines.

### 3.1 Scroll design (JogStrip widget)

Decision: **relative scrolling** (mouse-wheel semantics), not absolute scrollbar position. Absolute would require knowing the page's scroll extent, which the OS cannot provide for arbitrary windows (it would need a per-browser extension). Relative works in every app with zero app-specific plumbing.

- Emit `REL_WHEEL_HI_RES` (120 units per notch) so a drag can map finely to finger travel; supplement with `REL_WHEEL` notch events for apps that only listen to the classic axis (emit both, hi-res primary).
- **Momentum/flick:** on finger release, take drag velocity, continue emitting decaying hi-res deltas (friction factor) until below threshold or next touch. Feels like phone scrolling. Lives in the daemon (or client — see 5.3; either works, daemon keeps clients dumber).
- Drag-to-delta mapping and friction are tunables in config.

### 3.2 Trackpad mode

Decision: **relative pointing only** (true touchpad). Absolute (tablet-style) mapping from a small surface to a large monitor is twitchy and was rejected; can be revisited as a separate widget later.

- Per touch-move: `dx = x - last_x`, emit `REL_X/REL_Y` + `syn()` per frame at the touch report cadence. Don't batch or sub-sample (causes stutter).
- **Acceleration:** first version emits raw deltas and lets **libinput** apply the system pointer-acceleration profile (the virtual device looks like a real mouse, so this comes free and matches the rest of the desktop). Only hand-roll a velocity curve in the daemon if the feel is wrong.
- **Gestures (daemon-side logic):**
  - Tap = DOWN/UP within short time + small movement radius → `BTN_LEFT` click.
  - Tap-and-a-half (tap, then touch-and-move) → hold `BTN_LEFT` during move = drag.
  - Two-finger tap → right click (browser client supports multi-touch via Pointer Events; if a future hardware touch controller is unreliable beyond one point, fall back to an on-screen right-click corner).
  - Two-finger vertical drag or edge strip → route into the scroll code.

---

## 4. GNOME integration (D-Bus)

All desktop-state awareness comes over D-Bus, subscribed via `dbus-fast` (async-native; chosen over pydbus specifically to avoid bridging a GLib main loop into asyncio).

| Concern | Interface | Use |
|---|---|---|
| Screen lock / blank | `org.gnome.ScreenSaver` → `ActiveChanged(bool)` (session bus) | Blank/restore client display state; pause momentum |
| Suspend / resume | `org.freedesktop.login1` → `PrepareForSleep(bool)` (system bus) | Explicit blank before sleep (USB/host may stay powered), restore after resume |
| Night Light | `org.gnome.SettingsDaemon.Color` → `NightLightActive`, `Temperature` | Auto-dim policy for future hardware; theming hint for web client (optional dark/dim) |
| Idle | `org.gnome.Mutter.IdleMonitor` | Optional idle dim-then-blank policy (GNOME won't do this for external surfaces) |

Note for the web client: the phone manages its own screen power, so the screensaver/suspend sync mostly translates to UI state (e.g., show a "desktop is locked" screen, suppress input) rather than backlight control. The backlight/brightness (`BL 0-255`) concept is retained in the protocol for the future hardware client (Section 9). Manual brightness is exposed as `deckctl brightness N` and an on-deck settings slider; a GNOME Shell extension for brightness was considered and **rejected** (GJS extension maintenance burden not worth it).

### 4.1 Active-window detection — KNOWN RISK, spike required

This is the app-awareness engine and the least-standardized piece:

- **X11 session:** easy — EWMH `_NET_ACTIVE_WINDOW` + `WM_CLASS` (python-xlib or `xdotool`).
- **GNOME Wayland (the actual target):** there is **no standard Wayland protocol** for a client to query the focused window, by design. Mutter does not expose wlroots' `foreign-toplevel` protocol either. Realistic options, to be evaluated in spike #2:
  1. A small **GNOME Shell extension** that watches `global.display.focus_window` and publishes `{app_id, wm_class, title}` over a session D-Bus name (several community extensions exist as prior art: "Window Calls", "focused-window-dbus"). Most reliable; costs a tiny extension to maintain (ironic given the brightness decision, but here there is no alternative API).
  2. `org.gnome.Shell.Introspect` — exists but is restricted/unstable across GNOME versions; verify current status on the installed GNOME before relying on it.
  3. XWayland fallback — only sees XWayland windows; inadequate alone.
- Check `echo $XDG_SESSION_TYPE` first; support both backends behind `watch_active_app()`.

The daemon matches the reported app identity (`app_id`/`WM_CLASS`) against layout config keys, with a default layout as fallback.

---

## 5. Client (web app)

**Stack: Vite + React + TypeScript.** Vite for instant HMR and no SSR baggage; TypeScript because the WebSocket protocol is a two-process contract and typed message shapes catch drift. Plain CSS / CSS modules — no component library (custom chunky touch UI; MUI/Chakra would fight it). PWA manifest (`display: standalone`) so it runs fullscreen with no browser chrome, installable via Add to Home Screen.

### 5.1 Touch correctness (non-negotiable, validated against known browser traps)

- **Pointer Events only** (`pointerdown/move/up` + `setPointerCapture`). Never rely on `click` (300ms double-tap-zoom delay, no drag semantics).
- `touch-action: none` on all interactive surfaces (stops the browser hijacking drags for page scroll/zoom), `user-select: none`, disable tap highlight.
- Test on more than one mobile browser before trusting it — iOS Safari has its own history of pointer-capture and fullscreen-PWA quirks.

### 5.2 Hot path bypasses React

React owns layout rendering (the grid of widgets). Drags do **not** go through React state: the interactive surface handles pointer events imperatively, computes deltas, throttles to `requestAnimationFrame`, fires WebSocket messages directly, and moves any on-screen handle with a direct style transform. This is what keeps finger-tracking at 60fps; a state-update-per-pointermove would jank.

### 5.3 Rendering feedback

Because the client renders natively, visual feedback (button press states, slider handle following the finger) is local and immediate — no round trip. Only semantic events cross the wire. Momentum can be computed client-side (send decaying deltas) or daemon-side (send release velocity, daemon decays); pick one in implementation — daemon-side keeps clients dumber and consistent across future clients.

### 5.4 Connection lifecycle

Prior-art lesson (WebDeck's most-complained bug is reconnection): build it in from day one. On WebSocket close: show a "reconnecting…" overlay, retry with exponential backoff, re-request current layout on reconnect. Never silently go stale. Daemon side: client connects → daemon immediately pushes the layout for the currently focused app.

---

## 6. Protocol (WebSocket, JSON)

One WebSocket connection per client; the daemon serves both the built static client and the WS endpoint from one aiohttp server/port. JSON is sufficient at pointer-event rates and debuggable in devtools; binary framing only if profiling ever demands it (it won't at this volume). Keep a shared schema: a TS types file and a Python equivalent, kept in sync as the contract.

Message shapes (starting point — implementation may refine):

```jsonc
// daemon → client
{ "type": "layout", "app": "firefox", "page": "main", "widgets": [
    { "id": "b1", "kind": "button", "label": "Mute", "icon": "mic-off", "grid": [0,0,1,1] },
    { "id": "jog", "kind": "jogstrip", "orientation": "vertical", "grid": [3,0,1,3] },
    { "id": "pad", "kind": "trackpad", "grid": [0,1,3,2] }
]}
{ "type": "state", "locked": true }            // desktop locked/suspended → client shows idle screen
{ "type": "brightness", "value": 128 }         // reserved for hardware client

// client → daemon
{ "type": "press",   "id": "b1" }              // button semantics resolved daemon-side
{ "type": "jog",     "id": "jog", "delta": 37 }            // hi-res-ish units, client-throttled to rAF
{ "type": "jog_end", "id": "jog", "velocity": 412 }        // for daemon-side momentum
{ "type": "pad",     "id": "pad", "dx": 3, "dy": -1 }
{ "type": "pad_tap", "id": "pad", "fingers": 1 }
{ "type": "pad_drag","id": "pad", "state": "start" }       // tap-and-a-half drag lock
{ "type": "hello",   "client": "web", "token": "..." }
```

**Security:** a WS server that injects uinput events is remote control of the machine. Bind to localhost/Tailscale interface by default, never `0.0.0.0`; require a shared token in `hello` for anything beyond localhost. QR-code pairing (borrowed from WebDeck's best UX idea): daemon renders a QR encoding `http://<lan-or-tailscale-ip>:<port>/?token=...` — via `deckctl qr` in the terminal (python `qrcode` lib) — so nothing is typed on the phone.

---

## 7. Configuration model

Per-app layout files (YAML or JSON, owner preference — they like markdown/config-driven systems), matched on `app_id`/`WM_CLASS`, plus a `default` layout. Actions are generic primitives only:

```yaml
# layouts/firefox.yaml
match: ["firefox", "org.mozilla.firefox"]
pages:
  main:
    widgets:
      - kind: button
        label: "New tab"
        action: { key: "ctrl+t" }
      - kind: button
        label: "Dev tools"
        action: { key: "F12" }
      - kind: jogstrip
        orientation: vertical      # scrolls whatever is under the pointer
      - kind: button
        label: "Music ⏯"
        action: { shell: "playerctl play-pause" }
      - kind: button
        label: "Cursor mode"
        action: { page: "pad" }
  pad:
    widgets:
      - kind: trackpad
      - kind: button
        label: "back"
        action: { page: "main" }
```

Action primitives: `key` (keystroke via uinput), `shell` (subprocess), `dbus` (method call), `page` (client navigation). Nothing app-specific in the daemon. Pages multiply effective button count (a lesson from small-screen hardware sizing: pages > cramming).

---

## 8. Daemon stack & packaging

- **Python 3.12+, asyncio throughout.** Concurrent event sources (WebSocket clients, D-Bus signals, momentum timers) make async the structural choice.
- **Libraries:** `aiohttp` (HTTP static + WebSocket, one port), `dbus-fast` (async D-Bus), `python-evdev` (uinput), `qrcode` (pairing), `pydantic` or dataclasses for config/message schemas.
- Go was considered (single-binary distribution) and deferred; Python wins on iteration speed for a personal tool, and the owner knows the ecosystem. Revisit only if "ship one static binary" becomes a goal.
- **Packaging:** NixOS module providing the systemd **user** service, udev rule, `uinput` kernel module, `input` group membership. Client ships as Vite `dist/` served by the daemon; dev mode runs Vite's dev server proxying WS to the daemon.
- **CLI:** `deckctl` speaking to the daemon over a local socket — `status`, `qr`, `brightness N`, `reload` (re-read layouts). No GNOME Shell extension, no tray dependency (GNOME has no native tray; systemd + CLI is the GNOME-native shape).

---

## 9. Hardware path (deferred, preserved)

Full exploration summary so the option stays open. The architecture was designed so a hardware client slots in beside the web client without daemon changes above the transport.

**Rejected: e-ink** (Good Display GDEY029T94-FT01, 2.9" 296×128 B&W, touch + frontlight, $12.44). Reasons: 0.3s partial refresh + ghosting + periodic 2s full-refresh flash is wrong for frequent app-switching; monochrome low-res limits icons; e-ink's power advantage is irrelevant on USB power; the raw panel has 0.5mm-pitch FPC connectors a hardware novice cannot hand-solder (would need the adapter-board variant); total landed cost ~$35–40 exceeded the LCD route. E-ink remains defensible only for the aesthetic (no glow, persistent image).

**Rejected: Raspberry Pi Zero as controller.** A USB-tethered display peripheral should be a microcontroller, not a Linux SBC: instant-on (~100ms vs 20–30s boot), no SD-card corruption/OS maintenance, trivial USB CDC enumeration vs gadget-mode fiddling, lower power. A Pi only makes sense for a standalone Wi-Fi device, which this isn't.

**Selected (if/when built): Waveshare ESP32-S3-Touch-LCD-2** (~$18–22, Amazon ASIN B0DTTL56ZR). 2" 240×320 IPS, capacitive touch (CST816D, I2C), ST7789T3 display (SPI), ESP32-S3R8, USB-C with native USB (clean CDC serial, no CH340 driver), PWM-controllable backlight, good Waveshare wiki/demos. Runner-ups documented: classic CYD ESP32-2432S028R (~$8–15, resistive touch, huge community — witnessmenow/ESP32-Cheap-Yellow-Display repo); JC2432W328C (2.8" capacitive CYD-clone, ~$15 with case, expect pin-definition tweaks vs tutorials); Waveshare 1.69" (tiny; only 4–6 comfortable buttons). Touch-target math: comfortable buttons ≈14mm; 2.8" fits 8, 2" fits ~6, 1.69" fits 4. Pages compensate for smaller screens. Mounting idea: the flat valley between a Kinesis Advantage's key wells (3M VHB tape or a printed bracket, not permanent glue).

**Hardware client architecture (dumb terminal):** PC daemon renders the layout to a framebuffer (Pillow) — 240×320×16-bit ≈ 150KB full frame; use partial dirty-rect updates for smooth slider/drag feedback — shipped over USB CDC serial; firmware blits via SPI and reports touch DOWN/MOVE/UP with coordinates; `BL <0-255>` command drives backlight PWM; firmware boots into "backlight off, wait for host" so a rebooting board never strobes before the daemon reconnects. Firmware never changes when layouts change. Power draw ~100–180mA from USB — irrelevant against the 500mA USB 2.0 budget. E-ink comparison for the record: panel refresh 9mW / frontlight ≤60mA / total 30–110mA, but the tradeoffs above rule it out.

**Android-phone-as-device (explored, superseded by web app):** ADB TCP port forwarding is the pragmatic USB transport (`adb forward`, plain sockets, sub-ms latency); AOA (USB Accessory mode) is the "proper" peripheral protocol via libusb; both became moot once the client went browser-based — a phone browser over LAN/Tailscale (or an ADB-forwarded port) achieves the same with no native app to build.

---

## 10. macOS path (deferred, architecturally reserved)

Only the platform backend changes; protocol, client, widgets, layouts all carry over.

- **Injection:** Quartz Event Services — `CGEventCreateMouseEvent` / `CGEventCreateScrollWheelEvent` + `CGEventPost`, reachable from Python via PyObjC. Requires one-time **Accessibility** (and possibly Input Monitoring) grants in System Settings; unsigned rebuilds can silently invalidate the grant (known PyObjC annoyance; a Swift helper is the eventual clean fix, not needed now).
- **Focus:** `NSWorkspace.frontmostApplication` + change notifications (simpler than Linux — no X11/Wayland split).
- **Power:** NSWorkspace sleep/wake notifications (or IOKit).
- Windows, if ever: `SendInput` + `GetForegroundWindow`, third backend behind the same interface.

---

## 11. Prior art and positioning

Researched July 2026. Three clusters:

1. **Elgato-hardware ecosystem** (Stream Deck + Linux drivers like DeUX, OpenDeck): assumes purchased hardware; irrelevant as a platform, but **OpenDeck's button/plugin editor UI is flagged as a future reference** for deckd's layout editor (drag-to-arrange grid, icon picker, per-button action forms — look before building, don't reinvent badly).
2. **Software remote decks** (WebDeck, Macro Deck, Touch Portal, Stream-Pi, ODeck): closest neighbors. **WebDeck** is the nearest match (browser-based, self-hosted, Flask + Flask-SocketIO) and is **Windows-only with Linux explicitly deferred by its maintainer** — the exact gap deckd fills. Lessons adopted: QR pairing (great UX, adopt); reconnection is the chronic complaint (design for it from day one); integration bloat is the failure mode (rejected via the app-agnostic-core principle).
3. **DIY hardware decks** (FreeTouchDeck on ESP32/CYD — standalone Bluetooth HID keyboard, self-hosted web configurator on-device, but no host daemon and no app-awareness; Starkpad — open-source touchscreen deck with virtual keyboard/touchpad modes, good hardware reference).

**KDE Connect / GSConnect** was evaluated and rejected as a foundation: its remote-input is a closed fixed feature, not a programmable surface; extending it means writing a plugin inside a GNOME Shell extension (fragile, wrong layer). Use it as a working reference for pairing/reconnection design, and as an interim phone-trackpad during development.

**deckd's genuine differentiators (validated as underserved):**
(a) focus-driven automatic layout switching from OS window-focus tracking — existing tools use manual profile paging or streaming-software triggers, not general desktop focus;
(b) uinput-level relative scroll and trackpad injection — existing tools live at the send-a-hotkey abstraction;
(c) Linux/GNOME/Wayland-first, where the leading browser-based alternative doesn't run at all.

---

## 12. Implementation plan

**De-risking spikes first (in order):**

1. **uinput scroll end-to-end.** Hardcoded single jog strip in a bare HTML page → WebSocket → daemon → `REL_WHEEL_HI_RES`. Prove the *feel* (smoothness, momentum) before building any widget system. Includes the udev/NixOS permission setup.
2. **Focus watcher.** Resolve the GNOME-Wayland active-window question (Section 4.1): evaluate Shell-extension-over-D-Bus vs Introspect on the installed GNOME version; print focused `app_id` changes to stdout. This is the highest-uncertainty item in the whole design.

**Then milestones:**

3. Daemon skeleton: asyncio core, aiohttp WS + static serving, config loader, platform-backend interface with the Linux implementation wrapping spike code.
4. Client skeleton: Vite/React/TS, layout renderer for `button` + `jogstrip`, pointer-event hot path, reconnect overlay, PWA manifest.
5. Layout switching: wire focus watcher → layout push; per-app YAML configs; `key`/`shell`/`page` actions.
6. Trackpad widget: relative deltas, tap/drag-lock/two-finger gestures, libinput acceleration.
7. Lifecycle polish: screensaver/suspend D-Bus sync, QR pairing, token auth, `deckctl`, NixOS module.
8. Later: layout-editor UI (reference OpenDeck), Night-Light-aware theming, momentum tuning, macOS backend, optional ESP32 hardware client speaking a serial variant of the protocol.

**Open questions for implementation planning:**

- GNOME Wayland focus API choice (spike #2) — the one real unknown in the design.
- Momentum: client-side vs daemon-side (leaning daemon-side).
- Keystroke injection details: same uinput device as pointer or a second keyboard device; and keymap handling — evdev keycodes are layout-independent, so decide how `ctrl+t` in config maps under non-US keyboard layouts.
- Config format final call (YAML vs JSON) and schema validation approach.
- iOS Safari PWA behavior verification (pointer capture, standalone mode, Add to Home Screen).
