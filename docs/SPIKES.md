# deckd — Spike Progress & Implementation Plan

Tracks the de-risking work in `docs/INCEPTION.md` §12. Source of truth for *where we are* and *what's next*. INCEPTION.md stays the source of truth for *what* and *why*.

Owner context: solo project, planning-first workflow. Spikes come first because they're the load-bearing pieces; milestones build on top once spikes resolve.

---

## Spike #1 — uinput scroll end-to-end (issue #1)

**Status:** core path validated; deferred follow-ups remain for reboot/clean-machine install validation and final feel defaults.

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
  - Added udev rule artifact at `packaging/udev/70-deckd-uinput.rules`.
  - Added NixOS spike module at `packaging/nixos/deckd-spike.nix` for uinput, `input` group membership, and a user service.
  - Added tuning knobs: phone URL `scrollScale` / `scrollInvert`, daemon `--scroll-momentum-friction` / `--scroll-momentum-cutoff`, and helper-script `--velocity`.
  - Added `just check-uinput` diagnostic for pre/post-reboot permission validation.

### Deferred follow-ups
- Need empirical tune pass to choose final direction, scale, friction, and cutoff defaults.
- Need post-reboot `just check-uinput` pass on this machine.
- Need NixOS module evaluation on a clean machine.

---

## Spike #2 — GNOME-Wayland active-window detection (issue #2)

**Status:** done (X11 unsupported).

**Goal:** resolve the highest-uncertainty design question (INCEPTION.md §4.1) and ship a working `PlatformBackend.watch_active_app()`.

### Decision
- Chose (a): tiny GNOME Shell extension over session D-Bus.
- X11 fallback exists in daemon code but is not a supported target; no testing or ongoing maintenance planned for X11.
- (b) `org.gnome.Shell.Introspect` was ruled out — returns `AccessDenied` on this machine.

### Scope
- Tiny GNOME Shell extension over session D-Bus.
- `PlatformBackend.watch_active_app() -> AsyncIterator[AppInfo]` over the GNOME/Wayland split (`echo $XDG_SESSION_TYPE`).
- Daemon side: stub that prints focused `app_id` / `WM_CLASS` changes to stdout. No layout switching yet — just prove we can see focus changes.

### Definition of done
- [x] Focused-window changes printed within ~200ms of alt-tab.
- [x] Both `app_id` (Wayland-native) and `WM_CLASS` (XWayland) appear correctly.
- [x] Behavior documented for the GNOME version this machine runs (Shell 50.1).
- [ ] ~~X11 fallback~~ — unsupported.

### Progress
- **2026-07-15** — Spike #2 kickoff:
  - Environment observed: GNOME Shell 50.1 on Wayland (`XDG_SESSION_TYPE=wayland`, `XDG_CURRENT_DESKTOP=GNOME`).
  - `org.gnome.Shell.Introspect` is present, but `GetWindows` and `GetRunningApplications` return `AccessDenied`; this rules it out as the primary path on this machine.
  - Added GNOME Shell extension scaffold at `packaging/gnome-shell/deckd-focus@local` exposing focused window JSON over session D-Bus (`org.deckd.Focus`).
  - Added daemon-side `PlatformBackend`, `GnomeShellFocusBackend`, and X11 `xdotool` fallback in `daemon/deckd/platform.py`.
  - Added `scripts/watch_focus.py` / `just watch-focus` for validation.
  - Extension bundle packs successfully with `gnome-extensions pack`; `just watch-focus` reports a helpful install hint when `org.deckd.Focus` is not loaded.
  - `just install-focus-extension` installs the bundle; GNOME Shell on Wayland does not list the new extension until relogin, so enabling may be a second step after logging back in.
  - Fixed GNOME Shell 50.1 GJS binding issue: `Gio.bus_own_name` requires the sixth `name_lost` callback argument, even when it is `null`.
- **2026-07-16** — Verification:
  - Extension installed, enabled, and ACTIVE on GNOME Shell 50.1.
  - `gdbus call org.deckd.Focus.GetActiveWindow` returns correct `app_id`, `wm_class`, `title`, `pid`.
  - `just watch-focus` polls at 100ms and prints focus changes on alt-tab.
  - Native Wayland apps report `app_id`; XWayland apps report `wm_class`.

---

## Implementation Plan

_To be drafted after spike #1 and spike #2 resolve. The plan will consume their outputs and lay out milestones 3–7 (daemon skeleton, client polish, trackpad widget, lifecycle)._

---

## Notes / decisions log

- **2026-07-15** — Spike scaffolding landed. Two commits on `main`:
  - `d563827` Spike: daemon + client wire protocol with action dispatch.
  - `ad95ed2` Add dev supervisor: auto-reload on YAML, auto-restart on Python.
  Issue #3 (daemon skeleton), #4 (trackpad), #5 (lifecycle) opened for after-spike work.