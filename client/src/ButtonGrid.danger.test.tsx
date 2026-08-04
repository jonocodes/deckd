import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ButtonGrid } from "./ButtonGrid";
import type { Widget } from "./protocol";

function makeWidget(overrides: Partial<Widget>): Widget {
  return {
    id: "btn",
    kind: "button",
    label: "Press me",
    action: { key: "a" },
    ...overrides,
  } as Widget;
}

describe("ButtonGrid danger affordance", () => {
  afterEach(cleanup);

  it("marks confirm:true widgets with the danger class and a warning badge", () => {
    const widget = makeWidget({ id: "rm", confirm: true, label: "Delete" });
    render(
      <ButtonGrid
        widgets={[widget]}
        onPress={vi.fn()}
        onJog={vi.fn()}
        onJogEnd={vi.fn()}
        scrollScale={1}
        scrollInvert={false}
      />,
    );
    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn.className).toContain("cell-danger");
    expect(btn.getAttribute("data-confirm-dangerous")).toBe("true");
    // The warning badge lives inside the button as a small marker.
    const badge = btn.querySelector(".cell-danger-badge");
    expect(badge).not.toBeNull();
  });

  it("does not mark safe widgets as dangerous", () => {
    const widget = makeWidget({ id: "safe", label: "Safe" });
    render(
      <ButtonGrid
        widgets={[widget]}
        onPress={vi.fn()}
        onJog={vi.fn()}
        onJogEnd={vi.fn()}
        scrollScale={1}
        scrollInvert={false}
      />,
    );
    const btn = screen.getByRole("button", { name: "Safe" });
    expect(btn.className).not.toContain("cell-danger");
    expect(btn.getAttribute("data-confirm-dangerous")).toBeNull();
    const badge = btn.querySelector(".cell-danger-badge");
    expect(badge).toBeNull();
  });
});
