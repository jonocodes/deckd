/** Agent tiles formatting helpers (issue #180), split from
 * :component:`AgentTiles` so that file only exports components. */
import type { AgentEntry } from "./protocol";

export type AgentState = AgentEntry["state"];

export const AGENT_STATE_LABEL: Record<AgentState, string> = {
  needs_input: "Needs you",
  error: "Error",
  working: "Working",
  done: "Done",
  idle: "Idle",
  offline: "Offline",
};

/** "now", "45s", "12m", "3h", "2d" — compact enough for a tile corner. */
export function formatAge(sinceSec: number | null | undefined, nowMs: number): string | null {
  if (sinceSec == null) return null;
  const s = Math.max(0, Math.floor(nowMs / 1000 - sinceSec));
  if (s < 10) return "now";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}
