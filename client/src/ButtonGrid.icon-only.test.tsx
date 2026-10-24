import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ButtonGrid } from "./ButtonGrid";
import type { Widget } from "./protocol";

const grid = (widgets: Widget[]) =>
  render(
    <ButtonGrid widgets={widgets} onPress={vi.fn()} onJog={vi.fn()} onJogEnd={vi.fn()} scrollScale={1} scrollInvert={false} />,
  );

describe("ButtonGrid icon-only buttons", () => {
  afterEach(cleanup);

  it("marks a button with an icon and no label as icon-only (it gets the big glyph)", () => {
    grid([
      { id: "firefox", kind: "button", icon: { source: "simple-icons", name: "firefox" }, action: { shell: "firefox" } } as Widget,
      { id: "find", kind: "button", label: "Find", icon: { source: "lucide", name: "search" }, action: { key: "ctrl+f" } } as Widget,
      { id: "plain", kind: "button", label: "Plain", action: { key: "a" } } as Widget,
    ]);
    expect(screen.getByRole("button", { name: "firefox" }).className).toContain("cell-icon-only");
    expect(screen.getByRole("button", { name: "Find" }).className).not.toContain("cell-icon-only");
    expect(screen.getByRole("button", { name: "Plain" }).className).not.toContain("cell-icon-only");
  });
});
