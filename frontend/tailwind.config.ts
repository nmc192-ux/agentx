import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  darkMode: "class",
  theme: {
    extend: {
      // ── Design Tokens (DARIA Design System v1) ────────────────────────────
      colors: {
        background: {
          primary:   "#0A0A0A",
          secondary: "#141414",
          tertiary:  "#1A1A1A",
          quaternary:"#242424",
        },
        surface: {
          primary:   "#1C1C1C",
          secondary: "#262626",
          tertiary:  "#303030",
          quaternary:"#3A3A3A",
        },
        border: {
          primary:   "#2A2A2A",
          secondary: "#3A3A3A",
          tertiary:  "#4A4A4A",
          focus:     "#5A5A5A",
        },
        text: {
          primary:   "#F5F5F5",
          secondary: "#B8B8B8",
          tertiary:  "#8A8A8A",
          quaternary:"#6A6A6A",
          inverse:   "#0A0A0A",
        },
        trust: {
          unverified: "#6B7280",
          verified:   "#3B82F6",
          trusted:    "#8B5CF6",
          elite:      "#F59E0B",
        },
        post: {
          REQUEST:    "#EF4444",
          OFFER:      "#22C55E",
          TASK:       "#3B82F6",
          PREDICTION: "#A855F7",
          UPDATE:     "#F59E0B",
          PROPOSAL:   "#F97316",
        },
        accent: {
          primary:    "#6366F1",
          secondary:  "#8B5CF6",
          success:    "#22C55E",
          warning:    "#F59E0B",
          error:      "#EF4444",
          info:       "#3B82F6",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.625rem", { lineHeight: "0.875rem" }],
      },
      borderRadius: {
        "4xl": "2rem",
      },
      animation: {
        "pulse-slow":    "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "spin-slow":     "spin 3s linear infinite",
        "fade-in":       "fadeIn 0.3s ease-out",
        "slide-up":      "slideUp 0.3s ease-out",
        "glow-trust":    "glowTrust 2s ease-in-out infinite alternate",
      },
      keyframes: {
        fadeIn:    { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp:   { "0%": { transform: "translateY(8px)", opacity: "0" }, "100%": { transform: "translateY(0)", opacity: "1" } },
        glowTrust: { "0%": { boxShadow: "0 0 4px currentColor" }, "100%": { boxShadow: "0 0 16px currentColor" } },
      },
      boxShadow: {
        "card":      "0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.6)",
        "card-hover":"0 4px 12px rgba(0,0,0,0.5)",
        "glow-blue": "0 0 20px rgba(59,130,246,0.3)",
        "glow-violet":"0 0 20px rgba(139,92,246,0.3)",
        "glow-amber":"0 0 20px rgba(245,158,11,0.4)",
      },
    },
  },
  plugins: [],
};

export default config;
