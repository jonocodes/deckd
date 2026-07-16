# Orientation: scaling grid, not locked to portrait

The PWA manifest does not lock orientation. The client grid scales to fill the available space after subtracting chrome in whatever orientation the device is held — the same `[x, y, w, h]` coordinates are used in both orientations; cells simply resize proportionally.

Chosen over locking to portrait because both orientations are a desired end state. Chosen over immediate separate portrait/landscape layout variants because scaling covers most cases without requiring every layout to define two grids.

## Future extension

When orientation-specific arrangements are needed, add optional `portrait:` / `landscape:` blocks to the layout YAML. The client picks the matching block if present, falls back to the root widget list if not. The grid coordinate system must remain compatible with this — no assumptions about aspect ratio should be baked into coordinate semantics.
