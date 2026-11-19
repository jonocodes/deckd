/** Toast for an action the OS refused (issue #196).
 *
 * The daemon answers a key press macOS blocked (missing Accessibility or
 * Automation) with an ``action_error`` frame; the toast shows its message
 * right away. The banner carries the fix steps, so the toast only says what
 * happened and can be dismissed.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionErrorToast } from "./ActionErrorToast";

afterEach(cleanup);

const MESSAGE = "Key press blocked: deckd.app needs Accessibility permission.";

describe("ActionErrorToast", () => {
  it("shows the daemon's message in a polite live region", () => {
    const { container } = render(<ActionErrorToast message={MESSAGE} onDismiss={() => {}} />);
    expect(screen.getByText(MESSAGE)).toBeTruthy();
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();
  });

  it("offers Dismiss, and no Retry: a retry would be refused the same way", () => {
    const onDismiss = vi.fn();
    render(<ActionErrorToast message={MESSAGE} onDismiss={onDismiss} />);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
