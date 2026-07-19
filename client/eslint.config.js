import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The codebase intentionally syncs a ref to the latest prop during
      // render (JogStrip/Trackpad) so pointer callbacks read fresh values
      // without stale-closure risk. This experimental rule flags that idiom;
      // keep the load-bearing hooks rules (rules-of-hooks, exhaustive-deps)
      // but disable this one rather than rewrite working input logic.
      "react-hooks/refs": "off",
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
    },
  },
  // Config / tooling files run in Node, not the browser.
  {
    files: ["*.config.{js,ts}"],
    languageOptions: { globals: globals.node },
  },
);
