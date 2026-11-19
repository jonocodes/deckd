import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { demoLanding } from "./demo-landing";
import "./fonts";
import "./style.css";
import "./help.css";

const landing = demoLanding(window.location.search, import.meta.env.VITE_DEMO_PAGE);
if (landing) {
  window.location.replace(landing);
} else {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
