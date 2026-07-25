import type { Story } from "@ladle/react";
import { ManualControl } from "./ManualControl";

export default { title: "Trackpad" };

const noop = () => {};

/** The manual-control (trackpad) view — key strip, pad surface, and text
 * input — mounted inside a fixed ``.surface`` frame as ``App`` renders it. */
export const Default: Story = () => (
  <main className="surface" style={{ width: 390, height: 780 }}>
    <ManualControl
      onType={noop}
      onKey={noop}
      onPad={noop}
      onTap={noop}
      onDrag={noop}
      sensitivity={1}
    />
  </main>
);
