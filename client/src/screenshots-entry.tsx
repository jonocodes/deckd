import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Screenshots } from "./Screenshots";
import "./fonts";
import "./screenshots.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Screenshots />
  </StrictMode>,
);
