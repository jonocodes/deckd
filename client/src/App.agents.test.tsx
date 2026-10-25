/** Agent tiles chrome view (issue #180).
 *
 * Contracts:
 *  1. No ``agents`` frame -> no chrome button (the daemon has no agent
 *     source; the affordance would only ever show an empty state).
 *  2. First frame -> the button appears; clicking it opens the
 *     client-local ``agents`` view (no ``select_view`` on the wire —
 *     tiles are global data, not a deck) and a second click closes it.
 *  3. Agents in ``needs_input`` badge the button with a count, so the
 *     "an agent needs you" signal is visible from every deck.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentEntry, ClientMessage, ServerAgents } from "./protocol";

const send = vi.fn<(message: ClientMessage) => void>();
let agentsHandler: ((m: ServerAgents) => void) | null = null;
vi.mock("./socket", () => ({
  useDeckdSocket: (...args: unknown[]) => {
    // Positional: ..., onSessionState (6), onMediaError (7), onAgents (8).
    agentsHandler = (args[8] as ((m: ServerAgents) => void) | undefined) ?? null;
    return { status: "open", send, authenticate: vi.fn(), deauthenticate: vi.fn(), hasPassword: false };
  },
}));

import { App } from "./App";

function agent(id: string, state: AgentEntry["state"]): AgentEntry {
  return { source: "paseo", id, title: `Agent ${id}`, state, cwd: "/src/deckd", detail: null, since: null };
}

function push(agents: AgentEntry[]) {
  act(() => agentsHandler?.({ type: "agents", agents }));
}

describe("App — agents chrome button", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    agentsHandler = null;
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("hides the button until the daemon sends an agents frame", () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: /^agents/ })).toBeNull();
    push([]);
    expect(screen.getByRole("button", { name: "agents" })).toBeTruthy();
  });

  it("opens and closes the client-local agents view", () => {
    render(<App />);
    push([agent("1", "working"), agent("2", "idle")]);
    const button = screen.getByRole("button", { name: "agents" });
    fireEvent.pointerDown(button);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    const region = screen.getByRole("region", { name: "agents" });
    expect(region.querySelectorAll(".agent-tile")).toHaveLength(2);
    expect(send.mock.calls.some(([m]) => m.type === "select_view")).toBe(false);
    fireEvent.pointerDown(button);
    expect(screen.queryByRole("region", { name: "agents" })).toBeNull();
  });

  it("badges the button with the needs-you count and updates live", () => {
    render(<App />);
    push([agent("1", "needs_input"), agent("2", "needs_input"), agent("3", "working")]);
    const button = screen.getByRole("button", { name: "agents, 2 need you" });
    expect(button.className).toContain("chrome-btn-agents-alert");
    expect(button.querySelector(".chrome-btn-badge")?.textContent).toBe("2");
    push([agent("3", "working")]);
    expect(screen.getByRole("button", { name: "agents" }).querySelector(".chrome-btn-badge")).toBeNull();
  });
});
