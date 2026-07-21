import type { Story } from "@ladle/react";
import type { CSSProperties } from "react";
import { ButtonGrid } from "./ButtonGrid";
import { DEMO_LAYOUTS } from "./demo";
import {
  CONTENT_SCALE_DEFAULT,
  CONTENT_SCALE_MAX,
  CONTENT_SCALE_MIN,
  CONTENT_SCALE_STEP,
} from "./settings-store";

export default { title: "ButtonGrid" };

const noop = () => {};

type ContentScaleArgs = { contentScale: number };

/** Mirror the app's content-scale setting (the settings-view slider) as a
 * Ladle range control, so different button sizes can be compared without
 * touching localStorage. Same min/max/step as the real setting. */
const contentScaleControl = {
  args: { contentScale: CONTENT_SCALE_DEFAULT },
  argTypes: {
    contentScale: {
      control: {
        type: "range" as const,
        min: CONTENT_SCALE_MIN,
        max: CONTENT_SCALE_MAX,
        step: CONTENT_SCALE_STEP,
      },
    },
  },
};

// ButtonGrid fills its parent (height: 100%), so give stories a fixed frame.
function Frame({
  name,
  contentScale,
}: { name: keyof typeof DEMO_LAYOUTS } & ContentScaleArgs) {
  return (
    <div
      style={
        { height: 440, maxWidth: 820, "--content-scale": contentScale } as CSSProperties
      }
    >
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

export const Firefox: Story<ContentScaleArgs> = ({ contentScale }) => (
  <Frame name="firefox" contentScale={contentScale} />
);
Firefox.args = contentScaleControl.args;
Firefox.argTypes = contentScaleControl.argTypes;

export const Default: Story<ContentScaleArgs> = ({ contentScale }) => (
  <Frame name="default" contentScale={contentScale} />
);
Default.args = contentScaleControl.args;
Default.argTypes = contentScaleControl.argTypes;

/** All icon sources + edge cases in one grid: Lucide glyphs, per-button
 * colour, lazily-loaded Simple Icons brand logos, a no-icon button, and an
 * intentionally-unknown icon (dashed placeholder). */
export const Showcase: Story<ContentScaleArgs> = ({ contentScale }) => (
  <Frame name="showcase" contentScale={contentScale} />
);
Showcase.args = contentScaleControl.args;
Showcase.argTypes = contentScaleControl.argTypes;
