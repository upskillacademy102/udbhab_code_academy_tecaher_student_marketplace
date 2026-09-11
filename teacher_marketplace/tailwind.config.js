/** Tailwind config — built by the standalone CLI (tools/tailwindcss.exe). No Node required. */

/*
 * TWO PALETTES LIVE HERE ON PURPOSE (rebuild, stage A).
 *
 *   pine / marigold / ink / paper  — the new design language. Used by the
 *       rebuilt public pages (landing, login, register, errors) and, from
 *       stage B, by the student + teacher SPA.
 *
 *   brand (indigo)                 — the ORIGINAL palette, left untouched so
 *       the admin / super-admin portal (explicitly out of scope for this
 *       rebuild) keeps rendering exactly as it did. When we decide to bring
 *       it across, `brand` becomes an alias of `pine` and the whole portal
 *       moves in one line — no template edits.
 *
 * Colour rationale (see the approved plan):
 *   pine      deep teal — carries blue's trust association without edtech's
 *             default hue. The ground, not the accent.
 *   marigold  the ONLY accent. Reserved for one primary action per screen.
 *             Its scarcity is the mechanism (Von Restorff); spending it on
 *             badges/icons/nav would switch the effect off, which is exactly
 *             what the old indigo did.
 *   ink       warm green-black neutrals, biased toward the ground so text
 *             sits *in* the palette rather than on top of it.
 *
 * Contrast: every text pair below was measured against WCAG 2.1 relative
 * luminance before shipping. ink-400 is 3.62:1 on white — NON-TEXT ONLY
 * (icons, hairlines, disabled glyphs). Never use it for body copy.
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // The page ground. Measured deliberately, not picked by eye: a white
        // card on the previous #f7f5f1 separated from it by 1.09:1 - invisible,
        // so nothing on the page looked tappable. Two light tones can only
        // separate so far (the darkest ground that still holds AA body text
        // reaches 1.26:1), which is why the edge does the real work - see the
        // interactive-surface layer in static/src/app.css.
        //
        // #e7ede9 keeps ink-500 at 4.73:1 (AA) while reading as a deliberate
        // tint rather than almost-white.
        canvas: "#e7ede9",

        // ---- NEW: the rebuild palette -------------------------------
        paper: {
          DEFAULT: "#ffffff",
          canvas: "#e7ede9", // tinted page ground; actions sit on white above it
          sunk: "#dde6e1", // recessed wells, table headers
        },
        pine: {
          50: "#eef6f4",
          100: "#d6eae6",
          200: "#afd5ce",
          300: "#7fbab0",
          400: "#4e9c90",
          500: "#2a8175",
          600: "#176b61", // interactive: links, focus, secondary actions
          700: "#12574f", // brand ground
          800: "#0e4a43",
          900: "#0b3b36",
          950: "#062622",
        },
        marigold: {
          50: "#fef7ec",
          100: "#fdebd2",
          200: "#fbd9a8",
          300: "#f8c374",
          400: "#f5b65c",
          500: "#f2a93b", // THE accent — one primary action per screen
          600: "#de8f1e",
          700: "#b87215",
          800: "#8a5a12", // warning text on light grounds (5.07:1 on marigold-100)
          900: "#6b460f",
        },
        ink: {
          50: "#f1f3f1",
          100: "#e3e7e4", // hairlines
          200: "#cbd3cf",
          300: "#a8b5b0",
          400: "#7a8a84", // NON-TEXT ONLY — 3.62:1 on white
          500: "#5b6b66", // muted text — 5.62:1 on white
          600: "#44534e",
          700: "#2c3b37", // body — 10.79:1 on canvas
          800: "#1b2a26",
          900: "#12211e", // headings — 15.28:1 on canvas
        },
        // Semantic, drawn from the same warm family so alerts belong to the
        // page instead of arriving from a different design system.
        success: "#1f7a5c",
        danger: "#b4413c",
        warning: "#b87215",

        // ---- `slate` is now an ALIAS of ink -------------------------
        // The admin portal's 531 slate-* references are cool grey, which
        // clashed with the new warm ground - but more importantly it broke
        // contrast: slate-500 (the most-used shade, 121 uses) measures
        // 4.01:1 on #e7ede9 and FAILS AA. The warm ink-500 is 4.73:1 and
        // passes. Every other shade improves too. Aliasing fixes the
        // regression and the clash together, with no template edits.
        slate: {
          50: "#f1f3f1",
          100: "#e3e7e4",
          200: "#cbd3cf",
          300: "#a8b5b0",
          400: "#7a8a84",
          500: "#5b6b66",
          600: "#44534e",
          700: "#2c3b37",
          800: "#1b2a26",
          900: "#12211e",
          950: "#0a1210",
        },

        // ---- `brand` is now an ALIAS of pine ------------------------
        // The admin / super-admin portal was deliberately left on the old
        // indigo while the public pages were rebuilt, so it could not shift
        // under review. It now inherits the new palette.
        //
        // Aliasing rather than editing templates resolves all 44 brand-*
        // references plus the original component layer in one move, with no
        // template edits and a one-line path back to indigo if ever needed.
        brand: {
          50: "#eef6f4",
          100: "#d6eae6",
          200: "#afd5ce",
          300: "#7fbab0",
          400: "#4e9c90",
          500: "#2a8175",
          600: "#176b61",
          700: "#12574f",
          800: "#0e4a43",
          900: "#0b3b36",
          950: "#062622",
        },
      },
      fontFamily: {
        // Literata is a *reading* face (commissioned for Google Play Books).
        // Display only — never below 28px, where serifs at label size are
        // where this pairing usually fails.
        display: [
          "Literata",
          "ui-serif",
          "Georgia",
          "Cambria",
          "Times New Roman",
          "serif",
        ],
        sans: [
          "InterVariable",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "Noto Sans",
          "sans-serif",
        ],
      },
      borderRadius: {
        lg: "0.625rem",
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(15 23 42 / 0.04)",
        sm: "0 1px 3px 0 rgb(15 23 42 / 0.06), 0 1px 2px -1px rgb(15 23 42 / 0.06)",
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 8px 24px -12px rgb(15 23 42 / 0.10)",
        pop: "0 12px 32px -8px rgb(15 23 42 / 0.18)",
        // New: shadows tinted with ink, not slate, so elevation belongs to
        // the warm palette instead of casting a faint blue.
        soft: "0 1px 2px 0 rgb(18 33 29 / 0.05)",
        lift: "0 1px 2px 0 rgb(18 33 29 / 0.04), 0 10px 28px -14px rgb(18 33 29 / 0.16)",
        raise: "0 18px 40px -18px rgb(18 33 29 / 0.28)",
      },
      maxWidth: {
        content: "80rem",
        shell: "75rem", // marketing / reading width — narrower than the app
        prose: "38rem",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        // Result/step entry. Paired with a per-item --d delay in the
        // template so a list reads as arriving rather than popping.
        "rise-in": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        // Confirms a value landed (count-up finishing, unlock succeeding).
        "pulse-once": {
          "0%": { transform: "scale(1)" },
          "40%": { transform: "scale(1.04)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.18s ease-out",
        "slide-up": "slide-up 0.2s ease-out",
        "rise-in": "rise-in 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) both",
        "pulse-once": "pulse-once 0.36s ease-out",
      },
      transitionTimingFunction: {
        // Decelerate on enter, accelerate on exit — the two curves the whole
        // motion plan uses. Anything else is decoration.
        enter: "cubic-bezier(0.2, 0.8, 0.2, 1)",
        exit: "cubic-bezier(0.4, 0, 0.6, 1)",
      },
    },
  },
  plugins: [],
};
