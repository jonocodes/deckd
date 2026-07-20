import type { Story } from "@ladle/react";
import { ButtonGrid } from "./ButtonGrid";
import { DEMO_LAYOUTS } from "./demo";
import type { Orientation } from "./orientation";

export default { title: "Surface / device sizes" };

const noop = () => {};

/** Render the grid inside a fixed device-sized frame to simulate a resolution
 * right in Ladle (a parent with fixed dimensions, per the design-tooling
 * discussion). ``orientation`` is passed explicitly because the auto-detect
 * follows the window, which a fixed container can't change. */
function Device({
  w,
  h,
  orientation,
  layout = "firefox",
}: {
  w: number;
  h: number;
  orientation: Orientation;
  layout?: keyof typeof DEMO_LAYOUTS;
}) {
  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          width: w,
          height: h,
          border: "1px solid #2a333d",
          borderRadius: 12,
          overflow: "hidden",
          padding: 10,
        }}
      >
        <ButtonGrid
          widgets={DEMO_LAYOUTS[layout].widgets}
          orientation={orientation}
          onPress={noop}
          onJog={noop}
          onJogEnd={noop}
          scrollScale={3}
          scrollInvert={false}
        />
      </div>
      <span style={{ fontSize: 12, color: "#8a96a3" }}>
        {w}×{h} · {orientation}
      </span>
    </div>
  );
}

export const PhoneLandscape: Story = () => <Device w={844} h={390} orientation="landscape" />;
export const PhonePortrait: Story = () => <Device w={390} h={844} orientation="portrait" />;
export const Tablet7Landscape: Story = () => <Device w={1024} h={600} orientation="landscape" />;
export const Tablet10Landscape: Story = () => <Device w={1194} h={834} orientation="landscape" />;
export const Tablet10Portrait: Story = () => <Device w={834} h={1194} orientation="portrait" />;
