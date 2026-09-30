# Persistent chrome: bottom strip + right-side jogstrip

The client has a fixed chrome layer that is always visible regardless of which deck is active. It consists of:

- **Right side**: a full-height jogstrip (always-on scroll; can be suppressed per-deck with `jogstrip: false`)
- **Bottom strip**: app name, connection indicator, trackpad mode button, settings button

Per-app decks render in the remaining space and have no knowledge of the chrome.

Chosen over defining chrome elements per-deck because scroll and trackpad access are global needs — they should work regardless of which app is focused, without requiring every deck author to reserve space for them. The right-side placement gives the jogstrip full vertical extent, which improves scroll resolution compared to a bottom-strip placement.

## Consequences

- Deck grid coordinates are relative to the chrome-excluded area, not the full screen.
- The daemon does not need to know about chrome — it is purely a client-side concern.
- The `jogstrip: false` deck flag suppresses the persistent strip for decks that define their own full-width jogstrip or have no scrolling need.
