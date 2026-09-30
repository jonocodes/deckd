# Linux distribution: AppImage as the primary channel, with a privileged integration helper

Issue #168 asks which channel gets deckd to Linux users with zero toolchain.
The candidate set was tarball, `.deb`/`.rpm`, AppImage, Flatpak/Snap, and
distro repos. This ADR picks AppImage as the primary artifact, keeps the
relocatable tree + install script as the shared substrate every channel
builds on, and rejects Flatpak/Snap outright.

## Context

deckd is a per-user desktop-session daemon. Three of its capabilities decide
the channel:

1. **Global input injection via `/dev/uinput`** — needs a udev rule in
   `/etc/udev/rules.d` and membership in the `input` group. Both are **root**
   actions.
2. **Reading other apps' windows through a compositor plugin** — a GNOME
   Shell extension or a KWin script, installed and enabled **per user**.
3. **Talking to the session D-Bus bus** — the `dbus:` action primitive plus
   MPRIS, on the **unfiltered** session bus.

Plus user-level autostart (systemd user unit or an XDG `.desktop`) and a
bundled Python runtime + client + layouts.

The GUIDE already rules out Docker for exactly these reasons
(`docs/GUIDE.md:593`): the daemon needs host `/dev/uinput`, the host
session-bus socket, the host display, and still couldn't host the compositor
plugin. The same argument applies to any sandbox that filters devices and the
bus.

## Decisions

### Flatpak and Snap are rejected

A sandboxed package cannot do any of the three load-bearing things:

- It cannot write `/etc/udev/rules.d` or change group membership — and
  `/dev/uinput` is not on Flatpak's device whitelist, so `--device=all` does
  not reliably expose it either.
- Flatpak proxies the session bus through `xdg-dbus-proxy`, so only
  allowlisted names are reachable; arbitrary session services and the
  compositor plugin's own bus traffic break.
- It cannot install or enable a GNOME Shell extension / KWin script from
  inside the sandbox, and cannot read other apps' windows through a
  compositor plugin.

This is the Docker argument restated. Recorded here so it isn't relitigated;
these are properties of the sandbox model, not gaps that a manifest can fill.

### AppImage is the primary channel

AppImage is **not sandboxed** by default, so the daemon runs with the user's
full user-level capability: D-Bus, serving the client, and talking to the
compositor all work as they do from a checkout. It is one file and
distro-agnostic, which matches the "download, install, run" goal of #165 and
#168.

Its limits are the *root* step only:

- It cannot install the udev rule or add the `input` group. There are no
  maintainer scripts. This is true of **every** channel — the root step is
  unavoidable — but AppImage gives no package manager to own it.
- The focus watcher is user-level and **can** be installed by AppImage: the
  GNOME extension goes to `~/.local/share/gnome-shell/extensions` and the KWin
  script to the user's KWin directories, no root needed.
- Autostart can use an XDG `.desktop` in `~/.config/autostart`, which is
  weaker than the systemd *user* unit (no `graphical-session.target`
  ordering, weaker restart semantics).

Known papercut: the AppImage type-2 runtime needs FUSE (`libfuse2`), which
Ubuntu 22.04+/Debian 12 no longer ship by default. `--appimage-extract-and-run`
is the documented fallback.

### The privileged step is a first-run helper, not part of the AppImage

Because the root step exists on every channel, it is factored into a single
`install-system-integration.sh` helper (run with `sudo`) that is idempotent
and has a matching `--uninstall`. It installs:

- `/etc/udev/rules.d/70-deckd-uinput.rules` (the existing
  `packaging/udev/70-deckd-uinput.rules`), then reloads/triggers udev;
- the current user into the `input` group.

It also installs the user-level pieces — the focus watcher and an XDG
autostart entry — so a single "install" flow covers everything the AppImage
can do. The helper is bundled inside the AppImage under
`usr/share/deckd/integration/` and attached to the release next to the
AppImage, so no asset needs a separate download path.

### deb/rpm stay as a later, thin wrap of the same tree

A `.deb`/`.rpm` does not change the payload; it only moves the root step into
maintainer scripts and gives package-managed uninstall. That is worth having,
but it is a wrapper over the same relocatable tree, not a competing design.
Deferred until the AppImage path is proven on real hardware.

## Relationship to the substrate

All channels share Phase 0 of #168:

1. a build recipe that assembles the runtime + client + layouts into a
   relocatable tree;
2. a first-run/install script that performs the privileged + user-level
   integration;
3. docs.

The channel is a thin skin over that tree. AppImage is simply the first skin.

## Resolved sub-decisions (2026-09-25)

- **Runtime**: PyInstaller `onedir`, reusing the #165 macOS spec shape; the
  AppDir wraps the `onedir` output. Parity with macOS wins over avoiding the
  freezer's edge cases (aiohttp, dbus).
- **Helper UX**: a shell script run with `sudo` — transparent,
  headless-friendly, no PolicyKit dependency. It prints every change it makes
  and ships a matching uninstall.
- **Focus watcher + autostart**: the helper auto-installs both, detecting
  GNOME vs KDE and writing `~/.config/autostart/deckd.desktop`. The AppImage
  itself never silently writes into the user's shell.
- **Arch**: **x86_64 + aarch64** from the start. aarch64 has no
  `evdev-binary` wheel, so the daemon's `uinput` extra falls back to the
  sdist `evdev` and CI source-builds it before freezing.

## Consequences

- The Linux artifact is one AppImage file, attached to a GitHub release by a
  workflow that mirrors `release-macos.yml` and reuses the `DECKD_VERSION`
  seam from #165.
- The root step is explicit and documented rather than hidden in a package
  manager; users on AppImage grant it once with a `sudo` prompt.
- Flatpak/Snap are off the table, so no manifest or portal work is spent on a
  model that cannot work.
- The relocatable tree + integration helper are the reusable asset; deb/rpm
  and any future channel build on them without touching the payload.
