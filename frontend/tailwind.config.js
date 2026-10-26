/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: v("canvas"),
        surface: { DEFAULT: v("surface"), 2: v("surface-2") },
        line: v("line"),
        ink: { DEFAULT: v("ink"), soft: v("ink-soft"), muted: v("ink-muted") },
        lens: { DEFAULT: v("lens"), soft: v("lens-soft"), deep: v("lens-deep") },
        caution: { DEFAULT: v("caution"), soft: v("caution-soft") },
        danger: { DEFAULT: v("danger"), soft: v("danger-soft") },
        ai: { DEFAULT: v("ai"), soft: v("ai-soft") },
        sidebar: v("sidebar"),
        "on-accent": v("on-accent"),
        code: { DEFAULT: v("code"), fg: v("code-fg") },
        "t-date": { DEFAULT: v("t-date"), fg: v("t-date-fg") },
        "t-cat": { DEFAULT: v("t-cat"), fg: v("t-cat-fg") },
        "t-bool": { DEFAULT: v("t-bool"), fg: v("t-bool-fg") },
      },
      fontFamily: {
        sans: ['"Instrument Sans"', "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: { panel: "var(--shadow-panel)" },
    },
  },
  plugins: [],
};
