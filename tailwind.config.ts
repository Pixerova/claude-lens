import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // claude-lens dark theme palette
        surface:  "#1a1a1a",
        elevated: "#242424",
        border:   "#333333",
        muted:    "#666666",
        subtle:   "#999999",
        primary:  "#4B9EFF",
        amber:    "#F59E0B",
        danger:   "#EF4444",
        // Widget shell
        "app-bg": "#0c0c0e",
        // Usage tile backgrounds — session meter
        "tile-sess-norm": "#00695c",
        "tile-sess-warn": "#bf360c",
        "tile-sess-crit": "#b71c1c",
        // Usage tile backgrounds — weekly meter
        "tile-week-norm": "#1565c0",
        "tile-week-warn": "#e65100",
        "tile-week-crit": "#6a1b9a",
        // Action tile backgrounds
        "tile-action":   "#161618",
        "tile-suggest":  "#161612",
      },
      fontFamily: {
        // SF Pro Display is the closest system match to Space Grotesk
        sans: ["-apple-system", "BlinkMacSystemFont", "SF Pro Display", "SF Pro Text", "system-ui", "sans-serif"],
        // ui-monospace resolves to SF Mono on macOS — closest match to JetBrains Mono
        mono: ["ui-monospace", "SF Mono", "monospace"],
      },
      keyframes: {
        flash: {
          "0%, 100%": { opacity: "1" },
          "50%":       { opacity: "0.6" },
        },
      },
      animation: {
        flash: "flash 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
