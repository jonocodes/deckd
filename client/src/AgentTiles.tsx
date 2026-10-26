/** Agent tiles: the ``agents`` widget's surface (issue #180).
 *
 * View-only fleet view: one tile per live AI coding agent, coloured by
 * state. The daemon translates every source (Paseo today) into the same
 * six-value ``state`` and sends the list already sorted most-urgent
 * first, so this component renders in wire order and knows nothing
 * about any orchestrator.
 *
 * State is never conveyed by colour alone: every tile carries a text
 * label, and ``needs_input`` additionally pulses (motion-reduced
 * users get a static ring).
 */
import { useEffect, useState } from "react";
import type { AgentEntry } from "./protocol";
import { AGENT_STATE_LABEL, formatAge } from "./agent-format";

export type AgentTilesProps = {
  /** ``undefined`` while no ``agents`` frame has landed — the daemon has
   *  no agent source configured (e.g. ``--agents off``) yet a deck with
   *  an ``agents`` widget is focused. */
  agents: AgentEntry[] | undefined;
  /** Clock override for tests and stories (epoch ms). */
  now?: number;
};

function projectName(cwd: string | null | undefined): string | null {
  if (!cwd) return null;
  const parts = cwd.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || null;
}

function useNow(override: number | undefined, intervalMs = 15_000): number {
  const [now, setNow] = useState(() => override ?? Date.now());
  useEffect(() => {
    if (override !== undefined) return;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [override, intervalMs]);
  return override ?? now;
}

export function AgentTiles({ agents, now }: AgentTilesProps) {
  const nowMs = useNow(now);
  if (agents === undefined) {
    return (
      <div className="agents" role="region" aria-label="agents">
        <div className="agents-empty">agent status: no source configured</div>
      </div>
    );
  }
  if (agents.length === 0) {
    return (
      <div className="agents" role="region" aria-label="agents">
        <div className="agents-empty">no live agents</div>
      </div>
    );
  }
  return (
    <div className="agents" role="region" aria-label="agents">
      <ul className="agents-grid">
        {agents.map((agent) => (
          <AgentTile key={`${agent.source}:${agent.id}`} agent={agent} nowMs={nowMs} />
        ))}
      </ul>
    </div>
  );
}

function AgentTile({ agent, nowMs }: { agent: AgentEntry; nowMs: number }) {
  const project = projectName(agent.cwd);
  const age = formatAge(agent.since, nowMs);
  return (
    <li
      className={`agent-tile agent-tile-${agent.state}`}
      data-agent-id={agent.id}
      data-state={agent.state}
      title={agent.cwd ?? undefined}
    >
      <div className="agent-tile-head">
        <span className="agent-tile-state">{AGENT_STATE_LABEL[agent.state]}</span>
        {age && <span className="agent-tile-age">{age}</span>}
      </div>
      <div className="agent-tile-title">{agent.title}</div>
      {(agent.detail || project) && (
        <div className="agent-tile-foot">
          {agent.detail ? <span className="agent-tile-detail">{agent.detail}</span> : null}
          {project ? <span className="agent-tile-project">{project}</span> : null}
        </div>
      )}
    </li>
  );
}
