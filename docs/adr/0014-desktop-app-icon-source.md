# Opt-in `desktop` icon source: the daemon serves host app icons

A deck author can now write `icon: { source: desktop, name: <desktop-id> }`
to show an app's own full-colour icon (the one the host's dock shows) next to
Lucide glyphs and Simple Icons logos (issue #187). The daemon resolves the id
from the host's freedesktop data: the app's `.desktop` file, then its `Icon=`
key, then a file in the `hicolor` icon theme or `pixmaps/`. It serves the
file at `GET /desktop-apps/<id>/icon`. `GET /desktop-apps` lists installed
apps for the editor's icon picker. This **partially reverses ADR-0007**
("the daemon does not resolve app icons from `.desktop` files") and
**amends ADR-0006** (all sets monochrome and `currentColor`; daemon-served
icons deferred).

## Why reverse ADR-0007

ADR-0007 declined `.desktop` resolution because it made the daemon an asset
resolver and host, and because a Simple Icons slug in YAML already covered
the need. In practice Simple Icons misses many desktop apps: Tilix, most
GNOME apps, in-house tools. Its logos are also generic monochrome marks
rather than the icons users recognise from their own desktop. The cost
ADR-0007 named (a second daemon-served asset surface) already exists as the
album-art proxies, so this reuses that shape rather than inventing one.

## What stays from ADR-0007: opt-in, never automatic

ADR-0007's real concern was presentation silently derived by the daemon.
That still holds. `desktop` is **only ever an explicit author choice** in
YAML or the picker. The daemon never applies a host icon on its own:
running-windows rows, the badge fallback and Now Playing are unchanged. The
shipped decks, demo fixtures and docs screenshots keep their bundled icons.
Any automatic use would need its own decision, and a client setting that is
off by default.

## Decisions

- **Pure-Python resolver, `hicolor` only.** No PyGObject / Gtk, which would
  weigh down the AppImage / tarball. It searches `XDG_DATA_HOME` and
  `XDG_DATA_DIRS`, plus the Flatpak exports and Nix profile dirs, which
  trimmed environments (systemd user units, the AppImage) often drop.
  Lookup prefers `scalable` SVG, then the largest PNG, then `pixmaps/`.
  Symbolic icons are never chosen. The user's selected icon theme is not
  consulted: an app's own `hicolor` icon is the stable, recognisable one.
- **Index-keyed serving.** The icon route only serves ids the resolver
  indexed, so a client string never becomes a filesystem path. The route is
  unauthenticated like the art proxies (an `<img>` can't carry the password
  header). Icons come from whatever is installed, so responses carry a
  sandboxing CSP and `nosniff`: an SVG opened top-level on the daemon origin
  must not run script that could read the stored password. The app list is
  authenticated, like the editor's other reads.
- **Full colour, ignores `currentColor`.** These icons render as `<img>`
  and keep their own colours on any button `color`. In the badge they skip
  the themed disc that monochrome glyphs sit in. Some app icons are dark and
  lose contrast on the dark buttons. Fixing that, by picking a lighter
  button `color` or a different icon, is the author's job, as with every
  other `color` choice (ADR-0006).
- **Portability is the author's trade.** A deck naming a `desktop` icon
  depends on that app being installed on the host. On a host without it,
  the client shows the standard missing-icon placeholder, never an error.
  macOS and Windows resolve nothing today, so the picker's Apps tab is
  empty there.
