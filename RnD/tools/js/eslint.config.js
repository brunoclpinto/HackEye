// Flat config for the Lab front end (lab/static/**/*.js) and the node tests (tests/js/**/*.mjs).
// CommonJS on purpose: the packages live in the image at /opt/js/node_modules (not under /rnd), and require() honours NODE_PATH
// where ESM imports do not. Run through tools/check_inner.sh: eslint --config tools/js/eslint.config.js <files>.
const js = require("@eslint/js");
const globals = require("globals");
const importPlugin = require("eslint-plugin-import");

module.exports = [
  js.configs.recommended,
  {
    files: ["lab/static/**/*.js"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: { ...globals.browser } },
    plugins: { import: importPlugin },
    rules: {
      "import/no-cycle": "error",
      "no-unused-vars": "error",
    },
  },
  {
    files: ["tests/js/**/*.mjs"],
    languageOptions: { ecmaVersion: "latest", sourceType: "module", globals: { ...globals.node } },
    plugins: { import: importPlugin },
    rules: {
      "import/no-cycle": "error",
      "no-unused-vars": "error",
    },
  },
];
