/** Icon-set loaders: the lazily-imported Simple Icons set, indexed by slug,
and the daemon-served ``source: desktop`` app icons (issue #187).

Bundle strategy: Lucide (UI glyphs, on most buttons) is bundled whole so
it renders synchronously. Simple Icons (brand logos, ~3450 icons, only
occasionally used) is loaded lazily as a single on-demand chunk the first
time a deck references one — so its weight is never paid unless a brand
logo is actually used. Loaded by both ``Icon.tsx`` (resolve one icon at a
time) and ``IconPicker.tsx`` (enumerate all of them for the grid).

Kept in a non-component file so React fast refresh keeps working in the
Icon component file (rule: a file exporting a component should export
only components).
*/

import { getAuthHeaders } from "./http-auth";

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

/** An installed host app the daemon can serve a ``source: desktop`` icon for
 * (issue #187). ``id`` is the desktop-file id; ``name`` its display name. */
export type DesktopApp = { id: string; name: string };

/** True when there is no daemon to ask (``?demo=`` fixtures, ``?playground``). */
function isBackendFree(): boolean {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  return params.has("demo") || params.has("playground");
}

/** Where a ``source: desktop`` icon is fetched from. The daemon resolves the
 * desktop id against the host's icon theme and serves the file; with no
 * daemon, a few bundled fixture SVGs stand in so demos can show the source
 * (any other id 404s to the missing-icon placeholder). */
export function desktopIconUrl(name: string): string {
  const id = encodeURIComponent(name);
  if (isBackendFree()) return `${import.meta.env.BASE_URL}demo-app-icons/${id}.svg`;
  return `/desktop-apps/${id}/icon`;
}

/** Installed apps with a resolvable icon, for the icon picker's Apps tab. */
export async function fetchDesktopApps(): Promise<DesktopApp[]> {
  if (isBackendFree()) return DEMO_DESKTOP_APPS;
  const res = await fetch("/desktop-apps", { headers: getAuthHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = (await res.json()) as { apps: DesktopApp[] };
  return body.apps;
}

/** The fixture apps shipped under ``public/demo-app-icons/``. */
export const DEMO_DESKTOP_APPS: DesktopApp[] = [
  { id: "com.gexperts.Tilix", name: "Tilix" },
  { id: "com.slack.Slack", name: "Slack" },
  { id: "com.spotify.Client", name: "Spotify" },
  { id: "org.gimp.GIMP", name: "GIMP" },
  { id: "org.gnome.Console", name: "Console" },
  { id: "org.gnome.Nautilus", name: "Files" },
  { id: "org.gnome.Settings", name: "Settings" },
  { id: "org.keepassxc.KeePassXC", name: "KeePassXC" },
];
