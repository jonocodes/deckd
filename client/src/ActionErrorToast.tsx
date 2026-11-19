/** Non-blocking toast for an action the OS refused (issue #196).
 *
 * The daemon answers a key press macOS blocked for want of a permission
 * with an ``action_error`` frame; this shows its message straight away.
 * The health banner, raised at the same time, carries the fix steps, so the
 * toast only says what happened. No Retry: the OS would refuse it the same
 * way until the grant lands. Shares the media toast's look and placement.
 */
export function ActionErrorToast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="media-error-toast" aria-live="polite">
      <span className="media-error-text">{message}</span>
      <span className="media-error-actions">
        <button className="media-error-btn" onClick={onDismiss}>
          Dismiss
        </button>
      </span>
    </div>
  );
}
