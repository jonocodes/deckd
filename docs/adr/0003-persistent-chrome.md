# Persistent chrome: bottom strip + right-side jogstrip

The client has a fixed chrome layer that is always visible regardless of which layout is active. It consists of:

- **Right side**: a full-height jogstrip (always-on scroll; can be suppressed per-layout with `jogstrip: false`)
- **Bottom strip**: app name, connection indicator, trackpad mode button, settings button

Per-app layouts render in the remaining space and have no knowledge of the chrome.

Chosen over defining chrome elements per-layout because scroll and trackpad access are global needs — they should work regardless of which app is focused, without requiring every layout author to reserve space for them. The right-side placement gives the jogstrip full vertical extent, which improves scroll resolution compared to a bottom-strip placement.

## Consequences

- Layout grid coordinates are relative to the chrome-excluded area, not the full screen.
- The daemon does not need to know about chrome — it is purely a client-side concern.
- The `jogstrip: false` layout flag suppresses the persistent strip for layouts that define their own full-width jogstrip or have no scrolling need.
