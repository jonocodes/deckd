/** Confirmation prompt for ``confirm: true`` widgets (issues #69 / #107 /
 * #109 — Variant A: centered card modal).
 *
 * Daemon-authoritative handshake: on a ``confirm: true`` press the daemon
 * withholds execution, mints a ``confirm_id``, and sends a
 * ``ServerConfirmRequest``. This component renders the prompt the user
 * sees, then sends back a ``ClientConfirmResponse`` carrying the
 * daemon-minted ``confirm_id`` and the user's verdict (``"confirm"`` /
 * ``"cancel"``). The daemon's ~30 s backstop timer mirrors the
 * ``CONFIRM_TIMEOUT_S`` constant the daemon hardcodes — the modal
 * auto-dismisses in lockstep so a visible prompt is always a live one
 * (#109 design decision).
 *
 * Keyboard contract (Variant A): ``Enter`` confirms, ``Escape`` cancels,
 * matching every system permission dialog. Both buttons are wired
 * explicitly so a screen-reader user has the same two-step gesture.
 */
import { useCallback, useEffect, useRef } from "react";
import { Icon } from "./Icon";
import type { Widget } from "./protocol";

/** Auto-dismiss window. Matches ``deckd.server.CONFIRM_TIMEOUT_S``; a
 *  visible prompt is always a live one. When this fires locally we
 *  send ``"cancel"`` so the daemon's pending token is dropped
 *  immediately rather than waiting out its own backstop. */
const CONFIRM_TIMEOUT_MS = 30_000;

export interface ConfirmModalProps {
  /** The daemon-minted token to echo back in the ``confirm_response``
   *  frame. The modal does NOT run anything on its own — the daemon
   *  is the source of truth for what gets executed. */
  confirmId: string;
  /** The widget that was pressed. Used to look up its label / icon so
   *  the prompt names the action without the daemon having to send
   *  command text over the wire (issue #107 wire shape). */
  widget: Widget;
  /** Send ``"confirm"`` back to the daemon (executes the action). */
  onConfirm: (confirmId: string) => void;
  /** Send ``"cancel"`` back to the daemon (drops the pending action). */
  onCancel: (confirmId: string) => void;
}

export function ConfirmModal({
  confirmId,
  widget,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  // Stable refs to the props so the timeout callback below doesn't
  // capture a stale closure when ``widget`` changes (the parent may
  // re-render with a fresh widget on supersession).
  const onConfirmRef = useRef(onConfirm);
  const onCancelRef = useRef(onCancel);
  onConfirmRef.current = onConfirm;
  onCancelRef.current = onCancel;

  // Arm the auto-dismiss timeout exactly once per ``confirmId``. A
  // new confirm_id (a re-press on the same widget, or any second
  // dangerous press) replaces this modal entirely, so the timer for
  // the old id is wiped on unmount / id change.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      onCancelRef.current(confirmId);
    }, CONFIRM_TIMEOUT_MS);
    return () => window.clearTimeout(handle);
  }, [confirmId]);

  // Focus the primary action on mount so a keyboard user can
  // ``Enter`` straight through; the modal is a dialog and the
  // default focus landing on the safe button (``Cancel``) would
  // make ``Enter`` mean "abort" — surprising for a confirmation
  // prompt. We deliberately focus Confirm.
  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  const handleKey = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel(confirmId);
      }
      // Enter is handled by the focused button's native onClick; no
      // global handler needed.
    },
    [confirmId, onCancel],
  );

  // The widget's display name (label → id fallback) — the daemon
  // doesn't send command text on the wire, so the prompt body is
  // generated entirely from the widget record the client already
  // holds from the last ``ServerLayout``.
  const displayName = widget.label ?? widget.id;

  return (
    <div
      className="confirm-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`confirm-modal-title-${confirmId}`}
      aria-describedby={`confirm-modal-body-${confirmId}`}
      onKeyDown={handleKey}
    >
      <div className="confirm-modal-card">
        <div className="confirm-modal-badge" aria-hidden="true">
          <Icon icon={{ source: "lucide", name: "alert-triangle" }} className="confirm-modal-badge-icon" />
        </div>
        <h2 className="confirm-modal-title" id={`confirm-modal-title-${confirmId}`}>
          Confirm action?
        </h2>
        <p className="confirm-modal-body" id={`confirm-modal-body-${confirmId}`}>
          Run <strong>{displayName}</strong>?
        </p>
        <div className="confirm-modal-buttons">
          <button
            type="button"
            className="confirm-modal-button confirm-modal-cancel"
            onClick={() => onCancel(confirmId)}
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            className="confirm-modal-button confirm-modal-confirm"
            onClick={() => onConfirm(confirmId)}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
