/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Inter leads; the named script faces are fallbacks so ta/hi/te
        // glyphs render even where Inter has no coverage.
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Noto Sans Tamil",
          "Noto Sans Devanagari",
          "Noto Sans Telugu",
          "sans-serif",
        ],
      },
      fontSize: {
        xs: ["14px", { lineHeight: "18.75px" }],
        sm: ["16px", { lineHeight: "21.7px" }],
        base: ["19px", { lineHeight: "26.4px" }],
        lg: ["38px", { lineHeight: "42.24px" }],
      },
      fontWeight: {
        normal: "400",
        medium: "500",
      },
      colors: {
        cozy: {
          white: "#FFFFFF",
          canvas: "#121212",
          card: "#1E1E1E",
          input: "#262626",
          elevated: "#2A2A2A",
          secondary: "#3A3A3A",
          muted: "#8E8E8E",
          quiet: "#A3A3A3",
          subtle: "#525252",
          border: "rgba(255, 255, 255, 0.12)",
          borderStrong: "rgba(255, 255, 255, 0.22)",
          borderFocus: "#FFFFFF",
        },
      },
      spacing: {
        1: "6px",
        2: "8px",
        3: "12px",
        4: "13px",
        5: "16px",
        6: "18px",
        7: "20px",
        8: "24px",
        9: "28px",
        10: "32px",
        11: "36px",
        12: "40px",
        13: "48px",
        14: "64px",
      },
      borderRadius: {
        sm: "4px",
        md: "11px",
        lg: "24px",
        full: "9999px",
      },
      boxShadow: {
        sm: "rgba(255, 255, 255, 0.9) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px, rgba(0, 0, 0, 0.5) 0px 6px 14px -6px",
        md: "rgba(255, 255, 255, 0.06) 0px 1px 0px 0px inset, rgba(0, 0, 0, 0.3) 0px 1px 2px 0px",
        lg: "oklch(0.215 0.018 53 / 0.05) 0px 1px 3px -1px, oklch(0.215 0.018 53 / 0.16) 0px 12px 28px -18px",
      },
      transitionTimingFunction: {
        cozy: "cubic-bezier(0.23, 1, 0.32, 1)",
      },
      transitionDuration: {
        fast: "150ms",
        base: "200ms",
      },
    },
  },
  plugins: [],
};
