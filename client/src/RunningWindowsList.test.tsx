/** Direct tests for :component:`RunningWindowsList`.
 *
 * The chrome-view integration tests in :file:`App.windows.test.tsx`
 * cover the wire surface (the App dispatches the right
 * ``select_view`` / ``clear_view`` frames and reacts to the daemon's
 * ``running_windows`` push). This file exercises the component's own
 * rendering rules in isolation — empty states, label rendering, the
 * interactive-when-onTap shape.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunningWindowsList } from "./RunningWindowsList";

afterEach(cleanup);

describe("RunningWindowsList", () => {
  it("renders the unsupported empty state when windows is undefined", () => {
    render(<RunningWindowsList windows={undefined} />);
    expect(screen.getByText("running programs: unsupported on this platform")).toBeTruthy();
  });

  it("renders the empty list message when windows is []", () => {
    render(<RunningWindowsList windows={[]} />);
    expect(screen.getByText("no running programs")).toBeTruthy();
  });

  it("renders one row per window with the daemon-derived label", () => {
    render(
      <RunningWindowsList
        windows={[
          { window_id: "1", label: "Firefox", icon: { source: "simple-icons", name: "firefox" } },
          { window_id: "2", label: "xterm", icon: null },
        ]}
      />,
    );
    const rows = document.querySelectorAll(".windows-row");
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute("data-window-id")).toBe("1");
    expect(rows[0].textContent).toContain("Firefox");
    expect(rows[1].getAttribute("data-window-id")).toBe("2");
    expect(rows[1].textContent).toContain("xterm");
  });

  it("does not render a placeholder marker on default-fallback rows (honest absence)", () => {
    // Decision 6: a generic "terminal" Lucide icon on every xterm
    // would imply every xterm is the same xterm. The wire-shape
    // distinction (icon=null) is the only honest signal — the row
    // renders the label only.
    const { container } = render(
      <RunningWindowsList
        windows={[{ window_id: "1", label: "xterm", icon: null }]}
      />,
    );
    expect(container.querySelector(".windows-row-placeholder")).toBeNull();
    expect(container.querySelector(".windows-row-icon")).toBeNull();
  });

  it("renders the icon column when icon is present", () => {
    const { container } = render(
      <RunningWindowsList
        windows={[{ window_id: "1", label: "Firefox", icon: { source: "simple-icons", name: "firefox" } }]}
      />,
    );
    expect(container.querySelector(".windows-row-icon")).not.toBeNull();
  });

  it("rows are not interactive when onRowTap is omitted", () => {
    render(
      <RunningWindowsList
        windows={[{ window_id: "1", label: "xterm", icon: null }]}
      />,
    );
    const row = document.querySelector(".windows-row") as HTMLElement;
    expect(row.getAttribute("role")).toBeNull();
    expect(row.getAttribute("tabindex")).toBeNull();
  });

  it("rows become interactive when onRowTap is provided, calling back with the window id", () => {
    const onTap = vi.fn<(windowId: string) => void>();
    render(
      <RunningWindowsList
        windows={[
          { window_id: "w1", label: "xterm", icon: null },
          { window_id: "w2", label: "Firefox", icon: null },
        ]}
        onRowTap={onTap}
      />,
    );
    const rows = document.querySelectorAll(".windows-row");
    fireEvent.click(rows[0]);
    fireEvent.click(rows[1]);
    expect(onTap).toHaveBeenNthCalledWith(1, "w1");
    expect(onTap).toHaveBeenNthCalledWith(2, "w2");
  });

  it("Enter on a focused row triggers onRowTap", () => {
    const onTap = vi.fn<(windowId: string) => void>();
    render(
      <RunningWindowsList
        windows={[{ window_id: "w1", label: "xterm", icon: null }]}
        onRowTap={onTap}
      />,
    );
    const row = document.querySelector(".windows-row") as HTMLElement;
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onTap).toHaveBeenCalledWith("w1");
  });
});