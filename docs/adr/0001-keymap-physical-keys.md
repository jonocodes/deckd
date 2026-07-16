# Key strings in config map to physical evdev keycodes, not characters

Config key strings (e.g. `ctrl+t`) are parsed as physical evdev key names (`KEY_LEFTCTRL` + `KEY_T`), with no keymap translation. This works correctly for almost all shortcuts because applications bind shortcuts to physical key positions, not to characters.

## Consequence

On non-QWERTY layouts (e.g. Colemak), a config entry `key: "ctrl+t"` still fires `KEY_T` — the physical T-key — which may or may not be where `t` lives on that layout. Users on alternative layouts may need to specify the physical key they want rather than the character they see.

## Considered options

- **Translate through the active keymap** — map the character `t` to whatever physical key produces it under the current layout. Correct for character-based shortcuts; adds a dependency on keymap introspection (e.g. `xkbcommon`).
- **Physical keycodes (chosen)** — simpler, no runtime keymap lookup, correct for the common case where shortcuts are layout-independent.

## Status

Accepted, but revisit if Colemak or other non-QWERTY usage proves painful. The fix would be an optional `keymap: physical | character` config field defaulting to `physical`.
