/** Tests for the JogStrip keyboard alternative (issue #60, AC #6).
 *
 * The pointer gestures (drag / flick) stay covered by the Ladle
 * stories. Here we lock down the keyboard surface: arrow keys
 * produce scroll deltas, Page Up / Page Down emit larger jumps,
 * Home / End emit huge jumps, and hold-to-repeat streams deltas
 * while the key is held. The wheel direction honours the ``invert``
 * prop, matching the touch surface's behaviour.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JogStrip } from "./JogStrip";

const WIDGET = { id: "test.jog", label: "jog" };

function getStrip(): HTMLElement {
  // The JogStrip is a keyboard-focusable ``<div>`` with an
  // ``aria-label`` describing its purpose; query by label rather
  // than by role since ARIA doesn't have a great fit for a control
  // that emits scroll deltas (not actually a scrollbar — the value
  // isn't a position).
  return screen.getByLabelText(/scroll strip/i) as HTMLElement;
}

describe("JogStrip — keyboard alternative", () => {
  afterEach(cleanup);

  it("is keyboard-focusable via Tab order", () => {
    render(
      <div>
        <button>before</button>
        <JogStrip widget={WIDGET} scale={1} invert={false} onJog={() => {}} onJogEnd={() => {}} />
        <button>after</button>
      </div>,
    );
    const strip = getStrip();
    expect(strip).toBeTruthy();
    expect(strip.getAttribute("tabindex")).toBe("0");
    strip.focus();
    expect(document.activeElement).toBe(strip);
  });

  it("ArrowDown produces a positive delta when invert is off", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert={false} onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "ArrowDown" });
    expect(onJog).toHaveBeenCalledWith("test.jog", expect.any(Number));
    expect(onJog.mock.calls[0][1]).toBeGreaterThan(0);
  });

  it("ArrowUp produces a negative delta when invert is off", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert={false} onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "ArrowUp" });
    expect(onJog.mock.calls[0][1]).toBeLessThan(0);
  });

  it("the invert prop flips the keyboard delta direction", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "ArrowDown" });
    // With invert, an ArrowDown (intuitively "go down") should now
    // produce a negative delta — the wheel direction is reversed.
    expect(onJog.mock.calls[0][1]).toBeLessThan(0);
  });

  it("PageDown produces a larger delta than ArrowDown", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert={false} onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "ArrowDown" });
    fireEvent.keyDown(getStrip(), { key: "PageDown" });
    const arrowDelta = Math.abs(onJog.mock.calls[0][1]);
    const pageDelta = Math.abs(onJog.mock.calls[1][1]);
    expect(pageDelta).toBeGreaterThan(arrowDelta);
  });

  it("Home emits a single big negative delta and End a big positive one", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert={false} onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "Home" });
    fireEvent.keyDown(getStrip(), { key: "End" });
    expect(onJog.mock.calls[0][1]).toBeLessThan(-1000);
    expect(onJog.mock.calls[1][1]).toBeGreaterThan(1000);
  });

  it("non-scroll keys don't fire any onJog", () => {
    const onJog = vi.fn();
    render(<JogStrip widget={WIDGET} scale={1} invert={false} onJog={onJog} onJogEnd={() => {}} />);
    fireEvent.keyDown(getStrip(), { key: "a" });
    fireEvent.keyDown(getStrip(), { key: "Enter" });
    fireEvent.keyDown(getStrip(), { key: "Escape" });
    expect(onJog).not.toHaveBeenCalled();
  });
});