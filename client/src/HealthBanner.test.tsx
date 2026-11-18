/** Health-issue banner (issue #195).
 *
 * The daemon pushes the full list of active health issues (missing OS
 * permissions); the banner renders each one with what won't work and how
 * to fix it, is dismissible for the page session, and disappears when the
 * daemon pushes an empty list.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { HealthBanner } from "./HealthBanner";
import type { HealthIssue } from "./protocol";

afterEach(cleanup);

const AX: HealthIssue = {
  id: "accessibility_missing",
  severity: "error",
  title: "Accessibility permission missing",
  detail: "macOS isn't letting deckd.app control the mouse and keyboard.",
  fix_steps: [
    "On the Mac, open System Settings → Privacy & Security → Accessibility.",
    "Turn on deckd.app.",
  ],
  affects: ["pointer", "scroll", "key", "raise_window"],
};

describe("HealthBanner", () => {
  it("renders nothing when there are no issues", () => {
    const { container } = render(<HealthBanner issues={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the title, detail, what won't work and the fix steps", () => {
    render(<HealthBanner issues={[AX]} />);
    const banner = screen.getByRole("alert");
    expect(banner.textContent).toContain("Accessibility permission missing");
    expect(banner.textContent).toContain("deckd.app");
    expect(banner.textContent).toContain("Privacy & Security → Accessibility");
    // ``affects`` renders as human words, not wire keys.
    expect(banner.textContent).toContain("trackpad & clicks");
    expect(banner.textContent).toContain("window switching");
    expect(banner.textContent).not.toContain("raise_window");
    expect(screen.getAllByRole("listitem").length).toBe(2);
  });

  it("falls back to the raw key for an unknown primitive", () => {
    render(<HealthBanner issues={[{ ...AX, affects: ["teleport"] }]} />);
    expect(screen.getByRole("alert").textContent).toContain("teleport");
  });

  it("dismiss hides the issue; it stays hidden across re-pushes", () => {
    const { rerender } = render(<HealthBanner issues={[AX]} />);
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<HealthBanner issues={[{ ...AX }]} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears when the daemon pushes an empty list", () => {
    const { rerender } = render(<HealthBanner issues={[AX]} />);
    expect(screen.getByRole("alert")).toBeTruthy();
    rerender(<HealthBanner issues={[]} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a dismissed issue that clears and comes back shows again", () => {
    const { rerender } = render(<HealthBanner issues={[AX]} />);
    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    rerender(<HealthBanner issues={[]} />);
    rerender(<HealthBanner issues={[AX]} />);
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("dismissing one issue leaves the others up", () => {
    const other: HealthIssue = { ...AX, id: "uinput_missing", title: "uinput not accessible" };
    render(<HealthBanner issues={[AX, other]} />);
    expect(screen.getAllByRole("alert").length).toBe(2);
    fireEvent.click(screen.getAllByRole("button", { name: /dismiss/i })[0]);
    const left = screen.getAllByRole("alert");
    expect(left.length).toBe(1);
    expect(left[0].textContent).toContain("uinput not accessible");
  });
});
