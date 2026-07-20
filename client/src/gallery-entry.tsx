import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Gallery } from "./Gallery";
import "./fonts";
import "./gallery.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
