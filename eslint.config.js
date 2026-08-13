import globals from "globals";

const bugCatcherRules = {
  "no-dupe-keys": "error",
  "no-dupe-args": "error",
  "no-unreachable": "error",
  "no-cond-assign": ["error", "except-parens"],
  "getter-return": "error",
  "no-func-assign": "error",
  "no-dupe-else-if": "error",
  "no-self-assign": "error",
  "use-isnan": "error",
  "valid-typeof": "error",
  "no-empty": "off",
  "no-undef": "error",
  "no-redeclare": "error",
  "no-unused-vars": [
    "error",
    {
      argsIgnorePattern: "^_",
      caughtErrorsIgnorePattern: "^_",
      destructuredArrayIgnorePattern: "^_",
      varsIgnorePattern: "^_",
    },
  ],
};

export default [
  {
    files: ["static/*.js"],
    ignores: ["static/sw.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: {
        ...globals.browser,
        module: "readonly",
      },
    },
    rules: bugCatcherRules,
  },
  {
    files: ["static/sw.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "script",
      globals: globals.serviceworker,
    },
    rules: bugCatcherRules,
  },
  {
    files: ["tests-js/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.node,
    },
    rules: bugCatcherRules,
  },
];
