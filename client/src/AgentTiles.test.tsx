/** Direct tests for :component:`AgentTiles` (issue #180).
 *
 * The wire surface (App shows the chrome button only once an ``agents``
 * frame lands, badges the needs-you count, routes to the view) lives in
 * :file:`App.agents.test.tsx`; this file covers the component's own
 * rendering rules.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentTiles } from "./AgentTiles";
import { formatAge } from "./agent-format";
import type { AgentEntry } from "./protocol";

afterEach(cleanup);

const NOW = 1_800_000_000_000;
const sec = NOW / 1000;

function agent(over: Partial<AgentEntry>): AgentEntry {
  return { source: "paseo", id: "a", title: "Do a thing", state: "idle", cwd: null, detail: null, since: null, ...over };
}

describe("AgentTiles", () => {
  it("explains a missing source", () => {
    render(<AgentTiles agents={undefined} now={NOW} />);
    expect(screen.getByText("agent status: no source configured")).toBeTruthy();
  });

  it("says when there are no live agents", () => {
    render(<AgentTiles agents={[]} now={NOW} />);
    expect(screen.getByText("no live agents")).toBeTruthy();
  });

  it("renders tiles in wire order with a text state label", () => {
    render(
      <AgentTiles
        now={NOW}
        agents={[
          agent({ id: "1", title: "Ask", state: "needs_input", detail: "Approve Bash", cwd: "/src/deckd", since: sec - 95 }),
          agent({ id: "2", title: "Build", state: "working", since: sec - 3 }),
          agent({ id: "3", title: "Old", state: "idle", since: sec - 7200 }),
        ]}
      />,
    );
    const tiles = screen.getAllByRole("listitem");
    expect(tiles.map((t) => t.getAttribute("data-agent-id"))).toEqual(["1", "2", "3"]);
    const first = within(tiles[0]);
    expect(tiles[0].getAttribute("data-state")).toBe("needs_input");
    expect(tiles[0].className).toContain("agent-tile-needs_input");
    expect(first.getByText("Needs you")).toBeTruthy();
    expect(first.getByText("Ask")).toBeTruthy();
    expect(first.getByText("Approve Bash")).toBeTruthy();
    expect(first.getByText("deckd")).toBeTruthy();
    expect(first.getByText("1m")).toBeTruthy();
    expect(within(tiles[1]).getByText("Working")).toBeTruthy();
    expect(within(tiles[1]).getByText("now")).toBeTruthy();
    expect(within(tiles[2]).getByText("2h")).toBeTruthy();
  });

  it("keys tiles by source and id so two sources can share an id", () => {
    render(
      <AgentTiles
        now={NOW}
        agents={[agent({ source: "paseo", id: "x", title: "P" }), agent({ source: "claude-code", id: "x", title: "C" })]}
      />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});

describe("formatAge", () => {
  it.each([
    [null, null],
    [sec - 5, "now"],
    [sec - 45, "45s"],
    [sec - 600, "10m"],
    [sec - 3 * 3600, "3h"],
    [sec - 2 * 86400, "2d"],
    [sec + 30, "now"],
  ])("%s -> %s", (since, expected) => {
    expect(formatAge(since, NOW)).toBe(expected);
  });
});
