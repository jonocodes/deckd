import type { Story } from "@ladle/react";
import { ButtonGrid } from "./ButtonGrid";
import { DEMO_LAYOUTS } from "./demo";
import {
  CELL_SIZE_MIN,
  CELL_SIZE_MAX,
  CELL_SIZE_DEFAULT,
  CELL_SIZE_STEP,
} from "./settings-store";

export default { title: "Surface / device sizes" };

const noop = () => {};

type Controls = { cellSize: number };

const controls = {
  args: { cellSize: CELL_SIZE_DEFAULT },
  argTypes: {
    cellSize: {
      control: { type: "range" as const, min: CELL_SIZE_MIN, max: CELL_SIZE_MAX, step: CELL_SIZE_STEP },
    },
  },
};

function Device({
  w,
  h,
  layout = "firefox",
  cellSize,
}: {
  w: number;
  h: number;
  layout?: keyof typeof DEMO_LAYOUTS;
} & Controls) {
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
          onPress={noop}
          onJog={noop}
          onJogEnd={noop}
          scrollScale={3}
          scrollInvert={false}
          cellSize={cellSize}
        />
      </div>
      <span style={{ fontSize: 12, color: "#8a96a3" }}>
        {w}×{h}
      </span>
    </div>
  );
}

export const PhoneLandscape: Story<Controls> = (args) => <Device w={844} h={390} {...args} />;
PhoneLandscape.args = controls.args;
PhoneLandscape.argTypes = controls.argTypes;

export const PhonePortrait: Story<Controls> = (args) => <Device w={390} h={844} {...args} />;
PhonePortrait.args = controls.args;
PhonePortrait.argTypes = controls.argTypes;

/** S23 Firefox grid area (viewport minus chrome/jogstrip) — landscape. */
export const S23Landscape: Story<Controls> = (args) => <Device w={747} h={251} {...args} />;
S23Landscape.args = controls.args;
S23Landscape.argTypes = controls.argTypes;

/** S23 Firefox grid area — portrait. */
export const S23Portrait: Story<Controls> = (args) => <Device w={360} h={668} {...args} />;
S23Portrait.args = controls.args;
S23Portrait.argTypes = controls.argTypes;

export const Tablet7Landscape: Story<Controls> = (args) => <Device w={1024} h={600} {...args} />;
Tablet7Landscape.args = controls.args;
Tablet7Landscape.argTypes = controls.argTypes;

export const Tablet10Landscape: Story<Controls> = (args) => <Device w={1194} h={834} {...args} />;
Tablet10Landscape.args = controls.args;
Tablet10Landscape.argTypes = controls.argTypes;

export const Tablet10Portrait: Story<Controls> = (args) => <Device w={834} h={1194} {...args} />;
Tablet10Portrait.args = controls.args;
Tablet10Portrait.argTypes = controls.argTypes;
