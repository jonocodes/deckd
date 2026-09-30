/** Non-blocking toast for a failed media command (issue #64).
 *
 * The daemon sends a ``media_error`` frame naming the player and whether a
 * retry is worth attempting; this renders it above the bottom chrome with
 * Retry / Dismiss. It never blocks the grid — a rejected volume tap should
 * not cost you the rest of the deck. ``aria-live="polite"`` announces it.
 */
export function MediaErrorToast({
  player,
  message,
  retryable,
  onRetry,
  onDismiss,
}: {
  player: string;
  message: string;
  retryable: boolean;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="media-error-toast" aria-live="polite">
      <span className="media-error-text">
        <span className="media-error-player">{player}</span>
        {" — "}
        {message}
      </span>
      <span className="media-error-actions">
        {retryable ? (
          <button className="media-error-btn" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        <button className="media-error-btn" onClick={onDismiss}>
          Dismiss
        </button>
      </span>
    </div>
  );
}
