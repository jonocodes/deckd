import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { startUpdateCheck } from "./update-check";
import "./fonts";
import "./style.css";

// Watch the daemon's client fingerprint and hard-reload when the served
// bundle changes, so an installed PWA can't drive a stale UI indefinitely.
startUpdateCheck();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
