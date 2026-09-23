import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReflowHelp } from "./ReflowHelp";

afterEach(cleanup);

describe("ReflowHelp — content", () => {
  it("answers the three questions the page exists for", () => {
    render(<ReflowHelp />);
    expect(screen.getByRole("heading", { name: "How your buttons are laid out" })).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Why do my buttons move?" })).not.toBeNull();
    expect(
      screen.getByRole("heading", { name: /why can.t i see all my buttons/i }),
    ).not.toBeNull();
    expect(screen.getByRole("heading", { name: /why isn.t the last row full/i })).not.toBeNull();
  });

  it("reports the sandbox layout from the real algorithm", () => {
    // 240x340 at min 100 / gap 8 holds 2x3 whole cells, so 6 of 8 show as 2+2+2.
    render(<ReflowHelp minCell={100} maxCell={240} overflow="clip" />);
    const stats = screen.getByText(/Showing 6 of 8/).closest("p");
    expect(stats).not.toBeNull();
    expect(stats?.textContent).toContain("2+2+2");
    expect(stats?.textContent).toContain("2 hidden");
  });
});

describe("ReflowHelp — apply on close", () => {
  it("closes straight away when nothing was changed", () => {
    const onClose = vi.fn();
    const onApply = vi.fn();
    render(<ReflowHelp minCell={100} maxCell={240} onClose={onClose} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("prompts before applying, and Apply writes the band then closes", () => {
    const onClose = vi.fn();
    const onApply = vi.fn();
    render(<ReflowHelp minCell={100} maxCell={240} onClose={onClose} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("Min size"), { target: { value: "160" } });
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledWith({ minCell: 160, maxCell: 240 });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Don't apply leaves the device untouched but still closes", () => {
    const onClose = vi.fn();
    const onApply = vi.fn();
    render(<ReflowHelp minCell={100} maxCell={240} onClose={onClose} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("Max size"), { target: { value: "320" } });
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    fireEvent.click(screen.getByRole("button", { name: /don.t apply/i }));
    expect(onApply).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("ReflowHelp — standalone mount", () => {
  it("has no close affordance and never shows the apply dialog", () => {
    render(<ReflowHelp />);
    expect(screen.queryByRole("button", { name: "Close help" })).toBeNull();
    // The sandbox still works as a demo.
    fireEvent.change(screen.getByLabelText("Min size"), { target: { value: "160" } });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
