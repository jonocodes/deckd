# Orientation: scaling grid, not locked to portrait

The PWA manifest does not lock orientation. The client grid scales to fill the available space after subtracting chrome in whatever orientation the device is held.

Layouts are authored in **landscape orientation** (the natural shape of the chrome-excluded area on a horizontally-held phone or tablet). When the viewport is in **portrait**, the client **transposes** every widget's grid coordinates diagonally: `[x, y, w, h] → [y, x, h, w]`. A layout authored as 4×2 (four buttons across, two rows down) renders as 2×4 in portrait — same button count, same relative arrangement, cells sized for the taller-than-wide surface.

Chosen over locking to portrait because both orientations are a desired end state. Chosen over pure proportional scaling (an earlier draft of this ADR) because a 4-wide grid on a portrait phone gives buttons that are too narrow to tap accurately — the transpose keeps individual cell aspect ratios roughly square in both orientations. Chosen over immediate separate portrait/landscape layout variants because auto-transpose covers the common case without requiring every layout to author two grids.

## Future extension

When a layout wants orientation-specific arrangements that the auto-transpose can't express (e.g. a portrait grid with a different button set, not just a rotated one), add optional `portrait:` / `landscape:` blocks to the layout YAML. The client picks the matching block if present, falls back to the auto-transpose from the root widget list if not. The grid coordinate system must remain compatible with this — no assumptions about aspect ratio should be baked into coordinate semantics.
