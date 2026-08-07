# macOS system-wide "now playing" — read & control without a private entitlement

> Research spike for [issue #56](https://github.com/jonocodes/deckd/issues/56) —
> the macOS sibling of the Linux MPRIS media feature ([#46](https://github.com/jonocodes/deckd/issues/46)).
> Compiled 2026-08-06 against Apple Developer docs, the two candidate helper
> tools' GitHub repos (READMEs / issues / commit history), and first-hand
> breakage reports. Where a claim is version-specific I say exactly which macOS
> version it holds on.
>
> Scope: can a **Python daemon** on **modern macOS (2026)** READ and CONTROL
> whatever is currently playing **system-wide**, with **no private Apple
> entitlement**? Ranks the viable paths and gives a build-or-drop call.

---

## Bottom line up front

**Build — but shell out to `ungive/mediaremote-adapter`; do not talk to MediaRemote directly.** Direct MediaRemote reads are dead without an entitlement since macOS 15.4 (`MRMediaRemoteGetNowPlayingInfo` returns `Operation not permitted`, [`kMRMediaRemoteFrameworkErrorDomain` Code=3](https://github.com/aviwad/LyricFever/issues/94)). The entitlement-free path that still works on 15.4 through macOS 26 ("Tahoe") is the adapter's trick of running the read through `/usr/bin/perl`, which the system reports with a `com.apple.*` bundle id and therefore treats as entitled ([mediaremote-adapter README](https://github.com/ungive/mediaremote-adapter)). It is actively maintained (releases through **v0.7.6, May 2026**) and its read core is already vendored into `nowplaying-cli`, which tests green on **Sequoia 15.7 and Tahoe 26.3** ([nowplaying-cli README](https://github.com/kirtan-shah/nowplaying-cli/blob/main/README.md)). This is a genuinely moving target, so isolate it behind the existing `MprisBackend` seam and treat the helper as a swappable dependency.

---

## Path ranking

| # | Path | Verdict | Evidence |
|---|------|---------|----------|
| **a** | **Direct MediaRemote (pyobjc/ctypes), no entitlement** | **Dead for READ; still fine for SEND** | Since macOS 15.4 `mediaremoted` verifies an entitlement on the *read* side. `MRMediaRemoteGetNowPlayingInfo` returns `Operation not permitted` for unentitled callers ([LyricFever #94](https://github.com/aviwad/LyricFever/issues/94)). `MRMediaRemoteSendCommand` (play/pause/next) is **not** gated and still works unentitled ([issue #94](https://github.com/aviwad/LyricFever/issues/94)). But a media backend that can control-but-not-read is useless, so this path fails as a whole. |
| **b** | **Shell out to a maintained helper (`mediaremote-adapter` / `nowplaying-cli`)** | **Viable — recommended** | The adapter runs the read via `/usr/bin/perl` (bundle id `com.apple.perl5`), which the entitlement check accepts; no app entitlement, **no SIP change** ([adapter README](https://github.com/ungive/mediaremote-adapter)). Supports one-shot `get`, live `stream` (JSON, with diffing), and playback commands. Actively maintained; `nowplaying-cli` vendors this core and tests on 15.7 / 26.3. |
| **c** | **Per-app AppleScript (Music.app, Spotify)** | **Conditional — narrow fallback only** | Works today and needs zero private API, but is **per-app, not system-wide**: you must name each app and it only sees apps with a scripting dictionary. Reliability is spotty (Spotify's `current track` "has experienced breakage… may work randomly" — [Spotify community / node-applescript](https://github.com/andrehaveman/spotify-node-applescript)). Also triggers macOS Automation permission prompts. |
| **d** | **Not feasible** | **Rejected** | A read path that works unentitled through macOS 26 demonstrably exists (path b). |

---

## 1. Right target API — `MediaRemote`, not `MPNowPlayingInfoCenter`

The issue's framing is correct on both halves:

- **`MPNowPlayingInfoCenter` (MediaPlayer.framework, public) is PUBLISH-side only — not what we need.** It is "an object for setting the Now Playing information for media that **your app** plays" ([Apple docs](https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter)). An app writes *its own* metadata into `default.nowPlayingInfo` so the system surfaces it on the Lock Screen / Control Center. There is no API on it to read *another* app's now-playing state. It is the mirror image of what deckd needs.

- **`MediaRemote.framework` (private, undocumented) is the system-wide read/control side.** It is the macOS analogue of the MPRIS session bus. The functions of interest, all confirmed as the ones the helper tools wrap:
  - `MRMediaRemoteGetNowPlayingInfo` — read title / artist / album / artwork / elapsed / playback state.
  - `MRMediaRemoteGetNowPlayingApplicationIsPlaying` — the playing/paused bit.
  - `MRMediaRemoteSendCommand` — transport (play/pause/next/previous/seek).
  - `kMRMediaRemoteNowPlayingInfoDidChangeNotification` — the `NSNotificationCenter`/Darwin-notification that fires on metadata change; this is what lets you avoid polling.

  These are private/undocumented — the canonical reference is community-reversed headers ([davidmurray/ios-reversed-headers `MediaRemote.h`](https://github.com/davidmurray/ios-reversed-headers/blob/master/MediaRemote/MediaRemote.h), cited directly in the adapter's own commit history). No Apple documentation exists for them, which is the root of the fragility.

**Also confirmed publish-side (Q5):** `MPRemoteCommandCenter` (MediaPlayer.framework, public) is where an app registers handlers to *receive* remote-control events for *its own* playback (Control Center, headphone buttons, CarPlay). It is a receive-commands-for-myself API, not a send-commands-to-others API. Like `MPNowPlayingInfoCenter`, it is the wrong side of the mirror for deckd.

## 2. The macOS 15.4 lockdown

**What changed:** With **macOS 15.4 (Sequoia, ~March 2025)** Apple added **entitlement verification inside the `mediaremoted` daemon**. Clients without the required entitlement are denied now-playing *reads* ([adapter README](https://github.com/ungive/mediaremote-adapter); corroborated across [LyricFever #94](https://github.com/aviwad/LyricFever/issues/94) and [nowplaying-cli #28](https://github.com/kirtan-shah/nowplaying-cli/issues/28)).

**Concrete symptom:** `MRMediaRemoteGetNowPlayingInfo` returns nil / errors with `Operation not permitted` — `Error Domain=kMRMediaRemoteFrameworkErrorDomain Code=3` — for unentitled processes. First reported on 15.3 and the 15.4 beta on M1 Pro / M4 hardware, [issue opened 2025-03-22](https://github.com/aviwad/LyricFever/issues/94).

**Read vs. control asymmetry (important):** The gate is on the **read** side only. `MRMediaRemoteSendCommand` / `MRMediaRemoteCommand` (pause/play/skip) **still work unentitled** on 15.4+ ([issue #94](https://github.com/aviwad/LyricFever/issues/94)). So the lockdown specifically kills the metadata read that a media widget is built around.

**Is an entitlement now required?** Effectively yes for direct reads — the accepted credential is a private `com.apple.*`-style entitlement / bundle identity that third-party apps cannot obtain. There is no public entitlement Apple will grant for this.

**State on later 15.x and macOS 26 (as of 2026):** The restriction persisted through the 15.x line and into **macOS 26 ("Tahoe")**. It has *not* been reverted. The practical evidence that the *adapter workaround* still functions on current releases: `nowplaying-cli` (which vendors the adapter's read core) lists "Tested and working on: … Sequoia 15.7; Tahoe 26.3" ([README](https://github.com/kirtan-shah/nowplaying-cli/blob/main/README.md)), and the adapter itself shipped **v0.7.6 in May 2026**. So: the direct path stays shut, and the perl-shim path stays open — for now.

**Is it a moving target?** Yes — see the risk section. Apple has tightened this once decisively (15.4) and the whole surface is undocumented private API, so future tightening is plausible and unannounced.

## 3. Helper tools — current working state

### `ungive/mediaremote-adapter` (the one that matters)

- **How it works now — the perl shim.** Verbatim mechanism: *"Processes with a bundle identifier starting with `com.apple.` are granted permission to access the MediaRemote framework."* The adapter invokes **`/usr/bin/perl`**, which the system reports with a `com.apple.*` bundle id (`com.apple.perl5`), so `mediaremoted`'s entitlement check passes. The perl process **dynamically loads a bundled helper framework** (`MediaRemoteAdapter.framework`) that does the actual MediaRemote calls and prints results (JSON) to stdout ([README](https://github.com/ungive/mediaremote-adapter)).
- **No SIP change, no app entitlement.** The README has no mention of disabling SIP, and the consuming app needs **no special entitlement** — the entitled `/usr/bin/perl` host does the privileged work. Contrast with `Mx-Iris/MediaRemoteWizard`, which injects into `mediaremoted` and **does require SIP disabled** — not acceptable for deckd.
- **Bundling requirement:** the framework must be **bundled but *not* linked against** — it is passed as a runtime argument to the perl script (`mediaremote-adapter.pl`), not loaded into your own process. This keeps *your* process unentitled and out of the enforcement path.
- **Capabilities:** `get` (one-shot metadata: title/artist/album/artwork/playback state/elapsed), `stream` (live JSON updates with optional diffing — the notification-driven path, no polling), and playback **commands** (play/pause/skip/seek/shuffle/repeat/speed).
- **Maintenance:** active. Releases **v0.7.4 (2026-05-01), v0.7.5 (2026-05-03), v0.7.6 (2026-05-11)**; substantive commits through May 2026 (e.g. dropping an unused JavaScriptCore link to cut dyld load time in the `com.apple.perl5` host). Explicitly claims "Fully functional MediaRemote access for **all versions of macOS**."
- **Known limitations:** artwork "often takes a bit of time to load and may not appear in all cases"; the `test` command can briefly inject a fake media entry that interferes with other MediaRemote consumers (don't run it in production).

### `kirtan-shah/nowplaying-cli`

- **Broke on 15.4.** [Issue #28 "nowplaying-cli no longer works on macOS 15.4"](https://github.com/kirtan-shah/nowplaying-cli/issues/28) was opened **2025-04-01**; it is now **closed**, and the same breakage hit sibling projects (boring.notch, BetterTouchTool's Now Playing).
- **Fixed by adopting the adapter's approach.** The repo now vendors the adapter's read core — the README states files under **`src/mediaremote-mini/` are derived from** the mediaremote-adapter project (BSD-3-Clause), and the acknowledgement credits `@ungive`. Commit "fix: load helper script and dylib from installed prefixes (#31)" (2026-04) wires the shim into the Homebrew install layout.
- **Current state:** commands `get`, `get-raw`, `play`, `pause`, `togglePlayPause`, `seek`, `next`, `previous`. "Tested and working on: … Sequoia 15.7; Tahoe 26.3." Carries the standard caveat: *"nowplaying-cli uses private frameworks, which may cause it to break with future macOS software updates."* ~289 stars, a few open issues; lighter-touch maintenance than the adapter it depends on.

**Takeaway:** both tools now rely on the *same* underlying `/usr/bin/perl` mechanism. `nowplaying-cli` is the friendlier CLI to shell out to; the adapter is the upstream source of truth and the one to track for breakage. deckd could depend on either, but should watch the adapter.

## 4. Direct Python access (pyobjc / ctypes)

- **Read: dead unentitled, post-15.4.** `dlopen`-ing `MediaRemote.framework` and calling `MRMediaRemoteGetNowPlayingInfo` from Python (pyobjc or ctypes) hits the exact same `mediaremoted` entitlement wall — because enforcement is in the daemon, not the framework binary, the calling language is irrelevant. Reports of `Operation not permitted` are from unentitled native and scripted callers alike ([issue #94](https://github.com/aviwad/LyricFever/issues/94)). A Python daemon has no way to present a `com.apple.*` identity, so direct read is not an option.
- **Send: still works.** `MRMediaRemoteSendCommand` from Python remains functional unentitled (same asymmetry as §2). But control without read doesn't make a usable widget.
- **Net:** the only way Python gets a read on 15.4+ is by *not* calling MediaRemote itself — i.e. spawning the entitled `/usr/bin/perl` host (path b). Direct pyobjc/ctypes is a non-starter for the read half.

## 5. Entitlement-free fallbacks

- **`MPRemoteCommandCenter` — publish/receive-side only.** Confirmed in §1: it registers *your app's* handlers for remote-control events; it cannot enumerate or drive other apps. Not usable as a system-wide controller.
- **Per-app AppleScript (Music.app, Spotify).** Real and entitlement-free, but structurally narrower than MPRIS/MediaRemote:
  - **Can:** read `player state`, `current track`'s name / artist / album / duration / artwork-url, and send play/pause/next/previous — *for a specifically named app* that exposes a scripting dictionary (Music, Spotify) ([node-applescript](https://github.com/andrehaveman/spotify-node-applescript); [AppleScript gist](https://gist.github.com/joshuaswilcox/7251527)).
  - **Can't:** discover "whatever is currently playing" system-wide. You must hardcode each app; browser-based players (YouTube in Safari/Chrome), Apple Podcasts quirks, and any non-scriptable player are invisible. Spotify's `current track` is documented as flaky/random after some updates.
  - **Cost:** each scripted app triggers a macOS Automation consent prompt (TCC).
  - **Role for deckd:** a documented, explicitly-narrower fallback for the two big players if the adapter path ever breaks — not the primary.

## "Moving target" risk assessment

**How much should deckd bet on this? A moderate, well-fenced bet — not a load-bearing one.**

- **The surface is entirely undocumented private API.** Apple owes no compatibility and gives no notice. 15.4 is proof they will break it deliberately.
- **The current workaround is a genuine hole, not a supported path.** It hinges on `/usr/bin/perl` reporting a `com.apple.*` bundle id. Apple could (a) tighten the entitlement check to a real code-signature/entitlement rather than a bundle-id prefix, (b) restrict which `com.apple.*` binaries qualify, or (c) remove system perl entirely (perl is already deprecated in macOS as a bundled scripting runtime). Any of these closes the hole with no warning.
- **Mitigants:** the adapter is actively maintained and fast to respond (15.4 shipped ~March 2025; the perl workaround and downstream `nowplaying-cli` fix landed by April 2025). The whole feature already sits behind deckd's `MprisBackend` Protocol seam (`row_ids` / `read_state` / `send_command`), so a macOS backend is a third implementation that the browser/widget/dispatch never see. And the fallbacks degrade in tiers: adapter → per-app AppleScript (Music/Spotify) → feature simply absent.

**Recommendation:** build it as `MacNowPlayingBackend` that **shells out to the adapter/`nowplaying-cli`** rather than binding MediaRemote in-process. Treat the helper as an external, swappable dependency (like deckd already treats `xdotool` for X11 focus): detect it on `$PATH` / in a bundled location, surface a clean "unavailable + install hint" when missing (mirroring `FocusBackendUnavailable`), and never let its absence crash the daemon. Pin/track the adapter version. Do **not** invest in a direct-MediaRemote pyobjc path — it's dead for reads and would only re-break.

### Fit against the #56 seam (quick confirm)

The issue's architectural expectation holds: a macOS backend only needs to implement the three `MprisBackend` methods and wire into `connect_mpris_backend`. The one impedance mismatch is real and benign — MediaRemote exposes a **single** "now playing" app at a time, so `row_ids()` returns **one row (or zero)** rather than MPRIS's N players; the `mediabrowser` UI already has to degrade to a single row and does so cleanly. `send_command` maps onto `MRMediaRemoteSendCommand` (via the helper's command verbs); the live-update story uses the adapter's `stream` mode, which is driven by `kMRMediaRemoteNowPlayingInfoDidChangeNotification` under the hood — so no polling is required.

---

## Sources

Primary — Apple:
- MPNowPlayingInfoCenter (publish-side) — https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter
- MPRemoteCommandCenter (receive-commands-side) — https://developer.apple.com/documentation/mediaplayer/mpremotecommandcenter

Primary — helper tools (GitHub):
- ungive/mediaremote-adapter (README + releases v0.7.3–v0.7.6, commit history to May 2026) — https://github.com/ungive/mediaremote-adapter
- kirtan-shah/nowplaying-cli — https://github.com/kirtan-shah/nowplaying-cli
  - README (tested versions, `src/mediaremote-mini/` provenance) — https://github.com/kirtan-shah/nowplaying-cli/blob/main/README.md
  - Issue #28 "no longer works on macOS 15.4" — https://github.com/kirtan-shah/nowplaying-cli/issues/28
- aviwad/LyricFever issue #94 "MRMediaRemoteGetNowPlayingInfo return nil in latest MacOS" (Operation not permitted, Code=3; read broke / command still works; opened 2025-03-22) — https://github.com/aviwad/LyricFever/issues/94
- davidmurray/ios-reversed-headers `MediaRemote.h` (private function/notification reference) — https://github.com/davidmurray/ios-reversed-headers/blob/master/MediaRemote/MediaRemote.h

Corroborating / SIP-requiring alternative (rejected):
- Mx-Iris/MediaRemoteWizard (injects into `mediaremoted`; requires SIP disabled) — https://github.com/Mx-Iris/MediaRemoteWizard

AppleScript fallback:
- andrehaveman/spotify-node-applescript — https://github.com/andrehaveman/spotify-node-applescript
- AppleScript current-song gist — https://gist.github.com/joshuaswilcox/7251527

---

## Confidence / what's still uncertain

**High confidence:**
- `MPNowPlayingInfoCenter` / `MPRemoteCommandCenter` are publish/receive-side, wrong for reading others' playback.
- 15.4 added `mediaremoted` entitlement enforcement on reads; direct unentitled read is dead; send-command is not gated.
- The adapter's `/usr/bin/perl` (`com.apple.*` bundle id) shim is the working entitlement-free read path, no SIP change, and both tools are maintained through mid-2026 and tested on Sequoia 15.7 / Tahoe 26.3.

**Medium confidence:**
- Exact behaviour on *every* 15.x point release between 15.4 and 26 (I verified the endpoints — 15.4 broke it, 15.7 and 26.3 work via the shim — but did not walk each intermediate release).
- Whether artwork/streaming quirks noted by the adapter affect the specific fields deckd's `mediabrowser` renders.

**Low confidence / genuinely unknowable:**
- How long the perl-shim hole survives. It is an unsupported gap in a private API; Apple can close it in any release without notice.

**Not done here (by design):** no prototype/backend code was written; empirical verification on a live macOS host is the natural next step if this is greenlit (run `nowplaying-cli get` and `stream` on a current machine and confirm the fields).
