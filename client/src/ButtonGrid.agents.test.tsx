/** ``agents`` widget + ADR-0010 full-surface widgets (issue #180).
 *
 * A ``size: full`` widget takes the whole deck area instead of a grid
 * cell; the Paseo deck is one such widget of kind ``agents``, which
 * renders the daemon's global agent snapshot.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ButtonGrid } from "./ButtonGrid";
import type { AgentEntry, Widget } from "./protocol";

const AGENTS: AgentEntry[] = [
  { source: "paseo", id: "1", title: "Ask", state: "needs_input", cwd: null, detail: "Approve Bash", since: null },
  { source: "paseo", id: "2", title: "Build", state: "working", cwd: null, detail: null, since: null },
];

function grid(widgets: Widget[], agents?: AgentEntry[]) {
  return render(
    <ButtonGrid
      widgets={widgets}
      onPress={vi.fn()}
      onJog={vi.fn()}
      onJogEnd={vi.fn()}
      scrollScale={1}
      scrollInvert={false}
      agents={agents}
    />,
  );
}

describe("ButtonGrid agents widget", () => {
  afterEach(cleanup);

  it("renders the agent tiles as a full-surface widget", () => {
    const { container } = grid([{ id: "agents", kind: "agents", size: "full" }], AGENTS);
    expect(container.querySelector(".grid")?.className).toContain("grid-full");
    const region = screen.getByRole("region", { name: "agents" });
    expect([...region.querySelectorAll(".agent-tile")].map((t) => t.getAttribute("data-agent-id"))).toEqual(["1", "2"]);
  });

  it("explains a missing agent source", () => {
    grid([{ id: "agents", kind: "agents", size: "full" }], undefined);
    expect(screen.getByText("agent status: no source configured")).toBeTruthy();
  });

  it("a full widget takes the surface; the rest of the deck is not rendered", () => {
    grid(
      [
        { id: "b", kind: "button", label: "Hidden", action: { key: "a" } } as Widget,
        { id: "agents", kind: "agents", size: "full" },
      ],
      AGENTS,
    );
    expect(screen.queryByRole("button", { name: "Hidden" })).toBeNull();
    expect(screen.getByRole("region", { name: "agents" })).toBeTruthy();
  });

  it("flow decks are unchanged", () => {
    const { container } = grid([{ id: "b", kind: "button", label: "Go", action: { key: "a" } } as Widget]);
    expect(container.querySelector(".grid")?.className).toBe("grid");
    expect(screen.getByRole("button", { name: "Go" })).toBeTruthy();
  });
});
