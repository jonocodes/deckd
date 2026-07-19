import type { Story } from "@ladle/react";
import { JogStrip } from "./JogStrip";

export default { title: "JogStrip" };

const noop = () => {};

/** The in-grid jogstrip: scroll glyph, label, and hint. */
export const Grid: Story = () => (
  <div style={{ width: 160, height: 320 }}>
    <JogStrip
      widget={{ id: "scroll", label: "Scroll" }}
      variant="grid"
      scale={3}
      invert={false}
      onJog={noop}
      onJogEnd={noop}
    />
  </div>
);

/** The always-on chrome jogstrip (narrower, quieter). */
export const Chrome: Story = () => (
  <div className="chrome-jogstrip" style={{ height: 320 }}>
    <JogStrip
      widget={{ id: "__chrome__" }}
      variant="chrome"
      scale={3}
      invert={false}
      onJog={noop}
      onJogEnd={noop}
    />
  </div>
);
