# Theme: NuruOps, with AgroShield teal

**Status (2026-10-29): NuruOps material found on this PC and used.** All colour, type, spacing, radius, shadow and
motion values live in one file: `src/agroshield_platform/web/static/tokens.css`. Components and templates read
those variables only.

## NuruOps sources used

| What | File on this PC | Used for |
|---|---|---|
| Site styles ("Midnight Gold") | `Desktop/Lock In/NuruOps/styles.css` | dark surfaces (`#0F1117`, `#1A1D26`, `#20232E`, border `#2A2D36`), gold `#E8960C` / `#C77A00` / `#FEF3C7`, type roles (display serif, body sans), easing `cubic-bezier(.22,1,.36,1)` |
| App globals | `Desktop/Lock In/NuruOps/nuruops-app/app/globals.css` | light theme ("paper") surfaces `#F6F3EC`, `#F1EDE3`, border `#E5DFD1`, text `#1B1710` / `#403A2F` / `#6A6357`, light gold `#B8760A` / `#8A5600`; `html[data-theme]` toggle pattern |
| Typeface | `nuruops-app/app/layout.jsx` (EB Garamond via next/font), files from `nuruops-app/.next/static/media/` | display and heading face, self-hosted as `static/fonts/eb-garamond-latin*.woff2` under the SIL OFL 1.1 (`static/fonts/OFL.txt`) |
| Logo style | `Desktop/Lock In/NuruOps/brand/nuruops-logo-horizontal.svg`, `nuruops-emblem.svg` | the faceted polygon emblem with a thin dark stroke, set beside a Garamond wordmark; redrawn as a faceted teal shield for AgroShield |

## Decisions

- **Teal stays the signature accent** (the "Teal Sovereignty" tokens in `../agroshield-kenya/public/css/agroshield.css`:
  `#00695C`, `#004D40`, dark-mode `#00E5CC` family). Links, primary buttons, focus rings and the logo shield are teal.
- **Gold is the secondary highlight**, from NuruOps: small badges, one facet in the mark, chart series 2. Gold text uses
  `#8A5600` (light) or `#F5B547` (dark) so it passes WCAG AA; the bright `#E8960C` is decorative only.
- **Surfaces follow NuruOps:** warm paper in light mode, midnight in dark mode, so AgroShield and NuruOps read as one family.
- **Body text is the system UI font, not Garamond.** NuruOps sets everything in Garamond; for an insurance workspace with
  dense numeric tables a sans with tabular figures is clearer, and it costs nothing to download on slow SACCO connections.
  EB Garamond is kept for headings and the wordmark.
- **No web-font CDN.** Fonts are self-hosted, so no visitor's browser contacts a third party.
- **Light by default, dark follows the system, and a toggle** (stored per browser) overrides both.

## Swapping the theme

Edit `tokens.css` only. To try pure NuruOps gold as the accent, set `--accent` to `#B8760A` (light) / `#E8960C` (dark)
and `--accent-ink` to white / `#0F1117`.

## Added during the overnight QA and review

- `--overlay-strong`: the darker teal-black wash over hero photos. On screens under 900 px the whole photo gets it, so
  white text never sits on a bright part of an image; on wide screens it covers the text side of the gradient.
- `--input-border`: form control edges, at least 3:1 against the card and input surfaces in both themes
  (WCAG 1.4.11 non-text contrast). `--border-strong` stays for decorative lines.
- Charts in the underwriter workspace are inline SVG using `--chart-1` to `--chart-3`, drawn at their natural size
  (never stretched), each with a visually hidden data table for screen readers.
