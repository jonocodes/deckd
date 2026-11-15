/** Playground app-switcher strip (#152).
 *
 * The one affordance with no real-world analog: a browser has no OS
 * focus, so the visitor clicks a chip to say "pretend this app is
 * frontmost". The strip is a dumb list — it renders the apps it's
 * given, marks the MRU-front (focused) one, and reports clicks upward.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ServerWindowListEntry } from "../protocol";
import { PlaygroundAppSwitcher } from "./PlaygroundAppSwitcher";

const APPS: ServerWindowListEntry[] = [
  { window_id: "music", label: "Music", icon: { source: "lucide", name: "music" } },
  { window_id: "lights", label: "Lights", icon: { source: "lucide", name: "lightbulb" } },
  { window_id: "browser", label: "Firefox", icon: null },
];

describe("PlaygroundAppSwitcher", () => {
  afterEach(cleanup);

  it("renders one chip per app", () => {
    render(<PlaygroundAppSwitcher apps={APPS} onSelect={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Music" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Lights" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Firefox" })).toBeTruthy();
  });

  it("marks only the MRU-front (focused) app as pressed", () => {
    const reordered = [APPS[1], APPS[0], APPS[2]];
    render(<PlaygroundAppSwitcher apps={reordered} onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Lights" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByRole("button", { name: "Music" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("reports the clicked app's window id", () => {
    const onSelect = vi.fn();
    render(<PlaygroundAppSwitcher apps={APPS} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Lights" }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("lights");
  });

  it("renders nothing before any app roster has arrived", () => {
    const { container } = render(<PlaygroundAppSwitcher apps={[]} onSelect={vi.fn()} />);
    expect(container.querySelector(".playground-switcher")).toBeNull();
  });
});
