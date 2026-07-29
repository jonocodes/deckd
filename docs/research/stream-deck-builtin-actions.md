# Elgato Stream Deck — Built-in Action Types

> Research compiled 28 July 2026 against Elgato's official help center, SDK docs,
> Explorer articles, and Stream Deck 6.x / 7.x release notes.
>
> Scope: actions the **Stream Deck app itself** ships in the action list (i.e.
> what a user sees without installing any Marketplace / third-party plugin).
> Where I could not verify a specific action by name from an official source I
> say so explicitly.

---

## TL;DR for deckd

deckd's current surface (`key`, `shell`, `dbus`, `terminal`) is *much* smaller
than the built-in Stream Deck surface. The Elgato app's action panel groups
things into categories; the deckd-equivalent comparison is roughly:

| deckd action | Closest Stream Deck built-in | Notes |
|---|---|---|
| `key` (keystroke) | **System → Hotkey** | Same idea. Hotkey in Stream Deck also has a preset selector for common OS shortcuts. |
| `shell` (subprocess) | **System → Open Application** (best fit) or via **Text → Simulate Typing** for interactive apps | Not a 1-to-1 match. Open Application is the user-facing equivalent of "run this app" and in 7.0 got a green running-indicator and long-press-to-close/force-quit. |
| `dbus` (D-Bus call) | *(no built-in)* | Not exposed in Stream Deck's default actions. Plugins like the Linux community `StreamDeck-D-Bus` exist but are not first-party. |
| `terminal` (open a terminal emulator) | *(no built-in)* | Not in the default action list; users achieve this via Open Application + a `.desktop` entry, or via Hotkey + a terminal hotkey. |

The biggest gaps in deckd vs. the Stream Deck built-in surface are:

- **Profiles / Smart Profiles** — automatic profile switching per focused app.
- **Pages / Folders / Pinned Actions** — nested layouts and "always-there" keys.
- **Multi Action / Key Logic / Random Action / Delay** — flow-control actions that
  turn one key into a sequence, a 3-mode press-detector, or a randomised pick.
- **Switch Profile** — jump to another profile from a key.
- **Soundboard (Play Audio)** — first-class audio playback with playback modes
  (Play/Stop, Play/Overlap, Play/Restart, Loop/Stop), volume, fades, output
  routing.
- **Open Website / Website** — URL launcher with browser picker.
- **Text** — typed-text with two modes (Simulate Typing, Paste from Clipboard).
- **Virtual Stream Deck / Toggle Virtual Stream Deck** — on-screen virtual keypads.
- **Action Sharing / Pin Action / Background / Screensaver** — non-runtime
  affordances the app exposes.

Twitch / OBS / Streamlabs / Sound Decibel / Discord / Spotify / Wave Link / Voice
Focus / Camera Hub / Control Center / Key Light / etc. **are not built-in
actions** — they are distributed as separate plugins (many are first-party Elgato
plugins available on the Marketplace; several are bundled with the app install
historically, but they are conceptually plugins). This is the single most
important distinction when comparing "built-in" to third-party.

---

## 1. Categories present in the actions panel

These are the categories Elgato uses to group actions inside the action list
(verified from Elgato's own Explorer how-to articles, which direct users to
"find **Category X** in the action list"):

1. **Multi Action** — composite / flow-control actions.
2. **System** — Hotkey, Hotkey Switch, Open Application, Open Website / Website,
   Text, plus the navigation/profile actions and the Soundboard family's
   Play Audio.
3. **Soundboard** — its own category introduced for built-in audio playback.
4. **Dials** — Stream Deck + dial-specific actions (Action Trigger, Action
   Wheel, Dial Stacks).
5. *(per-plugin)* — Twitch, OBS Studio, Wave Link, Discord, Spotify, Camera
   Hub, Control Center, etc. appear under their plugin's category once
   installed.

Source: `https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-use-multi-actions/`
("Find the **Multi Action** category in the action list") and
`.../how-to-set-up-stream-deck-hotkeys/` ("find **System**"), and
`.../how-to-set-up-a-soundboard/` ("find the **Soundboard** section"),
`.../randomize-actions-on-stream-deck/` ("look under the **Multi Action**
category. … drag **Random Action**").

---

## 2. Verified built-in actions

Every entry below cites the source that names the action.

### Multi Action (composite / flow-control)

| Action | Description | Source |
|---|---|---|
| **Multi Action** | Run a fixed sequence of actions on a single key press; supports per-step delays. | [Explorer: How to Use Multi Actions](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-use-multi-actions/) |
| **Delay** | A standalone delay action (in ms) inserted between steps in a Multi Action. | [Explorer: Multi Action delays section](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-use-multi-actions/) |
| **Key Logic** *(added Stream Deck 7.0)* | Three slots on one key: **press / double-press / press-and-hold**. | [7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes); [Explorer: Key Logic](https://www.elgato.com/us/en/explorer/products/stream-deck/key-logic-stream-deck/) |
| **Random Action** | Picks one action from a configured pool at random each tap. | [Explorer: Randomize Actions](https://www.elgato.com/us/en/explorer/products/stream-deck/randomize-actions-on-stream-deck/) |

### System

| Action | Description | Source |
|---|---|---|
| **Hotkey** | Sends a keyboard shortcut; in 7.0+ it gained preset selectors for common OS shortcuts (copy, paste, screenshot, etc.). | [7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes); [Explorer: Hotkeys](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-set-up-stream-deck-hotkeys/) |
| **Hotkey Switch** | Sends one of two hotkeys depending on current state (two-state toggle for keyboard shortcuts). | [Explorer: Hotkeys — "How to add a Hotkey Switch"](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-set-up-stream-deck-hotkeys/) |
| **Open Application** | Launch an installed application from a searchable list; 7.0 added a green "running" indicator dot and long-press = do nothing / close / force-quit. | [6.9 release notes](https://help.elgato.com/hc/en-us/articles/34904105205777-Elgato-Stream-Deck-6-9-Release-Notes); [7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes) |
| **Open Website** / **Website** | Open a URL; 6.9 added a browser picker. | [6.9 release notes](https://help.elgato.com/hc/en-us/articles/34904105205777-Elgato-Stream-Deck-6-9-Release-Notes); [7.4 release notes](https://help.elgato.com/hc/en-us/articles/45347482546193-Elgato-Stream-Deck-7-4-Release-Notes) (cites "**Website** action") |
| **Text** | Type a string. Two modes: **Simulate Typing** (keystrokes) and **Paste from Clipboard** (single-paste; default in 6.9+). | [6.9 release notes](https://help.elgato.com/hc/en-us/articles/34904105205777-Elgato-Stream-Deck-6-9-Release-Notes) |
| **Switch Profile** | Jump to a different profile by name. | [7.4 release notes](https://help.elgato.com/hc/en-us/articles/45347482546193-Elgato-Stream-Deck-7-4-Release-Notes) — "nested Switch Profile actions inside a Multi Action could lose their internal references". Also referenced in the [SDK Profiles guide](https://docs.elgato.com/streamdeck/sdk/guides/profiles). |
| **Back to Profile** / "Auto Software Detection back-to-profile" action | Switch back to the previous profile after auto-switching. | [7.3 release notes](https://help.elgato.com/hc/en-us/articles/44411141578001-Elgato-Stream-Deck-7-3-0-Release-Notes) — "the **Auto Software Detection back-to-profile action**" |
| **Toggle Virtual Stream Deck** | Toggle an on-screen virtual Stream Deck window. | [7.4 release notes](https://help.elgato.com/hc/en-us/articles/45347482546193-Elgato-Stream-Deck-7-4-Release-Notes) — "Toggle Virtual Stream Deck key could appear visually stuck" |
| **Folder** | Opens a sub-layout (can be nested). Supports per-folder auto-exit (up to 60s). | [Explorer: Folders](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-use-folders-stream-deck/) |

> **Note on categories that I could *not* verify as containing specific built-in
> named actions in current 7.x:** Stream Deck's product page advertises per-app
> behaviour for audio, brightness, date/time, mic mute, sleep, etc., but those
> examples in Elgato's marketing copy refer to what users can build with
> plugins or Hotkeys — there is **no first-party built-in action called "Mic
> Mute", "Sleep", "Brightness Up", "Date/Time", or "Do Not Disturb"** in any
> release note I've found. (The closest is the **Toggle Virtual Stream Deck**
> action; mic/sleep/brightness controls are typically done with a hotkey or the
> Volume Controller / Wave Link / Camera Hub / Control Center plugins.)
>
> Default profiles ship with hotkeys for "screenshots, changing volume,
> opening apps" — these are **Hotkey / Open Application** actions, not separate
> dedicated categories. (See 6.6 beta changelog, "Default Profiles" section.)

### Soundboard

| Action | Description | Source |
|---|---|---|
| **Play Audio** | Plays an audio file from a key. Supports playback modes **Play/Stop, Play/Overlap, Play/Restart, Loop/Stop**; per-action volume, fade-in/out / fade-in&out (1–5s); on Windows, per-action output device. Supports MP3, WAV, FLAC, M4A (WAV recommended). | [Explorer: How to Set Up a Soundboard on Stream Deck](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-set-up-a-soundboard/) |

### Dials (Stream Deck + only)

| Action | Description | Source |
|---|---|---|
| **Action Trigger** | Assign up to 3 key actions to a dial, triggered by clockwise / counter-clockwise rotation / press. | [6.8 release notes](https://help.elgato.com/hc/en-us/articles/29844501142801-Elgato-Stream-Deck-6-8-Release-Notes) |
| **Action Wheel** | Radial menu on the touchscreen around a dial. | [Explorer / Help center article "Action Wheel"](https://help.elgato.com/hc/en-us/articles/28742375481997-Elgato-Stream-Deck-Action-Wheel) |
| **Dial Stack** | Stack multiple dial actions so a single dial controls several settings. | [Help center "Dial Stacks"](https://help.elgato.com/hc/en-us/articles/10843581380109-Elgato-Stream-Deck-Dial-Stacks) |

> Other dial actions are provided per-plugin (e.g., Wave Link's dial
> controls) — they're not in the default "Dials" section.

---

## 3. Layout / profile concepts (not actions, but worth knowing)

These are *features* the app exposes; they're configured in the Preferences
window and don't appear as draggable actions on a key:

| Concept | What it does | Source |
|---|---|---|
| **Profiles** | Per-device layout sets. Switchable manually or automatically. | [SDK Profiles guide](https://docs.elgato.com/streamdeck/sdk/guides/profiles); [Elgato product page "Profiles" comparison row](https://www.elgato.com/us/en/p/stream-deck) |
| **Smart Profiles** | Auto-switch the active profile based on the focused app. Per-profile → "Application" dropdown. | [Explorer: Smart Profiles](https://www.elgato.com/us/en/explorer/products/stream-deck/smart-profiles-stream-deck/) |
| **Pages** | Multiple pages of keys per profile (think multiple Stream Decks in one). | [Elgato product page comparison table](https://www.elgato.com/us/en/p/stream-deck) |
| **Folders** | Nested sub-layouts (a key opens a new key grid). | [Explorer: Folders](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-use-folders-stream-deck/) |
| **Pinned Actions** | Right-click → Pin Action. Pinned to a key position across all pages/folders in the same profile. | [6.6 beta changelog](https://help.elgato.com/hc/en-us/articles/25430103180557-Stream-Deck-6-6-Beta-Changelog); [Explorer: Pinned Actions](https://www.elgato.com/us/en/explorer/products/stream-deck/pinned-actions-stream-deck/) |
| **Key Logic (single key, multi-mode)** | Distinct from the "Key Logic" action above — refers to the *key press behaviour* (single press, double press, press-and-hold) that any action can be configured to respond to. Elgato's product page and 7.0 release notes describe this as the same capability surface. | [Elgato product page "Key Logic" row](https://www.elgato.com/us/en/p/stream-deck); [7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes) |
| **Multi-state actions** | Two-state (on/off) actions are supported via the manifest; e.g., Mute/Unmute. | [SDK Keys guide — Multi-State Keys](https://docs.elgato.com/streamdeck/sdk/guides/keys#multi-state-keys) |
| **Property Inspectors** | Per-action configuration UI panels shown beneath the canvas. | [SDK Property Inspectors guide](https://docs.elgato.com/streamdeck/sdk/guides/ui); called "property inspector" in Elgato Explorer articles |
| **Background / Wallpaper** | Per-page background image for keys; per-device screensaver (PNG / GIF / BMP / WEBP / Animated WEBP, 144×144 for keys). | [6.6 beta changelog "Per Page Backgrounds" / "Animated Screensaver"](https://help.elgato.com/hc/en-us/articles/25430103180557-Stream-Deck-6-6-Beta-Changelog); [Explorer: Background and Screensaver](https://www.elgato.com/us/en/explorer/products/stream-deck/how-to-add-a-background-and-screensaver/) |
| **Boot Logo** | Custom logo shown when Stream Deck starts. | [6.6 beta changelog](https://help.elgato.com/hc/en-us/articles/25430103180557-Stream-Deck-6-6-Beta-Changelog) |
| **Action Sharing** | Right-click an action → export as a single file; drag/drop or right-click → import. | [6.8 release notes](https://help.elgato.com/hc/en-us/articles/29844501142801-Elgato-Stream-Deck-6-8-Release-Notes) |
| **Copy / Paste Pages** | Copy entire pages; copy folder → paste as page, copy page → paste as folder. | [6.6 beta changelog](https://help.elgato.com/hc/en-us/articles/25430103180557-Stream-Deck-6-6-Beta-Changelog) |
| **Virtual Stream Deck** *(7.0+)* | Unlimited on-screen virtual keys; toggle via **Toggle Virtual Stream Deck** action. | [7.0 release notes](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes); [7.4 release notes](https://help.elgato.com/hc/en-us/articles/45347482546193-Elgato-Stream-Deck-7-4-Release-Notes) |
| **Action Wheel** | A dial touchscreen action that opens a radial menu of key actions. | [Help center "Action Wheel"](https://help.elgato.com/hc/en-us/articles/28742375481997-Elgato-Stream-Deck-Action-Wheel) |

---

## 4. Things commonly *thought* to be built-in but actually shipped as plugins

These appear in the actions panel of a typical installation but are **separate
plugins** (most are first-party Elgato plugins distributed via the in-app
Marketplace / bundled with the installer; historically many were bundled
together — see e.g. the 7.1 release note: *"The Volume Controller plugin is no
longer bundled by default"*).

| Action group | Plugin | Source |
|---|---|---|
| OBS Studio scene/source controls | **OBS Studio** plugin | [Marketplace listing referenced in 6.9 beta notes](https://marketplace.elgato.com/product/obs-studio-35615969-830f-45c9-ba0a-1a295bba7fec) |
| Streamlabs scene/source controls | **Streamlabs Desktop** plugin (split out from built-in in 6.9) | [6.9 release notes](https://help.elgato.com/hc/en-us/articles/34904105205777-Elgato-Stream-Deck-6-9-Release-Notes) — "**Streamlabs Desktop** actions are now a plugin" |
| Twitch stream/chat/viewer controls | **Twitch** plugin | [Explorer: Twitch article](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) (referenced) |
| YouTube live controls | **YouTube** plugin | [6.8 release notes — "Improved the YouTube account connection"](https://help.elgato.com/hc/en-us/articles/29844501142801-Elgato-Stream-Deck-6-8-Release-Notes) |
| System volume / mute | **Volume Controller** plugin (no longer bundled by default in 7.1) | [7.1 release notes](https://help.elgato.com/hc/en-us/articles/41533810232721-Elgato-Stream-Deck-7-1-Release-Notes) |
| Discord mute / cam / push-to-talk / status | **Discord** plugin | [Explorer: Discord article](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) |
| Spotify play/pause / volume | **Spotify** plugin | [Explorer: Spotify article](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) |
| Audio / microphone routing | **Wave Link** plugin | [7.3 release notes — "Wave Link 3.0 Plugin"](https://help.elgato.com/hc/en-us/articles/44411141578001-Elgato-Stream-Deck-7-3-0-Release-Notes) |
| Camera (Facecam) controls | **Camera Hub** plugin | [Explorer: Camera Hub / Adobe article](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) |
| Lights (Key Light) controls | **Control Center** plugin | [Explorer: Lighting article](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) |
| Weather data | **Weather** plugin | [7.0 release notes — "Weather plugin - stay ahead of the forecast"](https://help.elgato.com/hc/en-us/articles/38011940576273-Elgato-Stream-Deck-7-0-Release-Notes) |
| Adobe Photoshop controls | **Photoshop** plugin | [Explorer: Adobe plugin](https://www.elgato.com/us/en/explorer/products/stream-deck/stream-deck-plugins-for-streaming/) |
| Time zones display | **Clocks** plugin | [Elgato product page "Time Zones at a Glance"](https://www.elgato.com/us/en/p/stream-deck) |
| AI prompt / MCP server control | **MCP Deck** (virtual device) | [7.4 release notes — "Added Model Context Protocol (MCP)"](https://help.elgato.com/hc/en-us/articles/45347482546193-Elgato-Stream-Deck-7-4-Release-Notes) |

> **Rule of thumb:** if the help center article says "the `<X>` plugin" or "the
> `<X>` actions", it's a plugin, not a built-in action. Built-in actions are
> the ones described as "the `<X>` action" (singular, generic noun, no plugin
> qualifier).

---

## 5. Notes on concepts the user asked about

| Concept | Stream Deck built-in? | Notes |
|---|---|---|
| **Long press / hold** | Yes — multi-state, Key Logic's "press and hold" slot, and per-action long-press options (e.g., Open Application's long-press-to-close). | 7.0 release notes; Explorer Key Logic |
| **Folders (nested pages)** | Yes — Folder action. | Explorer Folders article |
| **Multi Actions (chained)** | Yes — Multi Action category. | Explorer Multi Actions article |
| **Toggle actions (two-state)** | Yes — actions can declare up to 2 states (e.g., Mute/Unmute) and toggle automatically on press. | SDK Keys — Multi-State Keys |
| **Property inspectors** | Yes — every action with settings has one (UI shown in the Stream Deck app beneath the canvas). | SDK Property Inspectors guide; Explorer articles refer to "property inspector" generically |
| **Smart Profiles** | Yes — auto-switch profiles per focused app. | Explorer Smart Profiles |
| **Custom icons / Multi-state** | Yes — user can upload / create custom icons per key, and configure a per-state icon. | Explorer: Customise with Icons; SDK Keys (states) |
| **GIFs / Images** | Yes — PNG/JPEG/GIF/BMP/WEBP/Animated WEBP supported as icons and screensavers; 144×144 per key. | Explorer: Customise with Icons |
| **Media controls (play/pause, next, etc.)** | **No first-party built-in.** The 7.4 release notes mention a "play/pause action on the Stream Deck XL default profile" — that refers to a *default-profile* key bound via Hotkey or by a plugin, not a dedicated built-in Media category. Confirmed no separate Media action category in any source. | 7.4 release notes (cites the icon of a "play/pause action" on the default profile but no dedicated category) |
| **Voice / Speech (TTS, voice commands)** | No first-party built-in. Community plugins exist on the Marketplace. | Inferred from absence in release notes and Explorer articles |
| **Timer / Delay (as a top-level action)** | Delay exists **inside** Multi Action only — not a standalone "Timer" action in the actions panel. The Soundboard's playback modes give time-based behaviour (loop / fade) but there is no general "wake me up in N seconds" action. | Explorer Multi Actions |
| **Date/Time** | No dedicated built-in. Clocks / Weather are Marketplace plugins. | Explorer Clocks article (treated as a plugin example) |
| **Mic mute / Audio mute** | No first-party built-in named "Mute". The Volume Controller plugin covers this. | 7.1 release notes ("Volume Controller plugin… no longer bundled by default") |
| **Brightness / Do Not Disturb / Sleep / Power** | No first-party built-in named actions. Typically done via Hotkey + OS shortcut, or via Control Center plugin (for Elgato Key Light brightness). | Inferred from absence in release notes; Control Center article exists |
| **GIFs as a category** | GIFs are a supported icon format, not an action category. | Explorer: Customise with Icons |
| **Twitch** | Plugin, not built-in. | Explorer: Twitch article |

---

## 6. Sources

Primary (Elgato-owned):

- SDK guides:
  - Actions — https://docs.elgato.com/streamdeck/sdk/guides/actions
  - Keys (Multi-State, States in Multi-Actions) — https://docs.elgato.com/streamdeck/sdk/guides/keys
  - Profiles — https://docs.elgato.com/streamdeck/sdk/guides/profiles
  - System (openUrl, onSystemDidWakeUp) — https://docs.elgato.com/streamdeck/sdk/guides/system
  - Property Inspectors — https://docs.elgato.com/streamdeck/sdk/guides/ui
- Stream Deck release notes (Elgato help center, `help.elgato.com`):
  - 7.5.0 — 48328697898897
  - 7.4.2 — 46818420770321
  - 7.4 — 45347482546193
  - 7.3.0 — 44411141578001
  - 7.1 — 41533810232721
  - 7.0.3 — 40016247300369
  - 7.0 — 38011940576273
  - 6.9 — 34904105205777
  - 6.8 — 29844501142801
  - 6.8 Beta — 31091417097485
  - 6.6 Beta — 25430103180557
- Explorer how-to articles (`elgato.com/us/en/explorer/products/stream-deck/`):
  - How to Use Multi Actions — `how-to-use-multi-actions`
  - How to Set Up Stream Deck Hotkeys — `how-to-set-up-stream-deck-hotkeys`
  - How to Use Key Logic — `key-logic-stream-deck`
  - How to Set Up a Soundboard — `how-to-set-up-a-soundboard`
  - How to Play Sounds Through Your Mic — `how-to-play-sounds-through-your-mic-stream-deck`
  - How to Randomize Actions — `randomize-actions-on-stream-deck`
  - Pinned Actions — `pinned-actions-stream-deck`
  - Folders — `how-to-use-folders-stream-deck`
  - Smart Profiles — `smart-profiles-stream-deck`
  - Customise with Icons and Icon Packs — `customize-stream-deck-with-icons-and-icon-packs`
- Product / marketing:
  - Stream Deck product page — `elgato.com/us/en/p/stream-deck` (Software comparison table naming Multi Actions, Pages, Folders, Key Logic, Profiles, Plugins, Virtual Stream Deck)
  - Explore Stream Deck — `elgato.com/us/en/s/explore-stream-deck`

Secondary (corroborating, non-Elgato):

- Wikipedia: Elgato — `https://en.wikipedia.org/wiki/Elgato#Stream_Deck`
- GitHub: `elgatosf/streamdeck-plugin-samples` (samples; not authoritative for built-ins, but confirms SDK structure)

---

## 7. Confidence / what's still uncertain

**High confidence (named in official Elgato source):**

- The full Multi Action category (Multi Action, Delay, Key Logic, Random Action).
- Hotkey + Hotkey Switch in the System category.
- Open Application, Open Website / Website, Text (Simulate Typing / Paste from Clipboard).
- Soundboard → Play Audio with its playback modes.
- Folder as a standalone action.
- Switch Profile and "back to profile" actions.
- Toggle Virtual Stream Deck.
- All listed Dials-category actions (Action Trigger, Action Wheel, Dial Stacks).
- Profile / Page / Pinned Action / Smart Profile concepts.

**Medium confidence (inferred from default-profile descriptions + release-note
bug-fix references, but I never saw a screenshot of the actions panel itself):**

- The full ordering and exact names of items in the "System" category beyond
  the ones explicitly named in release notes (e.g., whether "Date/Time" or
  "Brightness" appear as separate items, or whether they're all just Hotkeys
  with no dedicated slot).

**Low confidence / *not* built-in (verified by absence):**

- There is **no dedicated "Media" category**; "play/pause" in the default
  profile is achieved via Hotkey or plugin.
- There is **no built-in "Mic Mute", "Sleep", "Brightness", "Do Not Disturb",
  "Date/Time", "Voice" / "Text-to-Speech", or general "Timer"** action.
  These are plugin features (Volume Controller, Control Center, Clocks,
  Weather) or done via Hotkey.

The Zendesk-driven help-center search page is JS-rendered and not
indexable by static fetch, so the original catalog of articles (e.g., a
specific "Actions overview" page) was not directly readable. Most of the
above comes from the help-center article bodies, release-note bodies, and
the Elgato Explorer articles — all of which are Elgato-owned first-party
sources.