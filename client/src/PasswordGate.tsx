import { useState } from "react";
import type { FormEvent } from "react";

/** Landing screen shown when the daemon rejects the connection as
 * ``unauthorized`` (issue #16). A single password field — no QR, no token,
 * no URL query param. Submitting hands the value back to the socket, which
 * stores it and reconnects. ``retry`` is true once a stored password has
 * already been rejected, so the copy can say so. */
export function PasswordGate({
  onSubmit,
  retry,
}: {
  onSubmit: (password: string) => void;
  retry: boolean;
}) {
  const [value, setValue] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const password = value.trim();
    if (password) onSubmit(password);
  };

  return (
    <div className="password-gate">
      <form className="password-gate-form" onSubmit={submit}>
        <h1 className="password-gate-title">deckd</h1>
        <p className="password-gate-hint">
          {retry
            ? "Incorrect password. Try again."
            : "Enter the password to connect."}
        </p>
        <input
          className="password-gate-input"
          type="password"
          autoFocus
          autoComplete="current-password"
          placeholder="Password"
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
        />
        <button className="password-gate-submit" type="submit" disabled={!value.trim()}>
          Connect
        </button>
      </form>
    </div>
  );
}
