/** MPRIS bus suffixes that have a client-side icon mapping (issue #53).
 * Add entries here as new players are tested; an unknown ``desktop_entry``
 * falls back to the Lucide ``Disc`` glyph so the row still reads as "a
 * media player". The mapping is the desktop file basename → the Simple
 * Icons slug the client can render (it must exist — see the test; Rhythmbox
 * has no Simple Icons logo, so it takes the disc). Empty / unknown entries
 * fall through. */
export const DESKTOP_ICONS: Record<string, { source: "simple-icons"; name: string }> = {
  vlc: { source: "simple-icons", name: "vlcmediaplayer" },
  spotify: { source: "simple-icons", name: "spotify" },
  firefox: { source: "simple-icons", name: "firefox" },
  mpv: { source: "simple-icons", name: "mpv" },
  audacity: { source: "simple-icons", name: "audacity" },
};
