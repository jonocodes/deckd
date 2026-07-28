/** Tests for the Tooltip wrapper (issue #59).
 *
 * Verifies the AC:
 *  - hover (after a short delay) and keyboard focus both surface the tooltip
 *  - tooltip text matches the wrapped control's aria-label
 *  - Escape dismisses; pointer leave dismisses
 *  - aria-describedby is wired to the floating tooltip element
 *  - 4-second auto-dismiss keeps the tooltip from lingering
 *  - touch-and-hold shows the tooltip (long-press), touch release hides
 *
 * The App-level integration (every chrome button is wrapped) is
 * covered in App.test.tsx so a regression on the chrome buttons
 * doesn't go unnoticed.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useEffect, useRef, useState } from "react";
import { Tooltip } from "./Tooltip";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("Tooltip", () => {
  it("renders nothing by default and the host has no aria-describedby", () => {
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    expect(screen.queryByRole("tooltip")).toBeNull();
    const button = screen.getByRole("button", { name: "settings" });
    expect(button.getAttribute("aria-describedby")).toBeNull();
  });

  it("shows the tooltip on keyboard focus immediately", async () => {
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.focus(button);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toBe("settings");
    // aria-describedby must point at the floating tooltip element.
    expect(button.getAttribute("aria-describedby")).toBe(tooltip.id);
  });

  it("shows the tooltip on pointer enter after the hover delay", async () => {
    vi.useFakeTimers();
    render(
      <Tooltip label="manual control">
        <button aria-label="manual control">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "manual control" });
    fireEvent.pointerEnter(button);
    // Not yet — the hover delay is 200ms.
    expect(screen.queryByRole("tooltip")).toBeNull();
    await vi.advanceTimersByTimeAsync(250);
    expect(screen.getByRole("tooltip").textContent).toBe("manual control");
    vi.useRealTimers();
  });

  it("hides the tooltip on pointer leave", async () => {
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.focus(button);
    await screen.findByRole("tooltip");
    fireEvent.pointerLeave(button);
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    // aria-describedby clears too — no stale association.
    expect(button.getAttribute("aria-describedby")).toBeNull();
  });

  it("hides the tooltip on Escape", async () => {
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.focus(button);
    await screen.findByRole("tooltip");
    fireEvent.keyDown(button, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });

  it("hides the tooltip after the 4-second auto-dismiss", async () => {
    vi.useFakeTimers();
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.focus(button);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByRole("tooltip").textContent).toBe("settings");
    await vi.advanceTimersByTimeAsync(3500);
    expect(screen.queryByRole("tooltip")).not.toBeNull();
    await vi.advanceTimersByTimeAsync(600);
    expect(screen.queryByRole("tooltip")).toBeNull();
    vi.useRealTimers();
  });

  it("shows the tooltip on touch-and-hold and hides on release", async () => {
    // Use real timers but with a longer timeout — fake timers
    // interact poorly with ``waitFor``'s internal polling. The
    // long-press is 500ms which fits inside vitest's default 5s
    // timeout.
    render(
      <Tooltip label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.touchStart(button);
    // Wait long enough for the long-press timer to fire (500ms)
    // and the React state update to flush.
    await new Promise((r) => setTimeout(r, 600));
    expect(screen.getByRole("tooltip").textContent).toBe("settings");
    fireEvent.touchEnd(button);
    // Touch-end dispatches ``hide()`` synchronously; the tooltip
    // unmounts in the same tick. ``waitFor`` covers the React
    // commit before we assert.
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });

  it("forwards click handlers on the wrapped button", () => {
    const onClick = vi.fn();
    render(
      <Tooltip label="settings">
        <button aria-label="settings" onClick={onClick}>
          x
        </button>
      </Tooltip>,
    );
    fireEvent.click(screen.getByRole("button", { name: "settings" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("re-renders with new label without leaving stale tooltip text", async () => {
    function Wrapper() {
      const [label, setLabel] = useState("first");
      return (
        <>
          <Tooltip label={label}>
            <button aria-label={label}>x</button>
          </Tooltip>
          <button onClick={() => setLabel("second")}>swap</button>
        </>
      );
    }
    render(<Wrapper />);
    fireEvent.focus(screen.getByRole("button", { name: "first" }));
    expect((await screen.findByRole("tooltip")).textContent).toBe("first");
    // Swap the label — the old button is unmounted and a new one
    // appears with the new label. Focus on it; the new tooltip text
    // should surface immediately.
    fireEvent.click(screen.getByRole("button", { name: "swap" }));
    const second = screen.getByRole("button", { name: "second" });
    fireEvent.focus(second);
    expect((await screen.findByRole("tooltip")).textContent).toBe("second");
  });
});

/* ---------------------------------------------------------------------
   Ref forwarding (issue #60).

   The tooltip sits between the parent and the wrapped child, so a
   parent that passes ``ref={someUseRefObject}`` would otherwise see
   ``null``. The wrapper uses ``forwardRef`` and chains the ref onto
   the underlying button via ``cloneElement``'s ``ref`` prop, so the
   parent gets the resolved DOM node back.
   --------------------------------------------------------------------- */
describe("Tooltip — ref forwarding", () => {
  afterEach(cleanup);

  it("forwards a callback ref to the wrapped child", () => {
    const refCb = vi.fn();
    render(
      <Tooltip ref={refCb} label="settings">
        <button aria-label="settings">x</button>
      </Tooltip>,
    );
    // The ref callback receives the actual button DOM node.
    expect(refCb).toHaveBeenCalled();
    const node = refCb.mock.calls[0][0];
    expect(node?.tagName).toBe("BUTTON");
  });

  it("forwards a useRef object to the wrapped child", () => {
    // Render with the ref on the OUTER Tooltip (forwardRef form).
    // This is the form the chrome buttons use so a parent can
    // capture the button element for focus restoration.
    function Harness() {
      const ref = useRef<HTMLButtonElement | null>(null);
      // ``useState`` lets us force a re-render after the ref
      // commits (refs alone don't trigger re-renders), so the
      // testid span reads the post-commit value.
      const [, force] = useState(0);
      // ``useEffect`` runs after the commit; by the time it runs,
      // the ref callback has fired.
      useEffect(() => {
        if (ref.current) force((n) => n + 1);
      }, []);
      return (
        <>
          <Tooltip ref={ref} label="settings">
            <button aria-label="settings">x</button>
          </Tooltip>
          <span data-testid="ref-current">{ref.current ? "set" : "null"}</span>
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByTestId("ref-current").textContent).toBe("set");
  });
});
