# Morning report: overnight run, 29 to 30 October 2026

Everything below was done unattended, following `../OVERNIGHT_BRIEF.md`. Nothing was pushed, emailed, posted or
submitted. Outside contact was limited to openly licensed image and fact sources (read only) and, for Phase E, two free
satellite data services. Tuko and KNA were never contacted, and KMD was not contacted at all tonight.

Open `docs/overnight/index.html` from the repository folder to see every page before and after, side by side, by role,
width and colour scheme. The screenshots are local files and are not committed.

## 1. Work per phase

| Phase | Commit | What |
|---|---|---|
| A. Baseline | `cd113aa` | Reference pricing hashes saved (`pricing_reference.json`). Playwright crawl of every route and role at 1440, 1024, 768 and 375 px, light and dark, with axe-core, console, request, link and image checks (`before.json`, `before-summary.md`). Baseline issue list (`BASELINE_ISSUES.md`). |
| B. Design system and navbar | `90e9a98` | One tokens file (colour light and dark with system default plus toggle, type scale, 4/8 spacing, radius, shadow, motion). NuruOps theme with teal kept (`docs/design/THEME.md`). New navbar for public, officer, manager and underwriter, with dropdowns on click, account menu, developer menu in dev mode only, and a mobile sheet that traps focus. It never wraps: each role collapses to Menu before it could. Applied to every page without changing behaviour. |
| C. Public site and knowledge | `d96149e` | Home (underwriter value first), Crops, Livestock (in development, Register interest), How it works, For insurers (product structure, data sources, audit trail, real demo screenshots, honest placeholder list), For SACCOs, Learn hub plus eight articles, Questions, Credits, Request a demo. 16 licensed photos self-hosted. Forms store locally only, encrypted. |
| D. App polish and settlement | `5c5c9da` | Premium settlement tracking (SACCO records, underwriter confirms or queries, audited, CSV). Underwriter KPI strip, three charts, season and SACCO filters, aggregated CSV, sticky table headers. First-run Home and empty states for officers and managers, with the 6b layout kept. |
| E. Livestock feasibility | `c4374de` | EXPERIMENTAL feasibility study (`docs/research/livestock-feasibility.html` and `.json`). MODIS NDVI (NASA ORNL, 250 m, 2000 to 2026) was reachable and clean (98% good pixels) for two rangeland boxes around Laisamis (Marsabit) and Merti (Isiolo). ClimateSERV eMODIS returned no values. A one-in-five trigger, judged leave-one-out, fires in 5 or 6 of 25 seasons per site. The two sites' scores correlate at 0.79 and 0.85, but only about half of the trigger seasons are shared, so insurance units must be small. Nothing was added to quotes, enrolment or config. |
| F. QA loop | `d613ccc`, the Phase H commit (last in `git log`) | Crawl pass 1, then fixes, then a final crawl with screenshots (`after.json`, `after-summary.md`, `docs/overnight/after/`). |
| G. Review | `d613ccc` | `REVIEW.md`: five independent reviewers, each checked by a skeptic. 27 low-risk fixes made with tests; 17 items need approval and were left unchanged. |
| H. This report | the Phase H commit (last in `git log`) | This file, `index.html` (before and after), `pricing_check_after.json`. |

## 2. Not done, and why

- **EN/SW language switch on the public site.** There is no full Kiswahili copy to switch to. Farmer-facing sections
  carry Kiswahili text marked "pending native-speaker review" instead.
- **Check on a real Android phone.** No device was available. Mobile behaviour is covered by emulation tests (Pixel 5
  and 375 px) and the touch tests.
- **The 17 "needs approval" review items** (section 6): left unchanged under ground rule 2.
- **Small inline links** (citation numbers like [3] and the licence link in photo captions) stay under 44 px. They sit
  inside sentences, which is the standard inline-text exception (WCAG 2.5.8). Every other target is 44 px or more.
- **Low-contrast text over images** cannot be measured by axe. It was checked by eye at every width in both themes.
  On screens under 900 px the whole photo now sits under a dark wash (`--overlay-strong`).
- **Performance items** marked "later" in `REVIEW.md` (pagination of Members, eager loading, static caching). None is
  urgent at pilot size.
- **A smoke test of the `daily` and `demo` commands** is still a test gap. The README now documents scheduling `daily`.
- Nothing hit the 45-minute time-box. The Phase E download was slow (about 45 minutes per site at one request at a time), but it was never blocked and it completed.

## 3. Pricing hashes

`agroshield-price run --all --offline` was re-run after phases A to G (`pricing_check_after.json`):

| Ward | Reference `results_sha256` (Phase A) | After | Same |
|---|---|---|---|
| ward-a | `76436465366497deb69a8c2747798ad78b7de83a9a7846c0722d047a0f96e873` | `76436465366497deb69a8c2747798ad78b7de83a9a7846c0722d047a0f96e873` | yes |
| ward-b | `a9ad3062d46964dfc78111f9b69254cbd975c6f5ba29e74fa6d71d573697a291` | `a9ad3062d46964dfc78111f9b69254cbd975c6f5ba29e74fa6d71d573697a291` | yes |

The config file hashes are identical too. Nothing was reverted, because nothing changed. Pricing, index, trigger and
payout logic were not touched. The only change in `agroshield_pricing` is presentation in the HTML run report template:
keyboard access on scrollable tables, labelled empty headers and a 44 px disclosure.

## 4. Tests

| | Tests |
|---|---|
| Before (start of Phase A) | 221 passed |
| After Phase B | 232 passed |
| After Phase C | 262 passed |
| After Phase D | 275 passed |
| After Phases F and G | 295 passed |

New test files: `test_navbar.py` (real browser, every role at five widths), `test_public.py`, `test_settlement.py`,
`test_review_fixes.py`.

## 5. QA

Same crawler, same fictional demo data, every route and role at 1440, 1024, 768 and 375 px in light and dark.

| Check | Before | After |
|---|---|---|
| Pages (routes x roles) | 34 | 49 |
| Page views | 272 | 392 |
| Views with axe-core violations | 272 | 0 |
| axe-core violation nodes | 400 (4 rules) | 0 |
| Navbar on more than one row | 186 views | 0 |
| Horizontal scroll | 0 | 0 |
| h1 count not 1 | 16 views | 0 |
| Heading levels skipped | 0 | 0 |
| Console errors | 0 | 0 |
| Failed requests | 0 | 0 |
| Broken images, images without alt | 0, 0 | 0, 0 |
| Broken internal links, non-200 pages | 0, 0 | 0, 0 |
| Tap targets under 44 px at 375 px | 248 | 120, all inline citation numbers and photo licence links inside sentences |
| Elements overflowing their box | 6 views | 0 |

Other checks:
- Decimal input accepts commas, for example the remittance amount "1,500".
- Forms show a working state and block double submits (`nav.js`).
- Empty, error and loading states: 400, 403, 404 and 500 pages; first-run Home; empty Members, Portfolio and settlement.
- WCAG AA contrast in both themes (axe), with input borders at least 3:1.
- Fonts self-hosted; images in two sizes as WebP with a JPEG fallback, lazy below the fold.

## 6. Review findings

The full table is in `REVIEW.md`. Each line below gives the finding and a one-line recommendation.

### Needs approval (left unchanged)

- **M-Pesa callback left 'unconfirmed' is never credited or re-checked, so a farmer's money can be taken with no cover** (high, `src/agroshield_platform/mpesa.py:200`). Add a scheduled re-check (STK query) for unconfirmed callbacks with an officer view and a manual credit or reject, audited. Money handling, so not changed tonight.
- **Monitoring depends on CHIRPS v2.0 only, and v2 ends production before the LR 2027 season now on sale** (high, `src/agroshield_pricing/rainfall/chirps.py:33`). Plan the move to CHIRPS v3 before January 2027: fetch v3 for the pilot wards, re-run both reference pricings and compare, then decide with the underwriter. Index input, so not changed tonight.
- **Any single SACCO's manager can change records shared by all SACCOs and insurers (weather advisories, KIAMIS records)** (medium, `src/agroshield_platform/web/app.py:930`). Decide who owns weather advisories and KIAMIS records (platform staff, not any SACCO manager), then scope the routes and add web tests. Role model change.
- **Settlement 'collected' and UW money 'received' count money owed back to farmers as premium owed to the insurer** (medium, `src/agroshield_platform/settlement.py:109`). Decide whether over- and late payments owed back to farmers are netted out of 'collected'. Recommended: show 'collected, net of refunds owed' and a refunds column on both screens.
- **No way to reverse a mistaken premium payment or record that a refund was paid** (medium, `src/agroshield_platform/services.py:311`). Add a reversal entry (negative payment with reason, manager plus second approver) and a 'refund paid' record. Money handling.
- **With real keys, MPESA_ENV still defaults to 'simulated', so the M-Pesa simulator and fake B2C payouts work in production** (medium, `src/agroshield_platform/web/app.py:769`). Refuse to start with real keys unless MPESA_ENV is set explicitly, and hide the simulator outside development. Money path.
- **Session cookie is set with https_only=False, and serve has no TLS or proxy setting** (medium, `src/agroshield_platform/web/app.py:162`). Set https_only from config (true outside development) and document running behind an HTTPS proxy. Auth design, and it would change how tests run.
- **The SMS outbox can send the same message twice, and one bad provider response makes the whole batch resend** (medium, `src/agroshield_platform/sms.py:91`). Mark each message as sending before the provider call and record per-message results, so one bad response cannot resend a batch. Messaging path.
- **Public enquiry consent promises deletion, but there is no deletion path or retention rule, and the cited review doc is missing** (medium, `src/agroshield_platform/enquiries.py:26`). Deletion now exists (`agroshield-portal enquiries --delete REF`, audited; test_enquiry_can_be_deleted_on_request). Still to decide: how long enquiries are kept (recommended: 12 months, then delete).
- **Session cookie is never marked Secure and cannot be revoked at logout** (low, `src/agroshield_platform/web/app.py:161`). As above (https_only from config), plus a per-officer session version checked in require() so logout and deactivation end every session.
- **Login has no rate limiting or lockout, and failed-login audit stores the raw typed username** (low, `src/agroshield_platform/web/app.py:327`). Throttle by username and IP with backoff, run a dummy password hash for unknown users, and scrub the attempted username in the audit. Auth design.
- **Replanting voucher expiry is never enforced, and expiry runs from confirmation rather than issue** (low, `src/agroshield_platform/monitoring.py:221`). Enforce voucher_valid_days from issue (approval) date and show expired vouchers. Payout logic.
- **A payment received on or before the close date is still refunded if the daily lapse job ran first** (low, `src/agroshield_platform/services.py:325`). When a payment dated on or before the close arrives after the lapse job, reinstate cover instead of refunding, with an audit entry. Policy and money logic.
- **Bordereaux and ESG use the UTC date of naive SQLite datetimes, and stored datetimes mix UTC and Nairobi wall time** (low, `src/agroshield_platform/underwriting.py:168`). Store all timestamps in UTC and convert to Africa/Nairobi before taking dates or months; add offsets in CSV timestamps. Changes bordereau contents.
- **One missing key silently puts a deployment in dev-key mode: the key file sits beside the database, and 'demo' adds accounts with a public password** (low, `src/agroshield_platform/settings.py:98`). Refuse to start when some but not all production keys are set, and when DATABASE_URL is not SQLite but dev keys would be used. Deployment safety.
- **Monthly bordereaux place policies in months by UTC date, not the Nairobi date** (low, `src/agroshield_platform/underwriting.py:168`). Same as the UTC dates item above.
- **Seven weather routes have no web tests, and any SACCO's manager can approve or withdraw advisories shown to all SACCOs** (low, `src/agroshield_platform/web/app.py:930`). Part of the weather ownership decision above; then add web tests for role gating, upload rejection, approve and withdraw.

### Fixed tonight

- **File uploads are read whole into memory with no size limit** (medium, `src/agroshield_platform/web/app.py:707`). Uploads are read with a hard limit (5 MB CSV, 20 MB PDF) and refused with 413 above it. Test: test_uploads_over_the_limit_are_refused.
- **Field error messages are not linked to their inputs (no aria-describedby / aria-invalid)** (medium, `src/agroshield_platform/web/templates/_macros.html:8`). Inputs with an error now carry aria-invalid and aria-describedby pointing at the message (new invalid() macro). Test: test_field_errors_are_tied_to_their_inputs_and_radios_are_grouped.
- **Radio groups use an orphan <label> instead of fieldset/legend, so the question is never announced** (medium, `src/agroshield_platform/web/templates/enrol_step.html:30`). Radio questions are fieldset plus legend on enrolment, quick price and the missed-payout form. Same test.
- **Form field borders fail non-text contrast (about 1.5:1) in both themes** (medium, `src/agroshield_platform/web/static/tokens.css:30`). New --input-border token, 3.6:1 (light) and 3.6:1 (dark) or better against the input and card surfaces. Test: test_input_borders_meet_non_text_contrast.
- **The secret callback token is written in clear to the uvicorn access log, which the log scrubber does not cover** (medium, `src/agroshield_platform/cli.py:77`). `serve` now uses a uvicorn log config whose handlers redact /ussd/<token> and /mpesa/callback/<token> and mask IDs and phones. Tests: test_callback_token_is_redacted_and_ids_scrubbed_in_access_logs, test_scrub_filter_still_masks_numbers_passed_as_ints.
- **Public forms promise an email reply and deletion on request, but nothing in the code can do either** (medium, `src/agroshield_platform/web/templates/public/_ui.html:74`). Copy now says 'We aim to reply by email', and deletion on request is possible from the CLI. Retention period is in 'needs approval'.
- **Form says phone numbers in the message are masked, but scrub() misses dashed, dotted and bracketed numbers and 6-digit IDs** (medium, `src/agroshield_platform/web/templates/public/_ui.html:108`). The hint now asks people not to type ID or phone numbers, instead of promising masking. The scrub rule itself (masking rules) is unchanged.
- **Pages promise the full sum insured at WRSI 50 or below, but a replanting voucher already issued reduces that payout** (medium, `src/agroshield_platform/web/templates/public/crops.html:28`). Crops, How it works, For insurers and the crop-index article now say all payouts in a season together never exceed the sum insured, and a voucher counts toward it.
- **Farmer full names are written into the session cookie through flash messages, which are signed but not encrypted** (low, `src/agroshield_platform/web/app.py:386`). Flash messages name the policy number, not the farmer. Test decodes the session cookie: test_flash_messages_carry_no_farmer_names_in_the_cookie.
- **CSV exports write user-controlled text without neutralising spreadsheet formulas** (low, `src/agroshield_platform/services.py:521`). All CSV exports (policy register, bordereaux, portfolio, settlement) go through csvsafe.writer, which prefixes risky text cells with an apostrophe and leaves numbers alone. Tests: test_csv_cells_cannot_become_formulas, test_policy_export_neutralises_formula_names. Bordereaux bytes are unchanged for normal data.
- **Callback secret token and unscrubbed exception text reach logs** (low, `src/agroshield_platform/cli.py:76`). Token redaction and scrubbing on uvicorn logs as above. Remaining: tracebacks from unhandled errors are not scrubbed (needs a formatter change; low).
- **KAIP subsidy receivable includes lapsed policies on the SACCO dashboard but excludes them in the insurer's Money page** (low, `src/agroshield_platform/services.py:499`). SACCO Reports now leaves lapsed cover out of the KAIP receivable, the same rule as the insurer's Money page. Test: test_kaip_receivable_excludes_lapsed_cover_on_sacco_reports.
- **Quote breakdown 'Farmer pays' rounds to nearest while the amount due is rounded up, so it can show 1 KES less** (low, `src/agroshield_platform/web/templates/_macros.html:45`). Every 'Farmer pays' figure shows the whole-shilling amount actually asked for (rounded up), via a kes_due filter. Test: test_quote_breakdown_shows_the_amount_actually_asked_for. Prices themselves are unchanged.
- **Public enquiry inputs with no type attribute miss all input styling, including the 44px tap target** (low, `src/agroshield_platform/web/templates/public/_ui.html:84`). Name, organisation, county and the hidden field now have type=text, so they get the 44 px input style (found by the QA crawl too).
- **Chart values are only inside role=img (SVG <title> tooltips), so monthly premium and payout amounts have no text alternative** (low, `src/agroshield_platform/web/templates/uw_portfolio.html:52`). Each portfolio chart is followed by a visually hidden data table with the same figures.
- **Payout 'reference' input before 'Pay now' has only a placeholder as its label** (low, `src/agroshield_platform/web/templates/payouts.html:37`). The input now has an aria-label naming the reference type and the policy number.
- **Kiswahili text rendered without lang="sw"** (low, `src/agroshield_platform/web/templates/home.html:49`). lang=sw on Kiswahili summaries (Home, underwriter Weather), the manager's Kiswahili editor, and the language of each SMS in the log.
- **Farmers' full names are written into the readable session cookie, against the stated rule** (low, `src/agroshield_platform/web/app.py:386`). Same fix as above: policy number in flash messages; cookie decoded in a test.
- **Nothing documents or tests running the 'daily' job that lapses cover and creates payouts** (low, `README.md:48`). README now explains scheduling `agroshield-portal daily` (time, what it does, what breaks without it). A smoke test of the CLI is still a test gap.
- **README and .env.example are out of date with the code** (low, `README.md:45`). README: demo contents, enrolment steps, workspace pages, new modules, public site, settlement, daily schedule. .env.example: AGROSHIELD_CONFIG.
- **Farmer-facing pages imply the KAIP 50% subsidy applies to this product, while the KAIP article says it does not say that** (low, `src/agroshield_platform/web/templates/public/crops.html:67`). Crops, For SACCOs and Questions now say it is not confirmed whether this cover qualifies, and that quotes treat the share as an assumption.
- **Home and insurer pages say the payout clock is built around the draft 10-day rule, but the clock starts weeks later, at index confirmation** (low, `src/agroshield_platform/web/templates/public/home.html:41`). Home, For insurers and How it works now say the clock counts 10 days from index confirmation, which can be weeks after the trigger date the draft is reported to use.
- **Two Learn articles give opposite readings of the same IBLI basis-risk figure** (low, `src/agroshield_platform/articles.json:490`). The livestock article no longer quotes the 62 to 77% figure; it keeps the source's point that most of the gap comes from household-level losses. The basis-risk article keeps the study's own wording.
- **"Ready to pilot" and "live product" overstate the crop cover's status** (low, `src/agroshield_platform/web/templates/public/home.html:19`). 'Live product' removed from the livestock article. 'Ready to pilot' kept on the public pages because For insurers lists every open item.
- **SACCO page says enrolment takes five screens, but the wizard has four** (low, `src/agroshield_platform/web/templates/public/saccos.html:24`). For SACCOs and the first-run Home now describe the steps without a count.
- **Credits page "Used on" column is wrong for several photos, two of which appear on no page** (low, `src/agroshield_platform/web/static/img/credits.json:131`). 'Used on' is now read from the templates at start-up; photos on no page are left off /credits (still listed in IMAGE_CREDITS.md as spares).
- **Glossary defines "indemnity" differently from the index-insurance article** (low, `src/agroshield_platform/articles.json:699`). The glossary entry is now 'Indemnity cover' with the same meaning as the article (traditional, loss-assessed cover).

## 7. Theme

NuruOps "Midnight Gold" (dark `#0F1117` / `#1A1D26`, gold `#E8960C`, warm paper `#F6F3EC` in light), with AgroShield's teal
kept as the signature accent (`#00695C` light, `#2DD4BF` dark). EB Garamond (OFL, self-hosted) is used for headings and
the system sans for body and numbers. Sources and decisions are in `docs/design/THEME.md`.

## 8. Images

16 Wikimedia Commons photos of Kenya, each licence read on its file page and checked a second time by an independent
reviewer:
- Licences: CC0, public domain (USAID), CC BY 2.0 and 3.0, CC BY-SA 2.0, 3.0 and 4.0.
- No public figures, no AI-generated people, no logos.
- Self-hosted as WebP plus JPEG at 800 and 1600 px.
- Credited on `/credits` (the "used on" column is read from the templates) and in `docs/design/IMAGE_CREDITS.md`.
- Skipped: `Small-cropping-kenya (52428136678).jpg`. Commons lists it under "USDA images (review needed)", so its
  public-domain status is not confirmed.
- Two licensed photos are kept as spares, on no page: `camels-isiolo-road` and `dry-river-kitui`.
- The workspace screenshots on For insurers are AgroShield's own, on fictional demo data.

## 9. Approval checklist

- [ ] **Public site copy.** Read Home, Crops, Livestock, How it works, For insurers, For SACCOs, Questions and the eight
      Learn articles. Every figure is sourced, and the fact-check log is `phase_c_article_checks.json`. Approve
      publishing, or list changes.
- [ ] **Kiswahili.** The glossary and farmer sections need a native-speaker review before publishing.
- [ ] **"Ready to pilot".** Is this the right public status for crop cover? It is kept because For insurers lists every
      open item.
- [ ] **KAIP on public pages.** They now say eligibility of this cover for the subsidy is not confirmed. Confirm the wording.
- [ ] **Premium settlement.** The design is a ledger only: the SACCO records, the insurer confirms. Three open points:
  - Is "collected" net of refunds owed to farmers?
  - Does the SACCO deduct its distribution fee before remitting?
  - Whose M-Pesa paybill receives premium: the SACCO's or the insurer's?
- [ ] **Public enquiries.** Retention period (proposed: 12 months, then delete), who replies, and where requests are read
      (`agroshield-portal enquiries`).
- [ ] **The 17 "needs approval" items** in `REVIEW.md`. Most urgent:
  - the M-Pesa "unconfirmed" callback with no re-check;
  - CHIRPS v2 ending after December 2026, before LR 2027 monitoring;
  - who may approve weather advisories;
  - https-only session cookies in deployment.
- [ ] **Livestock next step**, after the Phase E feasibility note (`docs/research/livestock-feasibility.html`).
- [ ] **Navigation decisions.** Payouts was removed from the officer and manager top bar, as the brief's lists say; it
      is reachable from Home. An underwriter Weather page (read only) was added.
- [ ] **Push.** Nothing is pushed. Review the commits listed in section 1 and push when ready.

## Decisions made overnight (no one to ask)

- Screenshots for before and after are kept out of git (about 30 MB each). `index.html` links to them locally.
- Body text uses the system sans and headings use EB Garamond. NuruOps sets everything in Garamond, which reads poorly in
  dense tables.
- The KLIP payout figure is cited to the World Bank KLIP paper. A "70,000 livestock" figure and any Swiss Re attribution
  could not be verified and were left out.
- Footer heading "Partners" was renamed "Work with us", to avoid implying partnerships.
- The demo data gains one fictional remittance, so the settlement screens have something to show.
- Phase E used the NASA ORNL MODIS service because ClimateSERV's eMODIS NDVI returned no values for the test area.
