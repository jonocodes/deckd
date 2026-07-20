import type { Story } from "@ladle/react";
import { Icon } from "./Icon";
import type { Icon as IconRef } from "./protocol";

export default { title: "Icon" };

function Swatch({ icon }: { icon: IconRef }) {
  return (
    <div className="cell-button" style={{ width: 120, height: 120 }}>
      <Icon icon={icon} className="icon" />
      <span className="label">{icon.name}</span>
    </div>
  );
}

function Wall({ icons }: { icons: IconRef[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
      {icons.map((icon, i) => (
        <Swatch key={`${icon.source}-${icon.name}-${i}`} icon={icon} />
      ))}
    </div>
  );
}

const l = (name: string): IconRef => ({ source: "lucide", name });
const s = (name: string): IconRef => ({ source: "simple-icons", name });

/** Common Lucide UI glyphs, all rendered at the one consistent icon size. */
export const LucideGlyphs: Story = () => (
  <Wall
    icons={[
      "plus", "x", "search", "link", "refresh-cw", "arrow-left", "arrow-right",
      "app-window", "globe", "terminal", "keyboard", "play", "trash-2",
      "sparkles", "columns-2", "rows-2",
    ].map(l)}
  />
);

/** Brand logos from the lazily-loaded Simple Icons set. */
export const BrandLogos: Story = () => (
  <Wall icons={["firefox", "signal", "vscodium", "github", "gnome", "linux"].map(s)} />
);

/** Edge cases: an unknown Lucide name and an unknown source both fall back to
 * the visible dashed placeholder. */
export const Missing: Story = () => (
  <Wall icons={[l("not-a-real-icon"), { source: "nope", name: "whatever" }]} />
);
