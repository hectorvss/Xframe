import eslint from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: ["dist/**", "node_modules/**", "supabase/functions/**"],
  },
  {
    files: ["src/**/*.{js,jsx}"],
    linterOptions: {
      reportUnusedDisableDirectives: false,
    },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...eslint.configs.recommended.rules,
      "no-unused-vars": "off",
      "no-empty": "off",
      "no-useless-escape": "off",
      "react-hooks/rules-of-hooks": "error",
    },
  },
];
