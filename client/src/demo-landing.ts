/** On GitHub Pages there's no daemon, so the client with nothing to show
 * (no ``?demo=`` / ``?playground`` / ``?deck=``) just says "Reconnecting…".
 * The Pages build sets ``VITE_DEMO_PAGE`` (scripts/build_pages.sh) and such a
 * visit forwards there instead. The client is also the site's 404.html, so a
 * mistyped site link lands on the demo too. Unset everywhere else, so a
 * daemon-served client never redirects. */
export function demoLanding(search: string, target: string | undefined): string | null {
  if (!target) return null;
  const params = new URLSearchParams(search);
  return params.has("demo") || params.has("playground") || params.has("deck") ? null : target;
}
