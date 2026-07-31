import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MediaCell } from "./MediaCell";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

const WIDGET: Widget = {
  id: "media",
  kind: "media",
  controls: ["play", "previous", "next", "volume", "position", "speed"],
  media_http: {},
};

const STATE: MediaReading = {
  id: "media",
  available: true,
  stale: false,
  playing: true,
  position: 65,
  duration: 125,
  volume: 42,
  rate: 1,
  title: "Track",
  artist: "Artist",
};

describe("MediaCell", () => {
  afterEach(cleanup);

  it("exposes live status, pressed state, and useful range values", () => {
    render(<MediaCell widget={WIDGET} state={STATE} onPress={vi.fn()} onCommand={vi.fn()} />);
    expect(screen.getByText("Media live").getAttribute("role")).toBe("status");
    expect(screen.getByRole("button", { name: "Pause" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("slider", { name: "Playback position" }).getAttribute("aria-valuetext")).toBe("1:05 of 2:05");
    expect(screen.getByRole("slider", { name: "Volume" }).getAttribute("aria-valuetext")).toBe("42 percent");
  });

  it("dispatches transport and speed controls through click", () => {
    const onPress = vi.fn();
    const onCommand = vi.fn();
    render(<MediaCell widget={WIDGET} state={STATE} onPress={onPress} onCommand={onCommand} />);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Increase speed" }));
    expect(onPress).toHaveBeenCalledWith("media");
    expect(onPress).toHaveBeenCalledWith("media:next");
    expect(onCommand).toHaveBeenCalledWith("media", "rate", 1.25);
  });

  it("renders keyboard volume fallback when HTTP is unavailable", () => {
    const onPress = vi.fn();
    const widget = {
      ...WIDGET,
      media_http: null,
      volume_up_action: { key: "volumeup" },
      volume_down_action: { key: "volumedown" },
    };
    render(<MediaCell widget={widget} state={null} onPress={onPress} onCommand={vi.fn()} />);
    expect(screen.queryByRole("slider", { name: "Volume" })).toBeNull();
    expect(screen.getByText("Media unavailable").getAttribute("role")).toBe("status");
    fireEvent.click(screen.getByRole("button", { name: "Volume down" }));
    fireEvent.click(screen.getByRole("button", { name: "Volume up" }));
    expect(onPress).toHaveBeenNthCalledWith(1, "media:volume_down");
    expect(onPress).toHaveBeenNthCalledWith(2, "media:volume_up");
  });
});
