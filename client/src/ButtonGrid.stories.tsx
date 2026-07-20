import type { Story } from "@ladle/react";
import { ButtonGrid } from "./ButtonGrid";
import { DEMO_LAYOUTS } from "./demo";

export default { title: "ButtonGrid" };

const noop = () => {};

// ButtonGrid fills its parent (height: 100%), so give stories a fixed frame.
function Frame({ name }: { name: keyof typeof DEMO_LAYOUTS }) {
  return (
    <div style={{ height: 440, maxWidth: 820 }}>
      <ButtonGrid
        widgets={DEMO_LAYOUTS[name].widgets}
        onPress={noop}
        onJog={noop}
        onJogEnd={noop}
        scrollScale={3}
        scrollInvert={false}
      />
    </div>
  );
}

export const Firefox: Story = () => <Frame name="firefox" />;
export const Default: Story = () => <Frame name="default" />;

/** All icon sources + edge cases in one grid: Lucide glyphs, per-button
 * colour, lazily-loaded Simple Icons brand logos, a no-icon button, and an
 * intentionally-unknown icon (dashed placeholder). */
export const Showcase: Story = () => <Frame name="showcase" />;
