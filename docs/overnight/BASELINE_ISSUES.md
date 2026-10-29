# Baseline issues (Phase A, 29 October 2026, before any overnight change)

Crawl: `tools/qa/crawl.py before`. 34 pages (public, SACCO officer, SACCO manager, underwriter) at 1440, 1024, 768 and
375 px, light and dark = 272 page views. Screenshots in `docs/overnight/before/` (local only, see note), raw data in
`before.json`, generated summary in `before-summary.md`.

Pricing reference hashes saved first: `docs/overnight/pricing_reference.json` (ward-a `76436465...`, ward-b `a9ad3062...`;
two consecutive runs gave identical hashes, so the check is meaningful). Tests: **221 passed**.

## What is already fine

- Every page returns 200 for its role; no internal link fails; no 404 from the navbar.
- No console errors, no failed requests, no broken images, no images without alt text.
- No horizontal page scroll at any width.
- No axe-core colour-contrast violations in light or dark.

## Issues, by severity

| # | Severity | Issue | Where | Planned fix |
|---|---|---|---|---|
| 1 | High | **Navbar wraps onto 2 to 3 rows.** Manager header is 75 px tall at 1440 and 1024 (6 to 8 links plus Developer); underwriter wraps at 1024 to 1440 ("Reinsurer summary" drops to a second row); at 768 every signed-in navbar wraps before the Menu button appears (it only appears below 760 px). | all signed-in pages | Phase B navbar: per-role collapse breakpoint plus a measuring fallback, account menu, Developer menu folded in |
| 2 | High | **No public site structure.** Only `/` (a farmer leaflet) and `/login` exist; the brief's navbar (Crops, Livestock, How it works, For insurers, For SACCOs, Learn) has no pages behind it. The landing reads as a SACCO and farmer product, not an underwriter product. | public | Phase C |
| 3 | Serious (axe) | `scrollable-region-focusable`: scrollable `.table-wrap` boxes cannot be reached by keyboard. | reports, every `/uw` page, member page | `tabindex="0"`, `role="region"` and a label on scrollable table boxes |
| 4 | Moderate (axe) | `region`: content outside landmarks (development banner and some page parts). | 33 of 34 pages | banner inside a landmark; single `main`; skip link |
| 5 | Moderate (axe) | `page-has-heading-one`: no `h1` on officer and manager Home. | `/dashboard` | add a visually clear page title |
| 6 | Moderate | **Tap targets under 44 px at 375 px**: Menu button 31 px; `.btn.small` buttons 31 px (Find, Send M-Pesa request, Record deduction, Record report, Save, Upload, Send queued messages); Details toggles 37 px; landing FAQ toggles 25 px; date inputs 21 px. | most app pages | `--tap` minimum on every control in the design system (not only on coarse pointers) |
| 7 | Minor (axe) | `empty-table-header`: action columns have an empty `<th>`. | dev M-Pesa, payouts, bordereaux, triggers | visually hidden header text ("Actions") |
| 8 | Minor | Navbar is not to spec: no skip link, no account menu (name, organisation and Sign out sit loose in the bar), no theme toggle, no scrolled shadow, Developer menu does not close on Esc, mobile menu is a small dropdown, not a full-width sheet with focus trap. | all | Phase B |
| 9 | Minor | **Design not systematised**: colours and sizes are hard-coded in `portal.css` and inline `style=` attributes in about 40 places in templates; the pricing report and the research pages use their own palettes. | all | Phase B: one tokens file, component classes, inline styles removed |
| 10 | Minor | Nav item lists differ from the brief: officers and managers have "Payouts"; managers lack nothing else; underwriters have no Weather page and "Pricing and audit" is labelled differently. | signed-in nav | follow brief section 3 (Payouts stays reachable from Home and Reports); add a read-only underwriter Weather page |
| 11 | Info | The crawler's first navbar-row metric counted small vertical offsets as rows (officer "2 rows" at 1440 is a false positive; the header is 57 px, a single line). Fixed in the crawler for later runs. | tooling | done |

## Note on screenshots

The 224 baseline screenshots (29 MB of JPEG) are kept in `docs/overnight/before/` on this PC and are not committed, to
keep the repository small. `docs/overnight/index.html` (Phase H) shows them side by side with the after set.
