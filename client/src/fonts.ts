/** Bundle Inter (self-hosted woff2) for a consistent typeface across devices
 * rather than falling back to each OS's default UI font. Only the weights the
 * UI actually uses (400 body, 600 labels/buttons, 700 headings) are imported,
 * to keep the payload small. Imported by every entry point (app, gallery,
 * Ladle) so the font is present wherever components render. */
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
