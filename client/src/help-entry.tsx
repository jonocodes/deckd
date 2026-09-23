import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ReflowHelp } from "./ReflowHelp";
import "./fonts";
import "./help.css";

/** Standalone mount of the layout help page (`help.html`).
 *
 * No socket, no daemon, no app state: it is a public, linkable page. The size
 * controls are a sandbox here rather than a device preference, so no
 * ``onApply``/``onClose`` is passed. */
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div className="help-page">
      <ReflowHelp />
    </div>
  </StrictMode>,
);
