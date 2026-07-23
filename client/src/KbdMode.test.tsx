import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { KbdMode } from "./KbdMode";

function getInput(): HTMLInputElement {
  return screen.getByLabelText("Remote keyboard") as HTMLInputElement;
}

describe("KbdMode", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe("sendDelta (input event path)", () => {
    it("sends the inserted text when the field grows from empty", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
      const input = getInput();
      input.value = "abc";
      fireEvent.input(input);
      expect(onType).toHaveBeenCalledExactlyOnceWith("abc");
      expect(onKey).not.toHaveBeenCalled();
    });

    it("sends one backspace per deleted tail character (single deletion)", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
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
      render(<KbdMode onType={onType} onKey={onKey} />);
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
      render(<KbdMode onType={onType} onKey={() => {}} />);
      const input = getInput();
      input.value = "abc";
      fireEvent.input(input);
      expect(input.value).toBe("");
    });

    it("does not reset the field while composition is active", () => {
      const onType = vi.fn();
      render(<KbdMode onType={onType} onKey={() => {}} />);
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
    function dispatchBeforeInput(input: HTMLInputElement, inputType: string): boolean {
      return input.dispatchEvent(
        new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType }),
      );
    }

    it("sends 'enter' on insertParagraph and prevents default", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
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
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      dispatchBeforeInput(getInput(), "insertLineBreak");
      expect(onKey).toHaveBeenCalledExactlyOnceWith("enter");
    });

    it("sends 'backspace' on deleteContentBackward (empty-field path)", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      const input = getInput();
      dispatchBeforeInput(input, "deleteContentBackward");
      expect(onKey).toHaveBeenCalledExactlyOnceWith("backspace");
    });

    it("ignores other delete variants (out of scope; no double-handling)", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      dispatchBeforeInput(getInput(), "deleteWordBackward");
      expect(onKey).not.toHaveBeenCalled();
    });

    it("ignores plain text insertions from beforeinput (the input event handles them)", () => {
      const onKey = vi.fn();
      const onType = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
      dispatchBeforeInput(getInput(), "insertText");
      expect(onKey).not.toHaveBeenCalled();
      expect(onType).not.toHaveBeenCalled();
    });
  });

  describe("keydown path (iOS / physical keyboards)", () => {
    function dispatchKeyDown(input: HTMLInputElement, key: string, init: KeyboardEventInit = {}): boolean {
      return input.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }),
      );
    }

    it("sends type for a single printable char and prevents default", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
      const ev = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true });
      getInput().dispatchEvent(ev);
      expect(onType).toHaveBeenCalledExactlyOnceWith("a");
      expect(onKey).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(true);
    });

    it("sends key for named control keys (Tab)", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      dispatchKeyDown(getInput(), "Tab");
      expect(onKey).toHaveBeenCalledExactlyOnceWith("tab");
    });

    it("sends key for arrow keys", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      const input = getInput();
      for (const key of ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]) {
        dispatchKeyDown(input, key);
      }
      expect(onKey.mock.calls).toEqual([["up"], ["down"], ["left"], ["right"]]);
    });

    it("ignores 'Unidentified' (Android composition hands control to beforeinput)", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
      dispatchKeyDown(getInput(), "Unidentified");
      expect(onType).not.toHaveBeenCalled();
      expect(onKey).not.toHaveBeenCalled();
    });

    it("ignores Ctrl-chorded keys (combos belong in layouts)", () => {
      const onType = vi.fn();
      const onKey = vi.fn();
      render(<KbdMode onType={onType} onKey={onKey} />);
      dispatchKeyDown(getInput(), "c", { ctrlKey: true });
      expect(onType).not.toHaveBeenCalled();
      expect(onKey).not.toHaveBeenCalled();
    });
  });

  describe("strip", () => {
    it("sends the combo on pointerdown and prevents default to keep input focus", () => {
      const onKey = vi.fn();
      render(<KbdMode onType={() => {}} onKey={onKey} />);
      const escButton = screen.getByLabelText("esc");
      const ev = new Event("pointerdown", { bubbles: true, cancelable: true });
      escButton.dispatchEvent(ev);
      expect(onKey).toHaveBeenCalledExactlyOnceWith("esc");
      expect(ev.defaultPrevented).toBe(true);
    });
  });
});