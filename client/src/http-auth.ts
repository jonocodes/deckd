/** The ``X-Deckd-Password`` header for the daemon's authed HTTP routes, read
 * from the password the Settings panel stores. Empty when no password is set
 * (or storage is unavailable), which the daemon accepts when auth is off. */
export function getAuthHeaders(): Record<string, string> {
  try {
    const pw = window.localStorage.getItem("deckd.password") ?? "";
    if (!pw) return {};
    return { "X-Deckd-Password": pw };
  } catch {
    return {};
  }
}
