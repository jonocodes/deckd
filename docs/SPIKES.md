# deckd — Spike Progress & Implementation Plan

Tracks the de-risking work in `docs/INCEPTION.md` §12. Source of truth for *where we are* and *what's next*. INCEPTION.md stays the source of truth for *what* and *why*.

Owner context: solo project, planning-first workflow. Spikes come first because they're the load-bearing pieces; milestones build on top once spikes resolve.

---

## Spike #1 — uinput scroll end-to-end (issue #1)

**Goal:** prove the *feel* of synthetic scroll injection on GNOME/Wayland *before* building any widget system. Per INCEPTION.md §3 and §3.1.

### Scope
- Single hardcoded jogstrip widget in a bare HTML page (no React, no Vite, no layout system).
- WebSocket client to a minimal daemon that emits `REL_WHEEL_HI_RES` via python-evdev.
- Finger-travel → delta mapping; client-throttled to `requestAnimationFrame`; daemon logs emitted values.
- Udev rule + `input` group membership so the daemon runs unprivileged.

### Definition of done
- [ ] Dragging a finger on the bare HTML strip produces smooth, sub-notch scroll in arbitrary apps under the cursor.
- [ ] Momentum/flick works: release with velocity → decaying delta continued until below threshold or next touch.
- [ ] Udev rule survives reboot.
- [ ] NixOS expression (udev + group + user-service unit) reproducible on a clean machine.

### Progress
- **2026-07-15** — Spike #1 kickoff:
  - Added browser `jogstrip` rendering for the hardcoded `Scroll` strip in `layouts/default.yaml`.
  - Added `jog` / `jog_end` dispatch in the daemon.
  - Added daemon-side scroll sink abstraction: uinput via `python-evdev` when available, log-only fallback otherwise.
  - Added daemon-side flick momentum from release velocity.
  - Added smoke coverage for the jog message path with a fake scroll sink.
  - Manual same-machine uinput test works with `sleep 2 && .venv/bin/python -u scripts/send_scroll.py`, using the delay to move the pointer over the target scroll area before events fire.
  - Added LAN testing path: `just build-client`, `just run-daemon-lan`, then open `http://<desktop-lan-ip>:8765` from the phone. The built client uses `window.location.host` for WebSocket reconnect.
  - Added Vite LAN testing path: `just run-daemon-dev-lan` plus `just dev-client-lan`, then open `http://lute:5173` or Vite's printed Network URL from the phone. Vite binds to `0.0.0.0`; `VITE_DECKD_WS` points back to the daemon on port 8765.
  - Phone-to-desktop validation succeeded: dragging the jogstrip in the phone browser scrolls desktop apps via uinput.

### Current gaps
- Need tune pass for direction, scale, and momentum feel.
- Need udev rule + group membership check across reboot.
- Need NixOS expression for udev + group + user service.

---

## Spike #2 — GNOME-Wayland active-window detection (issue #2)

**Goal:** resolve the highest-uncertainty design question (INCEPTION.md §4.1) and ship a working `PlatformBackend.watch_active_app()`.

### Scope
- Choose between (a) tiny GNOME Shell extension over session D-Bus, (b) `org.gnome.Shell.Introspect`, (c) XWayland fallback. Pick whichever works on the installed GNOME version.
- Implement the chosen path. (a) is the realistic choice per the design doc.
- `PlatformBackend.watch_active_app() -> AsyncIterator[AppInfo]` over the GNOME/XWayland split (`echo $XDG_SESSION_TYPE`).
- Daemon side: stub that prints focused `app_id` / `WM_CLASS` changes to stdout. No layout switching yet — just prove we can see focus changes.

### Definition of done
- [ ] Focused-window changes printed within ~200ms of alt-tab.
- [ ] Both `app_id` (Wayland-native) and `WM_CLASS` (XWayland) appear correctly.
- [ ] Behavior documented for the GNOME version this machine runs.
- [ ] X11 fallback (`xdotool getactivewindow getwindowclass`) works behind the same interface.

### Progress
_(none yet — pending kickoff)_

---

## Implementation Plan

_To be drafted after spike #1 and spike #2 resolve. The plan will consume their outputs and lay out milestones 3–7 (daemon skeleton, client polish, trackpad widget, lifecycle)._

---

## Notes / decisions log

- **2026-07-15** — Spike scaffolding landed. Two commits on `main`:
  - `d563827` Spike: daemon + client wire protocol with action dispatch.
  - `ad95ed2` Add dev supervisor: auto-reload on YAML, auto-restart on Python.
  Issue #3 (daemon skeleton), #4 (trackpad), #5 (lifecycle) opened for after-spike work.