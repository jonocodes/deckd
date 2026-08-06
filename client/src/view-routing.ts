export type View = "layout" | "trackpad" | "settings" | "mediabrowser" | "editor" | "windows";

const PATH_BY_VIEW: Record<View, string> = {
  layout: "/",
  trackpad: "/trackpad",
  settings: "/settings",
  mediabrowser: "/media-browser",
  editor: "/editor",
  windows: "/windows",
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
