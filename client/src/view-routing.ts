export type View =
  | "deck"
  | "trackpad"
  | "settings"
  | "nowplaying"
  | "editor"
  | "windows"
  | "help";

const PATH_BY_VIEW: Record<View, string> = {
  deck: "/",
  trackpad: "/trackpad",
  settings: "/settings",
  nowplaying: "/now-playing",
  editor: "/editor",
  windows: "/windows",
  // Reached from Settings rather than an always-on chrome button: it explains
  // the sizing controls sitting right above the link (ADR-0011).
  help: "/help",
};

const VIEW_BY_PATH: Record<string, View> = Object.fromEntries(
  Object.entries(PATH_BY_VIEW).map(([view, path]) => [path, view]),
) as Record<string, View>;

// Views live under the app's base path: "/" when the daemon serves the
// client, "/deckd/app/" on GitHub Pages (Vite's ``base``, from
// VITE_BASE_PATH). The trailing slash is dropped so "/" joins as "".
const prefix = (base: string) => base.replace(/\/+$/, "");

export function viewFromPath(pathname: string, base: string = import.meta.env.BASE_URL): View {
  const p = prefix(base);
  if (p && pathname !== p && !pathname.startsWith(`${p}/`)) return "deck";
  return VIEW_BY_PATH[pathname.slice(p.length) || "/"] ?? "deck";
}

export function pathForView(view: View, base: string = import.meta.env.BASE_URL): string {
  return `${prefix(base)}${PATH_BY_VIEW[view]}`;
}
