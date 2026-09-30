import type { Story } from "@ladle/react";
import { Editor } from "./Editor";
import { DEMO_DECKS, EDITOR_DEMO_DECKS } from "./demo";

export default { title: "Editor" };

const noop = () => {};

export const Firefox: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      deck={DEMO_DECKS.firefox}
      send={noop}
      onExit={noop}
      mockDecks={EDITOR_DEMO_DECKS}
    />
  </div>
);

export const NoActiveDeck: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      deck={null}
      send={noop}
      onExit={noop}
      mockDecks={EDITOR_DEMO_DECKS}
    />
  </div>
);

export const EmptyPickers: Story = () => (
  <div style={{ height: 700, maxWidth: 960, border: "1px solid #30363d" }}>
    <Editor
      deck={null}
      send={noop}
      onExit={noop}
      mockDecks={[]}
    />
  </div>
);
