/** Agent tiles in the App (issue #180).
 *
 * Paseo is an ordinary app: when the daemon resolves focus to the Paseo
 * deck (desktop app identity, or the web app via its live agent titles)
 * it pushes a deck whose single full-surface ``agents`` widget renders
 * the global ``agents`` snapshot. There is no chrome button or separate
 * view for it.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEntry, ServerAgents, ServerDeck } from "./protocol";

let deckHandler: ((m: ServerDeck) => void) | null = null;
let agentsHandler: ((m: ServerAgents) => void) | null = null;
vi.mock("./socket", () => ({
  useDeckdSocket: (...args: unknown[]) => {
    // Positional: onDeck (0), …, onSessionState (6), onMediaError (7), onAgents (8).
    deckHandler = args[0] as (m: ServerDeck) => void;
    agentsHandler = (args[8] as ((m: ServerAgents) => void) | undefined) ?? null;
    return { status: "open", send: vi.fn(), authenticate: vi.fn(), deauthenticate: vi.fn(), hasPassword: false };
  },
}));

import { App } from "./App";

const PASEO_DECK: ServerDeck = {
  type: "deck",
  app: "paseo",
  display_name: "Paseo",
  jogstrip_enabled: false,
  widgets: [{ id: "agents", kind: "agents", size: "full" }],
} as ServerDeck;

function agent(id: string, state: AgentEntry["state"]): AgentEntry {
  return { source: "paseo", id, title: `Agent ${id}`, state, cwd: "/src/deckd", detail: null, since: null };
}

describe("App — Paseo deck", () => {
  afterEach(cleanup);
  beforeEach(() => {
    deckHandler = null;
    agentsHandler = null;
    window.history.replaceState(null, "", "/");
  });

  it("renders live agent tiles when the Paseo deck is focused", () => {
    render(<App />);
    act(() => deckHandler?.(PASEO_DECK));
    act(() => agentsHandler?.({ type: "agents", agents: [agent("1", "needs_input"), agent("2", "working")] }));
    const region = screen.getByRole("region", { name: "agents" });
    expect(region.querySelectorAll(".agent-tile")).toHaveLength(2);
    act(() => agentsHandler?.({ type: "agents", agents: [agent("2", "working")] }));
    expect(region.querySelectorAll(".agent-tile")).toHaveLength(1);
  });

  it("adds no chrome button for agents", () => {
    render(<App />);
    act(() => agentsHandler?.({ type: "agents", agents: [agent("1", "needs_input")] }));
    expect(screen.queryByRole("button", { name: /agents/i })).toBeNull();
  });
});
