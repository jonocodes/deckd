# Future: dynamic widget state for MPRIS and runtime content

The current protocol is stateless per widget — the daemon pushes a full layout and the client renders it unchanged until the next layout push. This is intentional for v1 simplicity.

A planned future extension is runtime widget state updates: the daemon pushes delta updates to individual widget properties (label, icon, value) without replacing the whole layout. The primary driver is MPRIS (`org.mpris.MediaPlayer2` on D-Bus) — showing currently playing track, artist, volume, and play/pause state on dedicated widgets.

## Protocol constraint

When extending the `layout` message or adding new message types for this feature, do not design in a way that forecloses per-widget state pushes. A likely shape:

```json
{ "type": "widget_state", "id": "now-playing", "label": "Bohemian Rhapsody", "icon": "pause" }
```

## Implementation notes (for when this is built)

- MPRIS2 interface: `org.mpris.MediaPlayer2.Player` on session D-Bus. Relevant properties: `PlaybackStatus`, `Metadata` (title, artist, album art URL), `Volume`.
- `dbus-fast` (already in the stack) supports property-change subscriptions via `PropertiesChanged` signals.
- Simple playback control (`play-pause`, `next`, `previous`) already works today via `action: { shell: "playerctl ..." }` — no daemon changes needed for that subset.
