export type View =
  | "layout"
  | "trackpad"
  | "settings"
  | "nowplaying"
  | "editor"
  | "windows"
  | "help";

const PATH_BY_VIEW: Record<View, string> = {
  layout: "/",
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

export function viewFromPath(pathname: string): View {
  return VIEW_BY_PATH[pathname] ?? "layout";
}

export function pathForView(view: View): string {
  return PATH_BY_VIEW[view];
}
