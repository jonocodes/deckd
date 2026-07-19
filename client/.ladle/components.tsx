import type { GlobalProvider } from "@ladle/react";
import "../src/style.css";

/** Wrap every story in the app's dark surface so components render against
 * the same background and inherit the same base typography as production. */
export const Provider: GlobalProvider = ({ children }) => (
  <div style={{ minHeight: "100vh", padding: 20, background: "#0e1115", color: "#e6e9ef" }}>
    {children}
  </div>
);
