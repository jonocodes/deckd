import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ManualControl } from "./ManualControl";

function getInput(): HTMLInputElement {
  return screen.getByLabelText("Remote keyboard") as HTMLInputElement;
}

describe("ManualControl", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe("IME toggle (strip keyboard-icon button)", () => {
    it("renders the keyboard toggle button in the strip", () => {
      const noop = () => {};
      render(
        <ManualControl
          onType={noop}
          onKey={noop}
          onPad={noop}
          onTap={noop}
          onDrag={noop}
          sensitivity={1}
        />,
      );
      expect(screen.getByRole("button", { name: "keyboard" })).not.toBeNull();
    });

    it("does not auto-focus the input on mount", () => {
      const noop = () => {};
      render(
        <ManualControl
          onType={noop}
          onKey={noop}
          onPad={noop}
          onTap={noop}
          onDrag={noop}
          sensitivity={1}
        />,
      );
      expect(getInput()).not.toBe(document.activeElement);
    });

    it("tapping the keyboard button focuses the input and sets aria-pressed", () => {
      const noop = () => {};
      render(
        <ManualControl
          onType={noop}
          onKey={noop}
          onPad={noop}
          onTap={noop}
          onDrag={noop}
          sensitivity={1}
        />,
      );
      const btn = screen.getByRole("button", { name: "keyboard" });
      const ev = new Event("pointerdown", { bubbles: true, cancelable: true });
      act(() => {
        btn.dispatchEvent(ev);
      });
      expect(ev.defaultPrevented).toBe(true);
      expect(getInput()).toBe(document.activeElement);
      expect(btn.getAttribute("aria-pressed")).toBe("true");
    });

    it("tapping the keyboard button again blurs the input and clears aria-pressed", () => {
      const noop = () => {};
      render(
        <ManualControl
          onType={noop}
          onKey={noop}
          onPad={noop}
          onTap={noop}
          onDrag={noop}
          sensitivity={1}
        />,
      );
      const btn = screen.getByRole("button", { name: "keyboard" });
      act(() => {
        btn.dispatchEvent(new Event("pointerdown", { bubbles: true, cancelable: true }));
      });
      expect(btn.getAttribute("aria-pressed")).toBe("true");
      act(() => {
        btn.dispatchEvent(new Event("pointerdown", { bubbles: true, cancelable: true }));
      });
      expect(btn.getAttribute("aria-pressed")).toBe("false");
      expect(getInput()).not.toBe(document.activeElement);
    });
  });

  describe("strip key buttons", () => {
    it("sends the combo on pointerdown and prevents default", () => {
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={() => {}}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const escButton = screen.getByLabelText("esc");
      const ev = new Event("pointerdown", { bubbles: true, cancelable: true });
      escButton.dispatchEvent(ev);
      expect(onKey).toHaveBeenCalledExactlyOnceWith("esc");
      expect(ev.defaultPrevented).toBe(true);
    });
  });

  describe("sendDelta (input event path)", () => {
    it("sends the inserted text when the field grows from empty", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      // The user explicitly raised the IME first (the input is otherwise
      // not focused, but the event listeners are attached regardless).
      input.value = "abc";
      fireEvent.input(input);
      expect(onType).toHaveBeenCalledExactlyOnceWith("abc");
      expect(onKey).not.toHaveBeenCalled();
    });

    it("sends one backspace per deleted tail character (single deletion)", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      fireEvent.compositionStart(input);
      input.value = "abcd";
      fireEvent.input(input);
      input.value = "abc";
      fireEvent.input(input);
      fireEvent.compositionEnd(input);
      expect(onKey).toHaveBeenCalledExactlyOnceWith("backspace");
      expect(onType.mock.calls).toEqual([["abcd"]]);
    });

    it("sends backspaces + replacement on autocorrect-style rewrite", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      fireEvent.compositionStart(input);
      input.value = "hellp";
      fireEvent.input(input);
      input.value = "hello";
      fireEvent.input(input);
      fireEvent.compositionEnd(input);
      expect(onKey).toHaveBeenCalledExactlyOnceWith("backspace");
      expect(onType.mock.calls).toEqual([["hellp"], ["o"]]);
    });

    it("resets the field to empty after a non-composition insert", () => {
      const onType = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={() => {}}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      input.value = "abc";
      fireEvent.input(input);
      expect(input.value).toBe("");
    });

    it("does not reset the field while composition is active", () => {
      const onType = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={() => {}}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      fireEvent.compositionStart(input);
      input.value = "abc";
      fireEvent.input(input);
      expect(input.value).toBe("abc");
      fireEvent.compositionEnd(input);
      input.value = "abc";
      fireEvent.input(input);
      expect(input.value).toBe("");
    });
  });

  describe("beforeinput path (Android IME control keys)", () => {
    it("sends 'enter' on insertParagraph and prevents default", () => {
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={() => {}}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const ev = new InputEvent("beforeinput", {
        bubbles: true,
        cancelable: true,
        inputType: "insertParagraph",
      });
      getInput().dispatchEvent(ev);
      expect(onKey).toHaveBeenCalledExactlyOnceWith("enter");
      expect(ev.defaultPrevented).toBe(true);
    });

    it("sends 'enter' on insertLineBreak too", () => {
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={() => {}}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      getInput().dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          inputType: "insertLineBreak",
        }),
      );
      expect(onKey).toHaveBeenCalledExactlyOnceWith("enter");
    });

    it("sends 'backspace' on deleteContentBackward (empty-field path)", () => {
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={() => {}}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      getInput().dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          inputType: "deleteContentBackward",
        }),
      );
      expect(onKey).toHaveBeenCalledExactlyOnceWith("backspace");
    });
  });

  describe("keydown path (iOS / physical keyboards)", () => {
    function dispatchKeyDown(input: HTMLInputElement, key: string, init: KeyboardEventInit = {}) {
      return input.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
      );
    }

    it("sends type for a single printable char and prevents default", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const ev = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true });
      getInput().dispatchEvent(ev);
      expect(onType).toHaveBeenCalledExactlyOnceWith("a");
      expect(onKey).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(true);
    });

    it("sends key for arrow keys", () => {
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={() => {}}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      const input = getInput();
      for (const key of ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]) {
        dispatchKeyDown(input, key);
      }
      expect(onKey.mock.calls).toEqual([["up"], ["down"], ["left"], ["right"]]);
    });

    it("ignores 'Unidentified' (Android composition hands control to beforeinput)", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(
        <ManualControl
          onType={onType}
          onKey={onKey}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      dispatchKeyDown(getInput(), "Unidentified");
      expect(onType).not.toHaveBeenCalled();
      expect(onKey).not.toHaveBeenCalled();
    });
  });

  describe("same-machine warning", () => {
    function setHostname(value: string) {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { ...window.location, hostname: value },
      });
    }

    afterEach(() => {
      setHostname("localhost");
    });

    it("renders the banner when the client is on the same machine (localhost)", () => {
      setHostname("localhost");
      render(
        <ManualControl
          onType={() => {}}
          onKey={() => {}}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      expect(screen.getByRole("status").textContent).toMatch(/Same machine/i);
    });

    it("does not render the banner when the client is on a remote hostname", () => {
      setHostname("lute.tail.ts.net");
      render(
        <ManualControl
          onType={() => {}}
          onKey={() => {}}
          onPad={() => {}}
          onTap={() => {}}
          onDrag={() => {}}
          sensitivity={1}
        />,
      );
      expect(screen.queryByRole("status")).toBeNull();
    });
  });
});