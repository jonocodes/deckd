import type { Story } from "@ladle/react";
import type { CSSProperties } from "react";
import { ButtonGrid } from "./ButtonGrid";
import { DEMO_LAYOUTS } from "./demo";
import {
  CELL_SIZE_MIN,
  CELL_SIZE_MAX,
  CELL_SIZE_DEFAULT,
  CELL_SIZE_STEP,
  CONTENT_SCALE_DEFAULT,
  CONTENT_SCALE_MAX,
  CONTENT_SCALE_MIN,
  CONTENT_SCALE_STEP,
} from "./settings-store";

export default { title: "ButtonGrid" };

const noop = () => {};

type Controls = { contentScale: number; cellSize: number };

const controls = {
  args: { contentScale: CONTENT_SCALE_DEFAULT, cellSize: CELL_SIZE_DEFAULT },
  argTypes: {
    contentScale: {
      control: { type: "range" as const, min: CONTENT_SCALE_MIN, max: CONTENT_SCALE_MAX, step: CONTENT_SCALE_STEP },
    },
    cellSize: {
      control: { type: "range" as const, min: CELL_SIZE_MIN, max: CELL_SIZE_MAX, step: CELL_SIZE_STEP },
    },
  },
};

function Frame({
  name,
  contentScale,
  cellSize,
  showKeyHints,
}: { name: keyof typeof DEMO_LAYOUTS; showKeyHints?: boolean } & Controls) {
  return (
    <div
      style={
        {
          height: 440,
          maxWidth: 820,
          "--content-scale": contentScale,
        } as CSSProperties
      }
    >
      <ButtonGrid
        widgets={DEMO_LAYOUTS[name].widgets}
        onPress={noop}
        onJog={noop}
        onJogEnd={noop}
        scrollScale={3}
        scrollInvert={false}
        onMediaCommand={noop}
        showKeyHints={showKeyHints}
        cellSize={cellSize}
      />
    </div>
  );
}

export const Firefox: Story<Controls> = (args) => <Frame name="firefox" {...args} />;
Firefox.args = controls.args;
Firefox.argTypes = controls.argTypes;

export const Default: Story<Controls> = (args) => <Frame name="default" {...args} />;
Default.args = controls.args;
Default.argTypes = controls.argTypes;

export const Showcase: Story<Controls> = (args) => <Frame name="showcase" {...args} />;
Showcase.args = controls.args;
Showcase.argTypes = controls.argTypes;

export const KeyHints: Story<Controls> = (args) => <Frame name="firefox" {...args} showKeyHints />;
KeyHints.args = controls.args;
KeyHints.argTypes = controls.argTypes;
