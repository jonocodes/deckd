import type { Story } from "@ladle/react";
import { Editor } from "./Editor";
import { DEMO_LAYOUTS, EDITOR_DEMO_LAYOUTS } from "./demo";

export default { title: "Editor" };

const noop = () => {};

export const Firefox: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      layout={DEMO_LAYOUTS.firefox}
      send={noop}
      onExit={noop}
      mockLayouts={EDITOR_DEMO_LAYOUTS}
    />
  </div>
);

export const NoActiveLayout: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      layout={null}
      send={noop}
      onExit={noop}
      mockLayouts={EDITOR_DEMO_LAYOUTS}
    />
  </div>
);

export const EmptyPickers: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      layout={null}
      send={noop}
      onExit={noop}
      mockLayouts={[]}
    />
  </div>
);
