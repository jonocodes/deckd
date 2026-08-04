import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmModal } from "./ConfirmModal";
import type { Widget } from "./protocol";

const WIDGET: Widget = {
  id: "rm-all",
  kind: "button",
  label: "Remove all",
  icon: { source: "lucide", name: "trash-2" },
  confirm: true,
  action: { shell: "rm -rf /" },
};

describe("ConfirmModal", () => {
  afterEach(cleanup);

  it("renders the dialog with the widget label and both action buttons", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="abc"
        widget={WIDGET}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/Confirm action\?/)).toBeTruthy();
    // Body shows the widget label in bold.
    expect(screen.getByText(/Remove all/).tagName).toBe("STRONG");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });

  it("calls onConfirm with the daemon-minted id when Confirm is pressed", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="tok-1"
        widget={WIDGET}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledWith("tok-1");
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("calls onCancel with the daemon-minted id when Cancel is pressed", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="tok-2"
        widget={WIDGET}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledWith("tok-2");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("calls onCancel when Escape is pressed (Variant A keyboard contract)", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="tok-3"
        widget={WIDGET}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).toHaveBeenCalledWith("tok-3");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("falls back to the widget id when label is missing", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="tok-4"
        widget={{ id: "rm-all", kind: "button", confirm: true }}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    // The id appears in the modal body as the fallback display name.
    expect(screen.getByText(/rm-all/)).toBeTruthy();
  });

  it("focuses Confirm by default so a keyboard Enter triggers it", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmModal
        confirmId="tok-5"
        widget={WIDGET}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    // The Confirm button receives focus on mount.
    const confirmBtn = screen.getByRole("button", { name: "Confirm" });
    expect(document.activeElement).toBe(confirmBtn);
    fireEvent.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledWith("tok-5");
  });
});
