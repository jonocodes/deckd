import type { Story } from "@ladle/react";
import { AgentTiles } from "./AgentTiles";
import { AgentFleet } from "./playground/mock-daemon";

export default { title: "AgentTiles" };

const NOW = 1_800_000_000_000;

/** A fleet as the Paseo bridge reports it — the Playground fixture, frozen
 * at one clock so the ages are stable. Wire order is urgency order. */
export const Default: Story = () => (
  <div style={{ display: "grid", width: 720, height: 420, border: "1px solid #30363d" }}>
    <AgentTiles agents={new AgentFleet().snapshot(NOW / 1000).agents} now={NOW} />
  </div>
);

/** Source up, nothing live (Paseo running with no open agents, or the
 * bridge just lost its upstream). */
export const Empty: Story = () => (
  <div style={{ display: "grid", width: 480, height: 300, border: "1px solid #30363d" }}>
    <AgentTiles agents={[]} now={NOW} />
  </div>
);
