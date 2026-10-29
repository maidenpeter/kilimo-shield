# Ideas borrowed from the old MVP demo

`../agroshield-kenya` is an earlier Node/Express demo. It is **read-only reference**:
nothing is merged or copied wholesale, and none of its pricing is used. This file
records each idea we take, where it came from, how it changes to fit AgroShield's
rules, and the milestone it is built in.

Status (2026-10-29): items 5 and 7 are **built** (milestone 4); items 2, 3, 8 and the static part of 4 are
**built** (milestone 5); item 1 is **built** (milestone 6). The rest wait for their milestones.

Line numbers refer to the demo as of 2026-10-28.

## Borrowed

| # | Idea | Source in the demo | How it changes here | Milestone |
|---|---|---|---|---|
| 1 | Bilingual (English / Kiswahili) onboarding and FAQ wording | `public/js/chatbot.js:31-53` (`STR` table: greeting, menu, askName ... confirmed) and the FAQ intents in the same file | Reused only as wording for USSD menus and SMS templates, stored in locale files (`locales/en.*`, `locales/sw.*`), never in code. No chatbot. Every Swahili string gets native-speaker review first: some are wrong (e.g. `askIrrigation` "Unalima kwa umeme au mvua?" asks about *electricity*; `askSubCounty` drops the ward). Prompts change from county to SACCO member number and ward. | **Built in 6**: `locales/en.yaml`, `locales/sw.yaml` (greeting, the "M-Pesa or SACCO" payment line, the SMS confirmation pattern); Kiswahili pending review |
| 2 | Education landing page structure and plain-language copy | `public/index.html:80-340` (`#tab-home`: hero, "What is agricultural insurance?", "Why Kenya needs it now", "How parametric cover works", benefits, scenarios, partners, FAQ at 306-326) | Becomes the farmer and SACCO landing page. Removed: every claim about county ESG pricing, the "Claims" flow, "~90 sec" payouts and unverified statistics. FAQ "What if my field is hit but the county index is not?" is rewritten around the **ward** index and the basis-risk dispute channel. Payout timing says "within 10 days of a trigger". | **Built in 5**: `web/templates/landing.html` |
| 3 | 6-step enrolment wizard pattern | `public/js/app.js:467-473` (`STEPS`, `initWizard`) and `public/index.html:453` (`#wizardSteps`) | Pattern only (stepper, one question group per step, review before submit) for the SACCO officer enrolment screen. Steps become: member and consent (Data Protection Act) / ward and plot / acreage and layers / premium split and payment route / loan-linked payout consent / review. Quotes come from the pricing API, never front-end maths. | **Built in 5**: `/enrol` (steps: member, plot, cover, consent, price, payment and confirm) |
| 4 | Risk map without basemap tiles | `public/js/map.js:253-290` (Leaflet + GeoJSON, no tile layer since the 2026-10-26 fix) | Rebuilt at **ward** level for the SACCO dashboard and the Payout Tracker, coloured by live WRSI and trigger status. Polygons only, no basemap, for low bandwidth. The demo's `kenya-geojson.js` county shapes are rough outlines, not real boundaries, so they are **not** reused: ward polygons come from an official boundary source. | **Static built in 5** (placeholder ward boxes on the dashboard, inline SVG); 7 (real boundaries, live WRSI) |
| 5 | Behavioural discounts (certified seed, irrigation, SACCO membership) | `server.js:206-210` (5% / 8% or 4% / 3%) | Become rows in the Resilience Score points table in config, earned as **points**, not hardcoded percentages. They reduce only the **farmer share** of premium, inside the configurable discount cap (15% placeholder pending the underwriter). The demo's percentages are not carried over. | **Built in 4** (`product.yaml` `resilience.points`, `quote.py`); score inputs from the photo app in 8 |
| 6 | ESG framework and TCFD reinsurer pack | `server.js:585-600` (`computeESG`), `public/js/esg.js:102, 329-346` (reinsurer pack) | Rebuilt as a **portfolio reporting** module for reinsurers and climate funds (exposure, payouts, inclusion metrics, climate-risk disclosure). It reads the book; it never writes to pricing. A test asserts that the quote API has no dependency on it. | 10 (reporting and IRA export) |
| 7 | A named acceptance scenario | `README.md:163-167` (Makueni, 3 acres maize, KES 7,000-9,500) | Kept as a **regression test**: a named (fictional) farmer, ward and expected premium band produced by *our* engine and recorded when terms are agreed. The band is read from the engine, never used to tune rates. The demo's scenario and band are not used: it was tuned to hit a target. | **Built in 4**: `tests/test_quote_api.py::test_acceptance_scenario_wanjiku_kamau` |
| 8 | "Teal Sovereignty" design tokens | `public/css/agroshield.css:2-90` (`:root` light and dark tokens) | Token values reused for the web portal's colour system (light and dark). Components, layout and the textile motif are not copied. | **Built in 5**: `web/static/portal.css` |

## Not borrowed

| Item | Where it is in the demo | Why not |
|---|---|---|
| County or agro-zone base rates | `server.js:55-70` (e.g. `maize_asal`) | Pricing comes from ward hazard data (WRSI burn cost), never zone rates. |
| ENSO multiplier (SCAF) | `server.js:101-121` | Not part of the index. Seasonal forecast information belongs to Layer A, with measured skill. |
| ESG in pricing | `server.js:585` onward | ESG never feeds the premium (brief, section 3). |
| Parametric "Claims" flow | `public/index.html:504` (`#tab-claims`), `public/js/app.js` `initClaimForm` | Layers A and B pay on the index. The Payout Tracker and the dispute channel replace it. |
| Demo disease result | `public/index.html:460-500`, `public/js/app.js:645` (`initDetector`) | A fixed fake diagnosis. The photo rider uses human review first (milestone 8). |
| "AICP KES 750,000" subsidy rule | demo `README.md`; the code has since changed to a 5-acre cap and KES 1,000,000 ceiling (`server.js:111-115`) | Unverified, and the demo contradicts itself. Subsidy follows KAIP terms from config (milestone 4). |
