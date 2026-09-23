import type { Story } from "@ladle/react";
import { ReflowHelp } from "./ReflowHelp";

export default { title: "ReflowHelp" };

const noop = () => {};

/** The in-app mount: a close button and the apply-on-close prompt. */
export const InApp: Story = () => (
  <main className="surface" style={{ width: 390, height: 780 }}>
    <ReflowHelp minCell={100} maxCell={240} overflow="clip" onApply={noop} onClose={noop} />
  </main>
);

/** The standalone mount (``help.html``): no close, no apply — the sliders are
 * a sandbox only. */
export const Standalone: Story = () => (
  <div className="help-page" style={{ width: 390, height: 780 }}>
    <ReflowHelp />
  </div>
);
