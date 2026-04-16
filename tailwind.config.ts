import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Claude Lens dark theme palette
        surface:  "#1a1a1a",
        elevated: "#242424",
        border:   "#333333",
        muted:    "#666666",
        subtle:   "#999999",
        primary:  "#4B9EFF",
        amber:    "#F59E0B",
        danger:   "#EF4444",
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "SF Pro Text", "system-ui", "sans-serif"],
        mono: ["SF Mono", "JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
