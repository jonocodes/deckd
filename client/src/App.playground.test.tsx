/** Playground app-switcher integration (#152).
 *
 * In a browser there is no OS focus, so the Playground needs its own way
 * to say "this app is frontmost now". This drives the real MockDaemon
 * through the real App deck-push path: clicking a chip re-resolves
 * focus in the mock, which pushes a new deck, and App re-renders the
 * badge / grid / icon with no special-casing.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const send = vi.fn();
vi.mock("./socket", () => ({
  useDeckdSocket: () => ({
    status: "open",
    send,
    authenticate: vi.fn(),
    deauthenticate: vi.fn(),
    hasPassword: false,
  }),
}));

import { App } from "./App";

describe("App — Playground app switcher (#152)", () => {
  beforeEach(() => {
    send.mockReset();
    vi.useFakeTimers();
    window.history.replaceState(null, "", "/?playground");
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders a chip for every virtual app", () => {
    render(<App />);
    expect(screen.getByRole("group", { name: "switch app" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Music" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lights" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Firefox" })).toBeTruthy();
  });

  it("switches the focused app's deck when a chip is clicked", () => {
    render(<App />);
    expect(document.querySelector(".app-badge-name")?.textContent).toBe("Music");
    // The Music deck renders a media widget; the Lights deck a meter.
    expect(document.querySelector(".cell-media")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Lights" }));
    expect(document.querySelector(".app-badge-name")?.textContent).toBe("Lights");
    expect(document.querySelector(".cell-meter")).toBeTruthy();
    expect(document.querySelector(".cell-media")).toBeNull();
    expect(screen.getByRole("button", { name: "Lights" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByRole("button", { name: "Music" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("hides the switcher outside playground mode", () => {
    window.history.replaceState(null, "", "/");
    render(<App />);
    expect(screen.queryByRole("group", { name: "switch app" })).toBeNull();
  });
});
