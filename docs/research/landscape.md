# deckd and the wider landscape — survey of similar projects

> Research compiled 2026-08-06 against each project's official repo, homepage, or
> release notes. Where a claim is hard to verify from a primary source I say so
> in the row. "Last activity" is the most recent commit or release visible on
> the official source at the time of the survey.
>
> Scope: projects that *do at least one of* — drive a Stream Deck from a
> non-Elgato host; turn a phone/tablet (often via a browser) into a control
> surface or input device for a desktop; or auto-switch a surface when the
> focused app changes. This is wider than the README's existing comparison
> table (Stream Deck / KDE Connect / Apple Touch Bar / Remote Touchpad /
> OpenDeck / Boatswain) — that table is the *baseline*; this is the *landscape*.

---

## Bottom line up front

deckd sits in a niche that no surveyed project fills in full: a **pure-browser
control surface** (any phone/tablet, no app install) that **auto-switches per
focused app on the host**, including a **heuristic for *websites* inside
browsers**, with **full arbitrary input injection** (keys/scroll/trackpad
through uinput) on Linux + macOS. Every existing project misses at least one of
those four:

- Projects that auto-switch (Stream Deck "Smart Profiles", Companion, Kando,
  StreamController, Hammerspoon, AutoHotkey, Keyboard Maestro, Espanso)
  either need **Elgato hardware** (Stream Deck, OpenDeck, StreamController),
  are **OS-locked to one platform** (AutoHotkey=Win, Hammerspoon=Mac,
  KMenu=Mac), or are **hotkey/command only with no visual surface** (AHK,
  Hammerspoon, Espanso).
- Projects that put a surface in a browser (Bitfocus Companion's web "Buttons"
  view, Touch Portal, Macro Deck, WebDeck, portway, Remote Touchpad, Home
  Assistant Dashboards, TileBoard) are **either not per-app auto-switched** (HA,
  TileBoard, Remote Touchpad, portway) or **are owned by a parent app whose
  primary surface is hardware** (Companion) or a **native mobile app** (Touch
  Portal, Macro Deck, WebDeck).
- Per-website matching is the cleanest **differentiator deckd has today**:
  Espanso's `filter_title` is the only other open-source project that
  documents the same browser-title heuristic, and Espanso is text-expansion,
  not a control surface. Kando's per-window-name rules are a closer cousin but
  it's a pie menu, not a grid.

The five projects to study as the *closest* peers (different axes each):

1. **Bitfocus Companion** (MIT) — closest in *what it does at the surface
   level* (web button grid, app-aware page switching, huge integration
   surface), but the host is a pro-AV shotbox; the web "Buttons" view is a
   side-feature, and it does not inject into the *host OS* — it controls other
   software.
2. **StreamController** (GPL-3.0) — closest Linux-native peer for *per-app
   auto-switching*, but hardware-bound to Elgato Stream Deck devices. If
   deckd ever cared about that hardware, this is the project to learn from.
3. **Kando** (MIT) — closest in *philosophy* (free software, plain formats,
   per-app/per-window rules, fully open on GitHub). It's a pie menu, not a
   grid, so the UX differs — but the *declarative-rules-per-app* design is
   the same idea.
4. **portway** (MIT) — closest in *transport shape* (browser client, uinput on
   Linux, no cloud, small Rust daemon), but it does only trackpad+keyboard
   with no deck layer. If deckd ever loses the deck and keeps only manual
   control mode, this is the spiritual sibling.
5. **Remote Touchpad** (GPL-3.0) — the **canonical** older browser-based
   remote-input project, the one already in deckd's README. Still maintained
   (Flatpak + Snap + Windows), GPL-3.0, on Wayland via the Flatpak
   RemoteDesktop portal. Smaller, simpler, and the right reference for
   the transport & security shape even if it doesn't have a deck.

A possible 6th, more aspirational: **Hammerspoon** (Mac) is the *engineering*
peer — a tiny Lua-scriptable daemon that *programmers* extend to do exactly
this kind of thing — and is worth studying for its API ergonomics, even
though its visual surface is "anything `hs.canvas` can draw," not a polished
button grid.

---

## How I sliced the landscape

There are three "categories" projects get put in that actually overlap a lot
in practice. I'll keep them separate here so the comparison is honest:

1. **Stream Deck hardware drivers / Stream Deck clones** — apps whose
   primary surface is an Elgato Stream Deck (physical or virtual). This is
   where most people look first.
2. **Phone-as-input** — apps that turn a phone/tablet into a trackpad,
   keyboard, mouse, or presentation remote. deckd's *manual control mode* is
   here, but only as a secondary feature.
3. **Browser-served control surfaces** — apps whose primary surface is a
   webpage the phone loads. This is deckd's *primary* surface category, and
   it's the one with the biggest overlap with (1) and (2).
4. **App-aware / context-aware control surfaces** — projects whose
   *behaviour changes* when the focused app changes. This is the
   cross-cutting capability deckd's "auto-switching per focused app" lives in.

A real project can be in two or three of these. deckd is in (2), (3), and (4).

---

## 1. Stream Deck hardware drivers / clones

These are apps whose **primary surface is an Elgato Stream Deck device**.
Deckd is *not* a Stream Deck host, but the comparison matters because (a) the
Stream Deck SDK defines the "auto-switch profile per app" feature (called
"Smart Profiles") that deckd re-implements, and (b) several of these projects
have a "Tacto"/"Satellite" mode that uses a phone/tablet *alongside* the
hardware, so they're where the Stream Deck folks went when they wanted a
phone/tablet surface.

| # | Project | URL | Platform | Profiles / auto-switch | Hardware | License | Last activity | Notes |
|---|---------|-----|----------|------------------------|----------|---------|---------------|-------|
| 1 | **Elgato Stream Deck** (closed) | [elgato.com](https://www.elgato.com/us/en/s/stream-deck-app) | Win, macOS, iPad | **Yes — "Smart Profiles"** via SDK `ApplicationsToMonitor` (see [SDK Profiles guide](https://docs.elgato.com/streamdeck/sdk/guides/profiles) and [App Monitoring](https://docs.elgato.com/streamdeck/sdk/guides/app-monitoring)) | Elgato hardware (Original, MK.2, Mini, XL, Plus, Pedal, Neo) | Proprietary, free app | Active (SDK 2.0.0) | The reference. The auto-switching mechanism is documented SDK-side; the marketing name "Smart Profiles" is in the Explorer article that drives Marketplace profiles. |
| 2 | **OpenDeck** | [github.com/nekename/OpenDeck](https://github.com/nekename/OpenDeck) | Linux, macOS, Win | **Yes** — auto-switch on active window (GNOME/KDE/X11 with Tauri tooling) | Elgato hardware; also drives **Tacto** on phone as a virtual deck | **GPL-3.0** | v2.14.0 (2026-07-29); 2.0k stars | Cross-platform Linux-first Stream Deck host that runs the official Elgato plugin ecosystem. **Tacto** is its commercial phone surface. |
| 3 | **StreamController** | [github.com/StreamController/StreamController](https://github.com/StreamController/StreamController) | Linux (GNOME, Hyprland, Sway, KDE via kdotool, X11) | **Yes** — Automatic Page Switching on active window; auto-lock on KDE/GNOME/Cinnamon | Elgato hardware (Original, Mini, XL, Pedal, Plus, Neo, Modules) | **GPL-3.0** | v2 series active; 1.1k stars, 1,884 commits | GTK4/Libadwaita, "an elegant Linux app for the Elgato Stream Deck with support for plugins." Closest *Linux-native* peer for the auto-switching UX. |
| 4 | **Boatswain** | [gitlab.gnome.org/World/boatswain](https://gitlab.gnome.org/World/boatswain) (Flathub: `com.feaneron.Boatswain`) | Linux (GNOME-native) | Pages + profiles, folders | Elgato hardware (Original, Mini, XL, Plus) | **GPL-3.0** | Last release ~4 months ago | GNOME-native, focused on streaming workflows (OBS, sound, etc.); no SDK plugin ecosystem. |
| 5 | **streamdeck-ui** | [github.com/timothycrosley/streamdeck-ui](https://github.com/timothycrosley/streamdeck-ui) | Linux (Arch/CentOS/Fedora/openSUSE/Ubuntu) | Multi-page buttons, drag/drop, auto-dim, animated icons | Elgato hardware (Original, MK2, Mini, XL, Pedal) | **MIT** | 1.3k stars; v2 series in PyPI | Minimal Linux-only Stream Deck UI; actions: run command, press keys, write text. |
| 6 | **LoupixDeck** | [github.com/RadiatorTwo/LoupixDeck](https://github.com/RadiatorTwo/LoupixDeck) | Linux + Windows | Pages, profiles | Loupedeck Live S, Razer Stream Controller | Source-available (custom) | Active | Niche: drives Loupedeck/Razer on Linux. |
| 7 | **Touch Portal** *(proprietary, cross-platform phone-as-deck)* | [touch-portal.com](https://www.touch-portal.com/) | Win, macOS, **Linux (beta AppImage)** | Unlimited pages, manual switching; per-page "On Enter/On Exit" actions; app state logic | Phone/tablet via iOS/Android app | Proprietary (free + Pro IAP) | Active (v4.6 desktop, 2026) | Closest *commercial* phone-as-deck to deckd; ships a native mobile app. |
| 8 | **Tacto** *(proprietary, phone-as-deck, built on OpenDeck)* | [tacto.live](https://tacto.live/) | Linux/macOS/Win via OpenDeck | Profiles **auto-switch with focused apps**, multi-action, toggle actions, custom backgrounds | **Phone only** (no Stream Deck hardware required) | Proprietary (free + Pro $24.99) | Active commercial product | Polished "Stream Deck Mobile" alternative; full plugin marketplace. |

**What this category is for and where it doesn't reach deckd:** the
auto-switching *is* the same idea as deckd's, but every entry above is
either hardware-bound (Stream Deck device required) or a native phone app
(Touch Portal, Tacto, Macro Deck). deckd's "load any browser, no install"
angle is the part none of them hit.

---

## 2. Phone-as-input

deckd's manual-control mode sits here. The closest open peers are tiny,
single-purpose Go/Rust/Python daemons with a browser client.

| # | Project | URL | Connection | Input primitives | Platform (host / client) | License | Last activity | Notes |
|---|---------|-----|------------|------------------|--------------------------|---------|---------------|-------|
| 1 | **KDE Connect** | [kdeconnect.kde.org](https://kdeconnect.kde.org/) ([kdeconnect-kde](https://github.com/KDE/kdeconnect-kde), [kdeconnect-android](https://invent.kde.org/network/kdeconnect-android), [kdeconnect-ios](https://github.com/KDE/kdeconnect-ios)) | LAN (UDP/TCP), BT, optional relay | Virtual touchpad, remote keyboard (incl. meta), presentation remote, media keys, mouse, file/clipboard/notification, run commands | Linux (best on KDE), macOS, Win / Android, iOS, Plasma Mobile | **GPL-2.0+** | kdeconnect-kde master commit 2026-08-06; F-Droid `1.35.11` (2026-08-05) | The "do it all" device-integration suite; remote-input is a plugin. iOS is read-only (no remote-input plugin). |
| 2 | **Remote Touchpad** | [github.com/Unrud/remote-touchpad](https://github.com/Unrud/remote-touchpad) | LAN (HTTP/QR-code pair, TLS optional) | Trackpad, keyboard (US ASCII, named keys), gestures, media/nav keys | Linux (Flatpak RemoteDesktop portal, X11, uinput), Win / any browser | **GPL-3.0** | master commit 2026-08-02 (v1.5.4); 671 stars | Single-binary Go server; closest spiritual ancestor of deckd's manual-control mode (already in deckd's README). |
| 3 | **portway** | [github.com/heptanal/portway](https://github.com/heptanal/portway) | LAN (HTTPS+WS, six-digit pairing, optional cert TLS) | Touchpad (1/2-finger gestures, drag-lock, scroll, click), US-ASCII keyboard + special keys, sticky modifiers, media keys | Linux (uinput — wayland/X agnostic) / any browser | **MIT** | Last commit 2026-07-19 | Browser-based remote mouse + keyboard. Same shape as deckd's manual-control mode but **no button deck**. NixOS module. |
| 4 | **Unified Remote** *(proprietary)* | [unifiedremote.com](https://www.unifiedremote.com/) | LAN | 100+ remotes: mouse, keyboard, media (Spotify/iTunes/XBMC/Netflix), screen mirror, file manager, power | Win, macOS, Linux, RPi, Arduino Yún / Android, iOS, Win Phone | Proprietary (free + paid) | Active product | Broad app-specific remotes; the "non-KVM" incumbent. |
| 5 | **Deskreen** | [deskreen.com](https://deskreen.com/) / [github.com/pavlobu/deskreen](https://github.com/pavlobu/deskreen) | LAN (WebRTC) | Screen mirror + "Second Screen" (Virtual Display Adapter); **no input injection** | Win, macOS, Linux / any browser | **AGPL-3.0** | master 2026-07-08 (v3.2.16) | Often grouped with phone-as-input but is really a *viewer* — phone is passive. |
| 6 | **scrcpy** | [github.com/Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) | USB (ADB) or wireless TCP/IP | Mirror **Android** screen + audio to computer; computer keyboard/mouse back into Android (HID); gamepad, OTG, V4L2 | Win, macOS, Linux / Android 5+ | **Apache-2.0** | v4.1 (2026-07-10) | The *inverse* direction (desktop → phone). Listed because it's the canonical cross-device input project. |
| 7 | **Input Leap** | [github.com/input-leap/input-leap](https://github.com/input-leap/input-leap) | LAN (custom TCP) | Mouse + keyboard sharing across machines (KVM-style, no phone client) | Linux, macOS, Win, BSD / same | **GPL-2.0** | **Archived 2026-07-26**; last commit 2025-11-27 | The "active" software-KVM fork. Repo is now read-only. Worth knowing only as a defunct peer. |
| 8 | **Barrier** | [github.com/debauchee/barrier](https://github.com/debauchee/barrier) | LAN | Mouse + keyboard sharing; clipboard | Linux, macOS, Win, BSD / same | **GPL-2.0** | Last commit 2022-02-04 | Effectively abandoned; input-leap replaced it. Upstream is now [deskflow/deskflow](https://github.com/deskflow/deskflow). |
| 9 | **Synergy** *(proprietary)* | [symless.com](https://symless.com/synergy) | LAN | Mouse + keyboard sharing, clipboard | Linux, macOS, Win | Commercial | Active | The proprietary KVM; not relevant to phone-as-input. |
| 10 | **Wifi-Mouse / Remote Mouse / Air Mouse / Monect** *(proprietary apps)* | app stores | LAN, some internet relay | Mouse, keyboard, media, gamepad, presentation, sometimes screen mirror | Win, macOS, Linux / Android, iOS | Proprietary | Marketed; closed source | Mentioned only because they dominate the store listings. |

**Smaller open-source entries (flagged, not asserted as competitors):**
[blue_keyboard](https://github.com/larrylart/blue_keyboard) (BT-HID dongle),
[ShareClick](https://github.com/phun333/ShareClick) (Rust KVM, mac↔Win only),
[boundless](https://github.com/bestlux/boundless) (Rust, Win-only),
[AirType-N](https://github.com/ChanIok/AirType-N) (phone-voice → desktop
keystrokes), [PalmPoint-PhoneInput](https://github.com/PalmPoint/PalmPoint-PhoneInput)
(BT trackpad/keyboard/gamepad), [phone-trackpad](https://github.com/AIcrafter-nanashi/phone-trackpad)
(0-star hobby), [trackpadpp](https://github.com/pg07codes/trackpadpp) (22 stars, stale),
[AndroidTrackpad](https://github.com/teamclouday/AndroidTrackpad) (12 stars, stale).

**Where this category doesn't reach deckd:** every project here either ships
a *fixed remote UI* (Unified Remote, KDE Connect's virtual touchpad) or
*exposes the input primitives only* (no deck/buttons). The "I have a grid of
buttons, **and** a trackpad, **and** auto-switches per app" combination is
deckd's distinguishing composition.

---

## 3. Browser-served control surfaces

The narrower category deckd's *primary* surface lives in: **a webpage the
phone loads** that acts as a control surface for the host.

| # | Project | URL | Surface | Client device | Customization | Per-app / context switching | License | Last activity | Notes |
|---|---------|-----|---------|---------------|---------------|----------------------------|---------|---------------|-------|
| 1 | **Bitfocus Companion** | [bitfocus.io/companion](https://bitfocus.io/companion) / [github.com/bitfocus/companion](https://github.com/bitfocus/companion) | Shotbox for broadcast/AV (OBS, vMix, ATEM, QLab, X32, etc.); **web "Buttons" view serves a button grid in a browser** | Web buttons = tablet/phone in browser + emulator + actual Stream Deck hardware | Web admin (in-browser GUI): button designer with feedback, stacked actions, logic, durations | **Yes — per-connection variables drive page swaps; the web view follows.** | **MIT** | v5.0.3 (2026-08-05); 2.2k stars, ~9.8k commits | The most direct peer in the *what-it-does-at-the-surface* sense. The web buttons view is a side-feature of a shotbox; the page model is per-connection rather than per-OS-app. |
| 2 | **Bitfocus Companion Satellite** | [bitfocus.io/companion](https://bitfocus.io/companion) (same project) | Companion's first-class tablet/phone surface | iOS/Android, web | Same as Companion; Satellite is the dedicated client app | Same | **MIT** | Same | Worth flagging separately because the Satellite model — a dedicated *mobile client app* — is the bit that's actually "phone-as-deck" within the Companion ecosystem. |
| 3 | **Macro Deck** | [github.com/Macro-Deck-App/Macro-Deck](https://github.com/Macro-Deck-App/Macro-Deck) (homepage: [macro-deck.app](https://macro-deck.app/)) | Macro pad with first-class mobile/web clients and a plugin ecosystem | **Android, iOS, web** + Stream Deck hardware via plugin | Drag-and-drop desktop editor + plugin store; variables + Cottle templating | Multi-profile, switchable | **Apache-2.0** | Active (updated 21 days ago); 1.5k stars, 691 commits | Open-source Windows host with first-class mobile/web clients. Closer in *stack* to deckd than any of the Stream Deck clones, but still ships a native mobile app for the primary surface. |
| 4 | **WebDeck** | [github.com/Lenochxd/WebDeck](https://github.com/Lenochxd/WebDeck) | Browser-based Stream Deck alternative (Flask web app, system tray, QR code) | Phone/tablet in browser; no install on phone | Drag-and-drop button grid | Manual | **GPL-3.0** | Active-ish (May 2026); 927 stars, 894 commits | Win-only host. The "browser-only, no install on phone" promise deckd also makes, but **Windows-only and no per-app switching**. |
| 5 | **Touch Portal** *(proprietary, phone-as-deck)* | [touch-portal.com](https://www.touch-portal.com/) | Macro pad with iOS/Android client app | iOS/Android app + Win/Mac/Linux host | Visual editor in the desktop app | Per-page On Enter/On Exit actions; app state logic | Proprietary (free + Pro) | v4.6 (2026) | Native mobile app, not pure web — but the closest polished cross-platform phone-as-deck. |
| 6 | **Home Assistant Dashboards** | [home-assistant.io/dashboards](https://www.home-assistant.io/dashboards/) | Home-automation control panel (tiles, buttons, gauges, cards) | Any browser (wall tablets, phones, desktop) | **Visual GUI editor** + YAML for `views` / `cards` | **Yes — via Views** (tabbed pages, per-user visibility, conditional cards, URL deep-link `/lovelace/<path>`) | HA frontend **Apache-2.0**; HA core **MIT** | Active; refs HA `2026.8.0` | The "browser-served control surface" idea taken to its home-automation extreme. **Host is the HA server itself** — no notion of "the focused app on my laptop." |
| 7 | **openHAB Main UI** (Layout Pages) | [openhab.org/docs/ui](https://www.openhab.org/docs/ui/) | Modern openHAB control surface | Any browser | In-browser Design + Code tabs (visual + YAML) | Tabbed pages, modal navigation, per-user `visibleTo` | **EPL-2.0** | Active (5.x) | Same idea as HA, openHAB stack. |
| 8 | **HABPanel** (openHAB legacy) | [openhab.org/docs/ui/habpanel](https://www.openhab.org/docs/ui/habpanel/habpanel.html) | Wall-tablet dashboard for openHAB | Any browser | In-browser drag-and-drop designer, JSON export | Dashboard list; switch via openHAB item | **EPL-2.0** | Archived; replaced by Main UI | Listed for completeness. |
| 9 | **SharpTools** *(proprietary SaaS)* | [sharptools.io](https://www.sharptools.io/) | Smart-home dashboard + rule engine; multi-hub (SmartThings, Hubitat, HA, Homey) | Any browser, Android, iOS, Fire Tablet | Drag-and-drop tile editor; "Super Tiles" for custom layouts | Multi-dashboard navigation, PIN-protected sharing, guest accounts | Proprietary | Active (2026) | Polished commercial version of the HA/openHAB idea. Still smart-home, not desktop-control. |
| 10 | **TileBoard** | original `resoai/TileBoard` 404; community fork [sgoudsme/TileBoard](https://github.com/sgoudsme/TileBoard) | HA tile-grid dashboard | Any browser, HA add-on | `config.js` only (no GUI) | Multi-page, side-menu; no app-aware switching | **MIT** | **Effectively dead** (last touched 2018) | Listed because it's the most-cited "wall tablet dashboard" recipe; but it's stale. |
| 11 | **Node-RED Dashboard** | [flows.nodered.org/node/node-red-dashboard](https://flows.nodered.org/node/node-red-dashboard) | Generic data/control dashboard from Node-RED flows | Any browser | Drag-and-drop in Node-RED editor | Tabs + groups; `ui-control` node can switch tabs dynamically based on flow state | **Apache-2.0** | **DEPRECATED** 2024-06-27 (Angular v1 EOL) | Listed for the **ui-control pattern**: a server-side flow can drive a tab change. Closest thing to "context-driven layout swap" outside the OS-app-focus world. |
| 12 | **FlowFuse Dashboard** | [github.com/FlowFuse/node-red-dashboard](https://github.com/FlowFuse/node-red-dashboard) | Successor to Node-RED Dashboard (Vue 3 / Vite) | Any browser | Same drag-and-drop + `ui-template` (raw HTML/JS), `ui-markdown` (Mermaid) | Same: tabs/groups; `ui-event` / `ui-control` for dynamic context | **Apache-2.0** | Active (351 stars, 3,484 commits) | The active project for the Node-RED dashboard pattern. Still flow-driven, not app-focus-driven. |
| 13 | **MagicMirror²** | [magicmirror.builders](https://magicmirror.builders/) | Smart-mirror display | Any browser (typically a Pi behind a one-way mirror) | Modules in `config/config.js` | Module rotation per time-of-day; mostly read-only | **MIT** | Active | Listed for completeness — *not* a control surface (mostly read-only: calendar, weather, news). |
| 14 | **Grafana** | [grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/) | Observability / SCADA-style dashboards | Any browser (kiosk mode common) | Dashboard JSON/YAML; rich plugin ecosystem | **Templated variables** + URL params drive state — close to "context switching" via URL, not via OS app focus | **AGPL-3.0** (OSS edition) | Active | Adjacent category: data dashboards. True "context switching" is via templated variables, not OS app focus. |
| 15 | **OBS Web** (Niek) | [github.com/Niek/obs-web](https://github.com/Niek/obs-web) | Browser-served OBS controller | Any browser | Web button grid | **No** — purely an OBS remote | **MIT** | Last touched ~2018 | Specific to OBS Studio over obs-websocket. |

**What this category is for and where deckd sits:** "a control surface served
as a webpage." Three sub-flavours:

- **Home-automation panels (HA / openHAB / SharpTools / TileBoard).** They
  control *device state*, not *the host OS's focused app*. The "host" is the
  home-automation server. Different problem from deckd's.
- **General-purpose dashboards (Node-RED / FlowFuse / Grafana).**
  Flow- or URL-driven context switching, not OS-app-driven. They can do
  dynamic tab swaps (`ui-control`), but the trigger is "the server says
  so," not "you alt-tabbed to Firefox."
- **Desktop / shotbox surfaces (Companion's web buttons, WebDeck, plus the
  Touch Portal / Tacto / Macro Deck mobile apps).** This is the only
  sub-flavour that *knows about the host OS's apps*. Companion's web view is
  the most capable; WebDeck is the closest "pure browser" implementation.
  Macro Deck ships a native mobile client and a web view.

deckd lives in the third sub-flavour but is, as far as I could verify, the
only project in the *entire table* that combines (a) pure-browser client
(no app install), (b) host-OS **app-focus** detection, (c) **arbitrary
input injection on the host OS** (keys/scroll/trackpad via uinput).

---

## 4. App-aware / context-aware control surfaces

This is the cross-cutting capability: the surface's *contents* change when the
focused app changes. deckd's most distinctive feature.

| # | Project | URL | Trigger | What changes on trigger | Per-app granularity | License | Last activity | Notes |
|---|---------|-----|---------|------------------------|--------------------|---------|---------------|-------|
| 1 | **Elgato Stream Deck "Smart Profiles"** | [docs.elgato.com/streamdeck/sdk/guides/profiles](https://docs.elgato.com/streamdeck/sdk/guides/profiles), [sdk/guides/app-monitoring](https://docs.elgato.com/streamdeck/sdk/guides/app-monitoring) | `ApplicationsToMonitor` (Win `.exe`, macOS bundle id) → `onApplicationDidLaunch` / `Terminate` | Layout swap on the Stream Deck | Yes — full per-app | Proprietary SDK, free app | Active (SDK 2.0.0) | The reference. Mechanism is SDK-level: a plugin declares which apps to watch and is notified; the Stream Deck software swaps the active profile. |
| 2 | **Bitfocus Companion v5** | [bitfocus.io/companion](https://bitfocus.io/companion) | Programmable triggers: time, sunrise/sunset, variable change, button press, HTTP/TCP/UDP/OSC/MIDI; per-connection variables expose app state | Page swap on a Stream Deck / Loupedeck / MIDI / emulator / web surface | Yes — per-connection (OBS, vMix, ATEM, X32, QLab, …) | **MIT** | v5.0.3 (2026-08-05) | Most flexible page model in the category. App focus is exposed as a module variable, not a first-class focus event. |
| 3 | **AutoHotkey** (Windows) | [autohotkey.com](https://www.autohotkey.com/), [`WinActive`](https://www.autohotkey.com/docs/v2/lib/WinActive.htm) | `WinActive()`, `#HotIf WinActive(...)`, shell hooks | Hotkey remap; auto-execute sections rebind keys per focused window | Yes — `ahk_exe`, `ahk_class`, window title | **GPLv2** | Active (v2.x) | The textbook implementation of the paradigm. **No visual surface** — pure hotkey/command dispatch. |
| 4 | **Hammerspoon** (macOS) | [hammerspoon.org](https://www.hammerspoon.org/) | `hs.application.watcher` fires on activate/deactivate/hide/show | User-defined: a `hs.canvas` button bar, a chooser, a modal hotkey set | Yes — fully programmable in Lua | **MIT** | Active (15.9k stars) | Includes `Seal` (pluggable launch bar) and Spoons like `InputSourceSwitch`, `URLDispatcher`. The right project to study for **API ergonomics** of a programmable, app-aware daemon. |
| 5 | **Kando** (cross-platform) | [kando.menu](https://kando.menu/) | Per-menu conditions evaluated on invocation: app name, window name/title, focused window class | **Pie menu swap** (radial, not grid) | Yes — full per-app / per-window-name | **MIT** | v2.3.1 (2026-06-04); v3.0.0 alpha 1 (2026-07-10); 6.2k stars | Closest in *philosophy* to deckd: free software, plain formats, declarative per-app rules. The radial-vs-grid UX is the main difference. v3.0 adds an explicit `focus-window` workflow action. |
| 6 | **Espanso** | [espanso.org](https://espanso.org/) | Per-config `filter_exec` / `filter_class` / `filter_title` (regex on window title — **the only open-source project that documents a per-website-title rule** like deckd's) | Behaviour swap, not visual: `enable`, `backend`, include/exclude specific matches | Yes — per-app AND per-website | **GPL-3.0** | Active (v2.x); 14.2k stars | Text expander, not a control surface — but its `filter_title` is the cleanest documentation of "match on a website's title in a browser" I've seen. Wayland app-specific configs are not yet supported. |
| 7 | **Keyboard Maestro** (Mac) | [keyboardmaestro.com](https://www.keyboardmaestro.com/) | Macro Group availability criteria — *Available in these applications* | Either hotkey remap **or** a floating **Macro Palette** (real visual surface, per-app) | Yes — first-class | Proprietary (US$36 one-time) | Active (v11.x) | The Macro Palette is a true visual surface that swaps when focus changes. Wiki has a "Browsers" group example that has different macros for Chrome, Firefox, Safari. |
| 8 | **BetterTouchTool** (Mac) | [folivora.ai](https://folivora.ai/) | Per-app gestures and shortcuts | Touch Bar widgets can function as a small visual surface that changes per app | Yes — per-app, per-gesture | Proprietary | Active | **Caveat:** couldn't render the JS-only site to verify exact feature set; prior knowledge only. |
| 9 | **Albert** (Linux launcher) | [albertlauncher.github.io](https://albertlauncher.github.io/) | Spotlight-style launcher; plugins can read the frontmost app | The launcher UI does *not* swap on focus change (single surface) | Plugin-defined, possible but not built-in | **MIT** | v35.1.0 (2026-07-25); 8.0k stars | Listed for completeness — Albert is a *launcher*, not a context-aware surface. |
| 10 | **Albert/Raycast/Ueli/Alfred/dmenu/Rofi/Wofi** (launchers) | various | Single command palette, not focus-driven | n/a | n/a | various | All active | Degenerate case in this category. |

---

## 5. Where the gaps land — and what that implies for deckd

The pattern across all four tables:

| Capability | Stream Deck clones | Phone-as-input | Browser-served surfaces | App-aware switching |
|------------|--------------------|----------------|------------------------|---------------------|
| Visual control surface (button grid / pie / palette) | ✅ All | ❌ None (fixed remotes) | ✅ Some (HA, Companion, WebDeck, Touch Portal) | ✅ Some (Kando, KM palette) |
| Auto-switch on host-OS app focus | ✅ All (hardware-bound) | ❌ None | ❌ None (HA/Node-RED driven by server state) | ✅ Many |
| Per-website / per-URL matching | 🟡 No (only via plugins for specific sites) | ❌ No | 🟡 Companion via browser module | 🟡 Espanso `filter_title` (text only) |
| Pure-browser client (no install on phone) | 🟡 Tacto/Companion Satellite are native apps | ✅ Most (KDE Connect's virtual touchpad is the exception) | ✅ All | n/a |
| Linux + Wayland + X11 host | 🟡 OpenDeck/StreamController yes; Boatswain GNOME only | ✅ Most (Remote Touchpad, portway, KDE Connect) | 🟡 Some via Wine | 🟡 AutoHotkey=Win, Hammerspoon=Mac |
| Arbitrary input injection (keys/scroll/trackpad) on the host OS | ❌ Hardware buttons + plugin-scoped | ✅ Whole point | 🟡 Macro Deck/Companion via plugins | 🟡 Hammerspoon, AHK |
| Open data format for the layout | 🟡 Plugin-specific | n/a | ✅ YAML/JSON for most | ✅ Yes (YAML, Lua, AHK) |

The cell that **only deckd fills** in this table is the combination
**pure-browser client + OS app focus + arbitrary input injection on the
host OS + per-website heuristic**. Other projects cover the corners:

- *Per-app auto-switching without hardware*: Hammerspoon, Kando, Keyboard
  Maestro, Espanso, AHK. But they're all hotkey/command only, not button
  grids.
- *Per-website matching*: Espanso's `filter_title`. Text expander, not a
  control surface.
- *Browser-served control surface*: Companion's web buttons, WebDeck.
  Neither does OS app focus.
- *Per-app auto-switching on a grid*: Elgato Stream Deck (hardware), OpenDeck
  (hardware), StreamController (hardware), Tacto (native app), Touch Portal
  (native app), Keyboard Maestro's palette (Mac only, hotkey-driven).

---

## 6. Implications for deckd

Three observations worth pulling out:

1. **The per-website heuristic is a genuine differentiator, and it's the
   cleanest open documentation of the pattern.** Espanso's `filter_title`
   is the only other project I found that documents "match on a website's
   title in a browser," and it's a text expander. deckd's `title:` glob in
   the layout YAML is the same idea applied to a control surface. **The
   planned URL-based matching via a browser extension
   ([#90](https://github.com/jonocodes/deckd/issues/90)) would make
   deckd the only project with both per-app and per-URL focus rules in
   a visual surface — and worth marketing.**
2. **The closest direct peer is Companion's web "Buttons" view, not
   Stream Deck itself.** Companion is MIT-licensed, more flexible than
   Stream Deck for page logic, and supports a web "Buttons" view that's
   a phone/tablet in a browser. The differences are (a) Companion's
   primary surface is the Stream Deck hardware, (b) the page model is
   *per-connection* (OBS, vMix, ATEM) rather than per-OS-app, (c)
   Companion doesn't inject into the *host OS*'s window system. Studying
   Companion's web view UX is probably the highest-leverage peer-review
   deckd can do.
3. **The peer deckd is most likely to be confused with is Touch Portal,
   Tacto, and Macro Deck — and the cleanest differentiator from all three
   is "no install on the phone."** Touch Portal, Tacto, and Macro Deck
   all require a native mobile app install. deckd's "load any browser"
   promise is the angle none of them have, and it should be loud in the
   README and the marketing (already in the README's "Controller
   agnostic" + "Connection: Browser (WiFi)" rows of the comparison
   table).

A small **second-order** observation: the **KVM fork line is collapsing**
(Input Leap archived 2026-07-26, Barrier silent since 2022, the only
maintained software-KVM is the proprietary Synergy and small Rust
experiments). That's not directly deckd's space (KVMs are computer↔computer,
not phone↔computer), but it's a sign that "share input across devices" is
fragmenting — and the phone-as-input projects (Remote Touchpad, portway,
KDE Connect's plugin, deckd's manual control) are picking up some of the
energy. Worth keeping an eye on.

---

## 7. What I'd watch for next

- **StreamController's mobile story.** If they ever add a "Tacto-style"
  phone/tablet client, they're the Linux-native closest peer in the
  *exact same direction* as deckd.
- **Companion v5 Satellite on iPad / Android tablets.** Their first-class
  tablet client is the strongest commercial phone-as-deck today;
  monitoring their protocol changes is the cheapest way to see what
  phone-as-deck users actually want.
- **Hammerspoon `hs.application.watcher` + a future `hs.webview` for
  a button grid.** If Hammerspoon ever ships a declarative surface, it's
  the project Mac users would use instead of deckd. (Probably won't — the
  Hammerspoon philosophy is "script it yourself.")
- **The promised browser extension for URL-based focus
  ([#90](https://github.com/jonocodes/deckd/issues/90)).** This is the
  move that turns deckd from "the title-glob deck" into "the
  per-website deck," which has no open-source peer in the visual-surface
  category at all.

---

## 8. Confidence / what's still uncertain

**High confidence (primary source verified during this survey):**

- Elgato SDK's `ApplicationsToMonitor` mechanism for per-app profile
  switching (the [Stream Deck SDK Profiles guide](https://docs.elgato.com/streamdeck/sdk/guides/profiles)
  and [App Monitoring](https://docs.elgato.com/streamdeck/sdk/guides/app-monitoring)
  page are explicit and current).
- OpenDeck, StreamController, Boatswain, streamdeck-ui, Remote Touchpad,
  portway, KDE Connect, Kando, Espanso, Hammerspoon, Companion, Macro Deck,
  StreamController, scrcpy, Deskreen, FlowFuse Dashboard — all existence
  and last-activity verified against GitHub or the project's own homepage.
- Input Leap's [archive notice](https://github.com/input-leap/input-leap)
  (2026-07-26) and Barrier's [last commit](https://github.com/debauchee/barrier/commit/653e4badeb88f61de901581667d4465d7b1e2d52)
  (2022-02-04).
- Touch Portal's cross-platform beta on Linux (AppImage), and
  Bitfocus Companion's [MIT license](https://github.com/bitfocus/companion)
  + v5.0.3 release date.

**Medium confidence:**

- The exact feature set of **Touch Portal Pro** (free base vs. Pro IAP
  split, what unlocks where). Site returned a JS-only shell.
- **Deckboard's** current state and platform support — homepage is
  a JS-only SPA, no public repo located in the survey window. Listed in
  the table with the "could not verify" caveat in earlier sub-survey
  notes.
- **BetterTouchTool's** per-app gesture and Touch Bar behaviour — the
  folivora.ai site is JS-rendered and didn't yield a static source for
  verification. Marked in the table.
- Companion's **web "Buttons" view** as a *first-class* surface — true
  in the sense that the project's docs reference a web buttons page, but
  Companion's marketing site returned a JS-only shell in the survey
  window, so the *UX* of that view (vs. its existence) is a bit
  under-documented. The repo's README and modules list are the stronger
  evidence.

**Low confidence / unverified:**

- **Elgato's literal "Smart Profiles" marketing name** — the marketing
  page at `elgato.com/.../smart-profiles-stream-deck` returns 404. The
  underlying *behaviour* (per-app profile auto-switching via
  `ApplicationsToMonitor`) is well-documented in the SDK guides. I've
  used the name because it's the term used in the Stream Deck release
  notes and the Explorer articles, but the specific page couldn't be
  fetched.
- **Touch Portal's exact last activity on Linux** — the v4.6 build number
  is current, but the AppImage's standalone release cadence isn't
  documented in a way I could pin down to a specific month.
- Any **paid-app feature gating or pricing changes** for Touch Portal,
  Tacto, SharpTools, BetterTouchTool, Keyboard Maestro — these are
  commercial products whose pricing I quoted from their sites at survey
  time, but pricing pages change.

Where I could not verify a claim with a primary source, the row in the
table says so. If you spot a project that should be in the survey and
isn't, the most likely explanation is "I couldn't verify its existence
from a primary source at the time of the survey" — happy to add it
given a link.

---

## Primary sources (most-cited during the survey)

- Bitfocus Companion — [bitfocus.io/companion](https://bitfocus.io/companion), [github.com/bitfocus/companion](https://github.com/bitfocus/companion)
- Stream Deck SDK — [docs.elgato.com/streamdeck/sdk](https://docs.elgato.com/streamdeck/sdk/guides/profiles), [docs.elgato.com/streamdeck/sdk/guides/app-monitoring](https://docs.elgato.com/streamdeck/sdk/guides/app-monitoring)
- OpenDeck — [github.com/nekename/OpenDeck](https://github.com/nekename/OpenDeck)
- StreamController — [github.com/StreamController/StreamController](https://github.com/StreamController/StreamController)
- Boatswain — [gitlab.gnome.org/World/boatswain](https://gitlab.gnome.org/World/boatswain), [flathub.org/en/apps/com.feaneron.Boatswain](https://flathub.org/en/apps/com.feaneron.Boatswain)
- Touch Portal — [touch-portal.com](https://www.touch-portal.com/)
- Tacto — [tacto.live](https://tacto.live/)
- Macro Deck — [github.com/Macro-Deck-App/Macro-Deck](https://github.com/Macro-Deck-App/Macro-Deck), [macro-deck.app](https://macro-deck.app/)
- WebDeck — [github.com/Lenochxd/WebDeck](https://github.com/Lenochxd/WebDeck)
- Remote Touchpad — [github.com/Unrud/remote-touchpad](https://github.com/Unrud/remote-touchpad)
- portway — [github.com/heptanal/portway](https://github.com/heptanal/portway)
- KDE Connect — [kdeconnect.kde.org](https://kdeconnect.kde.org/), [github.com/KDE/kdeconnect-kde](https://github.com/KDE/kdeconnect-kde)
- Input Leap — [github.com/input-leap/input-leap](https://github.com/input-leap/input-leap) (archived)
- Barrier — [github.com/debauchee/barrier](https://github.com/debauchee/barrier)
- scrcpy — [github.com/Genymobile/scrcpy](https://github.com/Genymobile/scrcpy)
- Deskreen — [github.com/pavlobu/deskreen](https://github.com/pavlobu/deskreen)
- Home Assistant Dashboards — [home-assistant.io/dashboards](https://www.home-assistant.io/dashboards/)
- openHAB Main UI — [openhab.org/docs/ui](https://www.openhab.org/docs/ui/)
- Node-RED Dashboard — [flows.nodered.org/node/node-red-dashboard](https://flows.nodered.org/node/node-red-dashboard)
- FlowFuse Dashboard — [github.com/FlowFuse/node-red-dashboard](https://github.com/FlowFuse/node-red-dashboard)
- Kando — [kando.menu](https://kando.menu/), [github.com/kando-menu/kando](https://github.com/kando-menu/kando)
- Espanso — [espanso.org](https://espanso.org/), [espanso.org/docs/configuration/app-specific-configurations](https://espanso.org/docs/configuration/app-specific-configurations/)
- AutoHotkey — [autohotkey.com](https://www.autohotkey.com/), [docs WinActive](https://www.autohotkey.com/docs/v2/lib/WinActive.htm)
- Hammerspoon — [hammerspoon.org](https://www.hammerspoon.org/), [github.com/Hammerspoon/hammerspoon](https://github.com/Hammerspoon/hammerspoon)
- Keyboard Maestro — [keyboardmaestro.com](https://www.keyboardmaestro.com/), [wiki: Macro Groups](https://wiki.keyboardmaestro.com/Macro_Groups)
- Albert — [albertlauncher.github.io](https://albertlauncher.github.io/)
- Grafana — [grafana.com/grafana/dashboards](https://grafana.com/grafana/dashboards/)
