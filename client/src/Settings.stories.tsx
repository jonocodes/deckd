import type { Story } from "@ladle/react";
import { Settings } from "./Settings";
import { DEMO_LAYOUTS } from "./demo";

export default { title: "Settings" };

const noop = () => {};

/** The settings panel with representative values, mounted inside a fixed
 * ``.surface`` frame the way ``App`` renders it. */
export const Default: Story = () => (
  <main className="surface" style={{ width: 390, height: 780 }}>
    <Settings
      layout={DEMO_LAYOUTS.vlc}
      status="open"
      scrollScale={3}
      scrollInvert={false}
      onScrollScaleChange={noop}
      onScrollInvertChange={noop}
      trackpadSensitivity={1}
      onTrackpadSensitivityChange={noop}
      wakeLockEnabled
      onWakeLockChange={noop}
      contentScale={1}
      onContentScaleChange={noop}
      jogWidth={1}
      onJogWidthChange={noop}
      bottomScale={1}
      onBottomScaleChange={noop}
      labelScale={1}
      onLabelScaleChange={noop}
      canDeauthenticate
      onDeauthenticate={noop}
    />
  </main>
);
