/** Tests for the Trackpad keyboard alternative (issue #60, AC #6).
 *
 * Arrow keys / numpad emit ``pad`` deltas; Space / Enter emit
 * ``pad_tap`` (left click); Home / End emit big jumps. The keyboard
 * handler must NOT fire while the trackpad isn't focused — its
 * hot path is the pointer gesture, and a stray global handler would
 * also steal keystrokes from the password gate / IME.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Trackpad } from "./Trackpad";

describe("Trackpad — keyboard alternative", () => {
  afterEach(cleanup);

  it("is keyboard-focusable and exposes an application role", () => {
    const noop = () => {};
    render(<Trackpad onPad={noop} onTap={noop} onDrag={noop} sensitivity={1} />);
    const trackpad = screen.getByRole("application", { name: /trackpad/i });
    expect(trackpad.getAttribute("tabindex")).toBe("0");
    trackpad.focus();
    expect(document.activeElement).toBe(trackpad);
  });

  it("ArrowRight produces a positive dx when sensitivity is 1", () => {
    const onPad = vi.fn();
    render(<Trackpad onPad={onPad} onTap={() => {}} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "ArrowRight" });
    expect(onPad).toHaveBeenCalledWith(expect.any(Number), expect.any(Number));
    expect(onPad.mock.calls[0][0]).toBeGreaterThan(0);
    expect(onPad.mock.calls[0][1]).toBe(0);
  });

  it("ArrowDown produces a positive dy", () => {
    const onPad = vi.fn();
    render(<Trackpad onPad={onPad} onTap={() => {}} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "ArrowDown" });
    expect(onPad.mock.calls[0][0]).toBe(0);
    expect(onPad.mock.calls[0][1]).toBeGreaterThan(0);
  });

  it("numpad diagonals produce diagonal deltas", () => {
    const onPad = vi.fn();
    render(<Trackpad onPad={onPad} onTap={() => {}} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "Numpad9" });
    expect(onPad.mock.calls[0][0]).toBeGreaterThan(0);
    expect(onPad.mock.calls[0][1]).toBeLessThan(0);
  });

  it("PageDown produces a larger dy than ArrowDown", () => {
    const onPad = vi.fn();
    render(<Trackpad onPad={onPad} onTap={() => {}} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("application"), { key: "PageDown" });
    const arrow = Math.abs(onPad.mock.calls[0][1]);
    const page = Math.abs(onPad.mock.calls[1][1]);
    expect(page).toBeGreaterThan(arrow);
  });

  it("Space fires a single-finger tap", () => {
    const onTap = vi.fn();
    render(<Trackpad onPad={() => {}} onTap={onTap} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: " " });
    expect(onTap).toHaveBeenCalledWith(1);
  });

  it("Enter fires a single-finger tap", () => {
    const onTap = vi.fn();
    render(<Trackpad onPad={() => {}} onTap={onTap} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "Enter" });
    expect(onTap).toHaveBeenCalledWith(1);
  });

  it("sensitivity scales keyboard deltas", () => {
    const onPad = vi.fn();
    render(<Trackpad onPad={onPad} onTap={() => {}} onDrag={() => {}} sensitivity={2} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "ArrowRight" });
    expect(onPad.mock.calls[0][0]).toBe(2);
  });

  it("non-keypad keys don't fire onPad or onTap", () => {
    const onPad = vi.fn();
    const onTap = vi.fn();
    render(<Trackpad onPad={onPad} onTap={onTap} onDrag={() => {}} sensitivity={1} />);
    fireEvent.keyDown(screen.getByRole("application"), { key: "a" });
    fireEvent.keyDown(screen.getByRole("application"), { key: "Escape" });
    expect(onPad).not.toHaveBeenCalled();
    expect(onTap).not.toHaveBeenCalled();
  });
});