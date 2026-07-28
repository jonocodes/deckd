/** Tiny accessibility helpers shared across the chrome and
 *  widget components (issues #60, #62).
 *
 *  Kept in one place so the Enter/Space activation contract
 *  doesn't drift between call sites: every keyboard activation
 *  handler should accept the same React keyboard event shape and
 *  call ``e.preventDefault()`` so a Space press doesn't also
 *  scroll the page when the focused control is a button. */

/** Returns an ``onKeyDown`` handler that fires ``action`` on
 *  Enter or Space. Wired alongside the component's existing
 *  ``onPointerDown`` so the touch path keeps its fast response
 *  and the keyboard path picks up native button semantics
 *  (which fire ``click`` on Enter / Space only when an
 *  ``onClick`` is attached — this helper is what keeps the
 *  codebase's ``onPointerDown``-only pattern keyboard-friendly). */
export function onActivate<E extends { key: string; preventDefault: () => void }>(
  action: () => void,
): (e: E) => void {
  return (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    action();
  };
}

/** True when a keystroke should land in the focused element
 *  rather than trigger a global shortcut. The password gate,
 *  the trackpad IME, and any settings text fields own their
 *  character keys; number keys / Escape belong to them, not to
 *  the chrome view switcher. ``contenteditable`` is covered for
 *  forward-compat. */
export function isTypingTarget(el: HTMLElement): boolean {
  if (el instanceof HTMLInputElement) {
    return !el.readOnly && el.type !== "checkbox" && el.type !== "radio" && el.type !== "button";
  }
  if (el instanceof HTMLTextAreaElement) return true;
  if (el.isContentEditable) return true;
  return false;
}