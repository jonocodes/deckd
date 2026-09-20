# deckd

App-aware touch control surface for your desktop. A Stream Deck-like deck of buttons, sliders, scroll strips, and a manual control mode (a single combined trackpad + keyboard passthrough), rendered in any browser on any touchscreen device, driven by a local daemon that watches the focused application and swaps layouts automatically.

## Uses

- Control your desktop from your phone, or tablet, or laptop
- Control multiple computers from one surface
- Control slides/presentations
- Get custom controls for each app you are using — including **websites**: play/pause and skip on YouTube or Netflix, or turn a site into an on-screen piano (see [Web-app layouts](docs/GUIDE.md#web-app-layouts); title-based, so best-effort today)
- Automatically switch display depending on which app is active
- Expose hotkeys for launching apps, or keyboard shortcuts
- Use phone as a mouse, scrollbar, and keyboard controller
- Voice typing from your phone to desktop


## Screenshots


### Home launcher

![home launcher](docs/screenshot-home.png)

### Portrait phone view

![home portrait](docs/screenshot-portrait.png)

### Firefox

![firefox mode](docs/screenshot-firefox.png)

### Trackpad/keyboard

![trackpad/keyboard](docs/screenshot-trackpad.png)

## Status

Pre-alpha, but usable day-to-day. Here's what deckd can do today and what's still planned.

**Working today**

- [x] **Automatic per-app layouts** — focus a window on the desktop and the phone's browser flips to that app's buttons automatically.
- [x] **Web-app layouts** — treat a website as an app. A layout can claim a site by matching the browser's window title (e.g. YouTube and Netflix media controls), driving each site's own keyboard shortcuts. See [Web-app layouts](docs/GUIDE.md#web-app-layouts).
- [x] **Buttons** that fire keystrokes, shell commands, launch a terminal, or call D-Bus methods.
- [x] **Macros** — chain multiple actions in a single button press, with delays and optional continue-on-error.
- [x] **Button styling** — bundled icons (Lucide glyphs + Simple Icons brand logos) and per-button background colours, set in YAML.
- [x] **Scroll strip** — an always-on right-side jogstrip to scroll the focused window, with release momentum.
- [x] **Manual control mode** — the phone becomes a trackpad (move, tap, right-click, drag-lock) and a keyboard, so you can type into and point at the focused app for the things layouts don't cover (URL bars, chat boxes, ad-hoc commands).
- [x] **App badge** — the focused app's name, icon, and accent color show in the bottom bar so you can tell at a glance what you're controlling.
- [x] **Chrome media indicator** — the media icon sprouts a pulsing green dot whenever a media player is playing (passive playback indicator), independent of the browser view.
- [x] **Now playing** — control any supported media player (Spotify, Firefox, VLC, etc.) from a dedicated chrome view, with album art, per-player transport controls, and now-playing metadata.
- [x] **Running programs list** — tap a layout-grid icon in the bottom chrome to open a list of every open window on the host, labeled by the layout the window would match. Tap a row to raise (focus) that window and close the list. Enumeration and raise are GNOME-only today (via the focus extension); other backends show the list's "unsupported on this platform" empty state.
- [x] **VLC media widgets** — full VLC control surface with play/pause, seek, volume, album art. Configurable art sources (VLC embedded art + iTunes fallback).
- [x] **Live sensor widgets** — meter and stats widgets pushed to the client in real time (CPU %, memory %, etc.), bound to daemon-side sensor sources.
- [x] **GUI layout editor** — build and edit layouts from the browser without hand-editing YAML: a widget palette, a drag-to-reorder reflow canvas with span and overflow controls, a properties panel (labels, icons via a searchable picker, colours, actions and macros), and new-layout creation — saved back to disk over the write API. In development, but usable today. See [Layout editor](docs/GUIDE.md#layout-editor).
- [x] **Live layout editing** — edit a layout file on the desktop (by hand or via the GUI editor) and every connected phone/tablet re-renders instantly; a bad edit shows an error in place instead of crashing.
- [x] **Per-device tuning** — a settings panel for scroll speed/direction, trackpad sensitivity, content and text size, bar sizes, and keep-screen-awake, all saved on the device.
- [x] **Addressable client views** — the layout, manual control, now playing, settings, editor, and running-windows views have their own URL paths for deep links and browser history.
- [x] **Keep screen awake** while the surface is in use.
- [x] **Install to home screen** (PWA) for a fullscreen, app-like surface.
- [x] **Password auth** — every client authenticates with a shared password (on by default; `--no-auth` disables it for local development). See [Client auth](docs/GUIDE.md#client-auth).
- [x] **LAN scope control** — bind the daemon to a specific network interface (`--bind iface:wlan0`) or literal address; defaults to localhost-only for safety.
- [x] **Accessibility** — keyboard navigation, visible focus ring, screen-reader landmarks and live announcements, larger controls, high contrast, and reduced motion.
- [x] **Runs on Linux: GNOME (Wayland), KDE Plasma (Wayland), X11**
- [x] **Runs on MacOS (barely tested)**
- [x] **Nix flake** — `nix run` for a trial, plus NixOS and home-manager modules that install the daemon as a session service in one import and wire up the GNOME Shell extension or KWin script. See [Nix flake, NixOS, and home-manager](docs/GUIDE.md#nix-flake-nixos-and-home-manager).

**Planned**

- [ ] **Screensaver & suspend sync** — dim/lock the surface when the desktop sleeps.
- [ ] **Multiple simultaneous clients** with per-device layouts and resolutions.
- [ ] **Soundboard** — trigger sound clips from the deck.
- [ ] **Multi-daemon chooser** — pair and pick between several desktops.
- [ ] **Reliable web-app detection** — a browser extension reporting the active tab's real URL, so sites match by domain/path instead of the current window-title heuristic ([#90](https://github.com/jonocodes/deckd/issues/90)).
- [ ] **Windows support**
- [ ] **Packing and deployment**

## Inspiration and Comparison

The original inspiration was the Stream Deck, and I like all these projects. I wanted something that could do more, have open ended controls, and work across platforms.


| Feature | [deckd](https://github.com/jonocodes/deckd/issues) | [Stream Deck](https://www.elgato.com/us/en/s/explore-stream-deck)* | [KDE Connect](https://kdeconnect.kde.org/) | [Apple Touch Bar](https://support.apple.com/guide/mac-help/use-the-touch-bar-mchlbfd5b039/mac) | [Remote Touchpad](https://github.com/Unrud/remote-touchpad) |
|---|---|---|---|---|---|
| Controller agnostic | ✅ | ❌ | ✅ | ❌ | ✅ |
| Cross platform | ✅ | ✅ | ✅ | ❌ | ✅ |
| Connection | Browser (WiFi) | USB | WiFi | Built-in | WiFi |
| Custom layouts | ✅ | ✅ | ❌ | 🟡 | ❌ |
| Custom layouts for web apps* | ✅ | ❌ | ❌| ❌ |❌ |
| Open source | ✅ | 🟡† | ✅ | ❌ | ✅ |
| Browser-based client | ✅ | ❌ | ❌ | ❌ | ✅ |
| Keyboard command triggering | ✅ | ✅ | 🟡 | 🟡 | ❌ |
| Global media control | ✅ | ✅ | ✅ | ✅ | ❌ |
| Mouse/touchpad control | ✅ | ❌ | ✅ | ❌ | ✅ |

\*Make layouts for any website with keyboard controls. Examples: YouTube, Google Meet, Twitch

†[OpenDeck](https://github.com/nekename/OpenDeck#showcase), and [Boatswain](https://flathub.org/en/apps/com.feaneron.Boatswain) are open source; Elgato's SDK is not

## Architecture

```
                        ┌──────────┐
                        │  Phone / │
                        │  Tablet  │
                        │  Browser │
                        └────┬─────┘
                             │
                      WebSocket (ws://)
                             │
          ┌──────────────────┼───────────────────┐
          │             deckd daemon             │
          │            (aiohttp, asyncio)        │
          │                                      │
          │  ┌──────────┐  ┌──────────┐          │
          │  │  Layout  │  │  Action  │          │
          │  │  Loader  │  │ Dispatch │          │
          │  └──────────┘  └────┬─────┘          │
          │         │           │                │
          └─────────┼───────────┼────────────────┘
                    │           │
        layouts/*.yaml    ┌─────┴─────┬──────────┐
                          │           │          │
                      uinput       shell     D-Bus
                     (evdev)     (subprocess)  gdbus
                          │                    │
              scroll + keys + pointer  ┌───────┴───────┐
                          │            │               │
                     /dev/uinput   GNOME Shell     (xdotool —
                                   Extension        any X11 DE)
                                  deckd-focus
                                   @local

                            ┌──────────────────┐
                            │  Focus watchers  │
                            └──────────────────┘
                              GNOME Shell ext.   (Wayland, GNOME)
                              KWin script        (Wayland, KDE Plasma)
                              xdotool           (any X11 session)
                              osascript          (macOS)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the component breakdown and key flows.

## Getting started

deckd needs Python 3.11+ and Node 18+. CI tests the 3.11 floor and the 3.12 interpreter the Nix package ships. In brief:

```sh
uv venv --python 3.12
uv pip install -e ".[dev,uinput,dbus]"
cd client && npm install && cd ..
just build-client
just run-daemon        # serves the client at http://127.0.0.1:8765
```

Then open `http://127.0.0.1:8765` in any browser. The full install story —
per-platform setup (macOS, KDE Plasma Wayland, X11), phone/tablet pairing,
`/dev/uinput` permissions, and running deckd as a login service — is in the
[user & setup guide](docs/GUIDE.md#running-deckd).

### Nix

The flake at the repo root builds the daemon and the client, and ships
modules for both halves of a NixOS install. It needs flakes enabled
(`experimental-features = nix-command flakes`).

**Try it without installing anything.** `nix run` serves the bundled
client and layouts on `http://127.0.0.1:8765`; auth is on, and the
password is generated at `~/.config/deckd/password`:

```sh
nix run github:jonocodes/deckd
nix run github:jonocodes/deckd -- --bind 0.0.0.0   # reachable from a phone
nix run . -- --bind 0.0.0.0                        # from a local checkout
```

**NixOS + home-manager.** Add the input, import the system module and
the home-manager module for your desktop, then rebuild:

```nix
# flake.nix (your own config)
inputs.deckd.url = "github:jonocodes/deckd";

# configuration.nix
imports = [ inputs.deckd.nixosModules.deckd ];
services.deckd = {
  enable = true;
  openFirewall = true;        # only needed when binding beyond localhost
  users = [ "jono" ];         # optional: add to the `input` group
};

# home.nix
imports = [ inputs.deckd.homeModules.deckd-gnome ];  # or homeModules.deckd-kde
services.deckd = {
  enable = true;
  bind = [ "0.0.0.0" ];       # default is localhost-only
};
```

```sh
sudo nixos-rebuild switch --flake .
```

Relogin after the first switch: the GNOME extension appears once the
Shell restarts; the KWin script is hot-started when Plasma is running.
`nix flake update deckd` moves your config to newer commits.

The home-manager module owns:

- `deckd` as a **user** service (`WantedBy=graphical-session.target`) —
  starts with your desktop session, restarts on failure;
- `~/.config/deckd/layouts`, seeded once from the package; your edits
  are never overwritten (`seedLayouts = false` opts out);
- `~/.config/deckd/password` (generated on first start) — point
  `passwordFile` at a secret to manage it yourself.

**Home-manager standalone** (no NixOS module, e.g. Nix on another
distro) uses the same import; the udev rule and `input` group for
`/dev/uinput` are then yours to install (see
[uinput permissions](docs/GUIDE.md#uinput-permissions)):

```nix
{
  imports = [ inputs.deckd.homeModules.deckd-gnome ];
  services.deckd.enable = true;
}
```

**Without flakes:** `nix profile install github:jonocodes/deckd` (or
`nix build github:jonocodes/deckd` and run `./result/bin/deckd`), then
start it yourself; the classic recipes (`just install-service`,
`just install-focus-extension` / `install-focus-kwin`) still work.

Options, caveats, and the full output list are in the
[setup guide](docs/GUIDE.md#nix-flake-nixos-and-home-manager).

## Documentation

- **[User & setup guide](docs/GUIDE.md)** — install, per-platform setup, writing layouts, the client features, and the development loop.
- **[Reference](docs/REFERENCE.md)** — every CLI flag, environment variable, and HTTP endpoint.
- **[Architecture](docs/ARCHITECTURE.md)** — how the daemon, client, and focus watchers fit together.
- **[Platform parity](docs/PLATFORM-PARITY.md)** — what's verified working on each OS.
- **[Testing](docs/TESTING.md)** — the test ladder and integration gaps.
- **[Agent onboarding](docs/ONBOARDING.md)** — repository map and read order for contributors and agents.

## License

deckd is free software: you can redistribute it and/or modify it under
the terms of the **GNU General Public License** as published by the
Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See [`LICENSE`](LICENSE) for the full text.
