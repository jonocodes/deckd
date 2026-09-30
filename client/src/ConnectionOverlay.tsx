/** Full-surface reconnect / disconnected overlay (issue #64).
 *
 * The socket hook owns the facts — whether the retry loop is active, the
 * attempt count, and the last error — and this component turns them into
 * copy plus a single Cancel/Retry affordance. It renders *over* whatever
 * the surface was last showing, so a stale grid stays readable behind it.
 *
 * Deliberately ``aria-live="polite"`` without ``role="status"``: the app
 * already keeps one ``role="status"`` live region for announcements, and a
 * second implicit status role would make ``getByRole("status")`` ambiguous
 * for both users and tests. The spinner stops under the app's
 * ``a11y-reduce-motion`` class and the OS ``prefers-reduced-motion`` query.
 */
export function ConnectionOverlay({
  reconnecting,
  attempt,
  lastError,
  onCancel,
  onRetry,
}: {
  /** The auto-retry loop is active (dialing or waiting out the backoff).
   *  False means the loop is paused/stopped, so offer Retry. */
  reconnecting: boolean;
  attempt: number;
  lastError: string;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const detail = lastError || "contacting the daemon…";
  return (
    <div className="conn-overlay" aria-live="polite">
      <div className="conn-overlay-card">
        {reconnecting ? <span className="conn-overlay-spinner" aria-hidden /> : null}
        <span className="conn-overlay-title">
          {reconnecting ? "Reconnecting…" : "Disconnected"}
        </span>
        <span className="conn-overlay-sub">
          {reconnecting ? `Attempt ${attempt} — ${detail}` : detail}
        </span>
        {reconnecting ? (
          <button
            className="conn-overlay-btn"
            aria-label="Cancel reconnecting"
            onClick={onCancel}
          >
            Cancel
          </button>
        ) : (
          <button
            className="conn-overlay-btn"
            aria-label="Retry connection"
            onClick={onRetry}
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
