/** Lazily-imported Simple Icons set, indexed by slug.

Bundle strategy: Lucide (UI glyphs, on most buttons) is bundled whole so
it renders synchronously. Simple Icons (brand logos, ~3450 icons, only
occasionally used) is loaded lazily as a single on-demand chunk the first
time a layout references one — so its weight is never paid unless a brand
logo is actually used. Loaded by both ``Icon.tsx`` (resolve one icon at a
time) and ``IconPicker.tsx`` (enumerate all of them for the grid).

Kept in a non-component file so React fast refresh keeps working in the
Icon component file (rule: a file exporting a component should export
only components).
*/

export type SimpleIcon = { slug: string; path: string; title: string };

let simpleIconsPromise: Promise<Map<string, SimpleIcon>> | null = null;

export function loadSimpleIcons(): Promise<Map<string, SimpleIcon>> {
  if (!simpleIconsPromise) {
    simpleIconsPromise = import("simple-icons").then((mod) => {
      const m = new Map<string, SimpleIcon>();
      for (const value of Object.values(mod)) {
        if (value && typeof value === "object" && "slug" in value && "path" in value) {
          const icon = value as SimpleIcon;
          m.set(icon.slug, icon);
        }
      }
      return m;
    });
  }
  return simpleIconsPromise;
}
