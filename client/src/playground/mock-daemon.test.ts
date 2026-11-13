/** MockDaemon foundation + app-switch seam (#149 / #150 / #151 / #152).
 *
 * The mock is the Playground's whole backend, so its behavioural
 * contracts are worth pinning: it starts on the music app, it ticks
 * deterministically, and a ``raise_window`` (what the app-switcher
 * sends) re-resolves focus and pushes the newly focused app's deck —
 * exactly what the daemon's focus watcher does on a real desktop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  MediaState,
  ServerChromeMedia,
  ServerDeck,
  ServerRunningWindows,
  ServerWidgetUpdate,
} from "../protocol";
import { MockDaemon } from "./mock-daemon";

let started: MockDaemon | null = null;

function makeDaemon() {
  const decks: ServerDeck[] = [];
  const media: MediaState[] = [];
  const widgets: ServerWidgetUpdate[] = [];
  const chromeMedia: ServerChromeMedia[] = [];
  const windows: ServerRunningWindows[] = [];
  const daemon = new MockDaemon({
    onDeck: (m) => decks.push(m),
    onMediaState: (m) => media.push(m),
    onWidgetUpdate: (m) => widgets.push(m),
    onChromeMedia: (m) => chromeMedia.push(m),
    onRunningWindows: (m) => windows.push(m),
  });
  started = daemon;
  return { daemon, decks, media, widgets, chromeMedia, windows };
}

describe("MockDaemon", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    started?.stop();
    started = null;
    vi.useRealTimers();
  });

  it("starts focused on the music app and publishes the app roster", () => {
    const { daemon, decks, windows } = makeDaemon();
    daemon.start();
    expect(decks.at(0)?.app).toBe("Music");
    expect(windows.at(0)?.windows.map((w) => w.label)).toEqual(["Music", "Lights", "Firefox"]);
  });

  it("advances playback while playing (a single deterministic clock)", () => {
    const { daemon, media } = makeDaemon();
    daemon.start();
    const before = media.at(-1)?.position ?? 0;
    // Music starts at position 42, playing, rate 1.
    vi.advanceTimersByTime(1000);
    expect(media.at(-1)?.position).toBe(before + 1);
  });

  it("re-resolves focus and pushes the deck on raise_window (app switch)", () => {
    const { daemon, decks, windows } = makeDaemon();
    daemon.start();
    daemon.send({ type: "raise_window", window_id: "lights" });
    expect(decks.at(-1)?.app).toBe("Lights");
    // MRU order moves the focused app to the front of the roster.
    expect(windows.at(-1)?.windows.at(0)?.window_id).toBe("lights");
  });

  it("pauses the clock on the focused deck's play/pause press", () => {
    const { daemon, media } = makeDaemon();
    daemon.start();
    daemon.send({ type: "press", id: "music-media" });
    const paused = media.at(-1);
    expect(paused?.playing).toBe(false);
    const position = paused?.position;
    vi.advanceTimersByTime(1000);
    expect(media.at(-1)?.position).toBe(position);
  });

  it("stops ticking after stop()", () => {
    const { daemon, media } = makeDaemon();
    daemon.start();
    vi.advanceTimersByTime(500);
    const count = media.length;
    daemon.stop();
    vi.advanceTimersByTime(2000);
    expect(media.length).toBe(count);
  });
});
