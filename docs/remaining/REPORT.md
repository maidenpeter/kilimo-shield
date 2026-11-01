# Remaining brief: report (30 October to 1 November 2026)

Everything below is on `main` unless it says otherwise. The two pricing changes (CHIRPS3 and soil water-holding
capacity) are on their own branches and are **not merged**. Nothing was pushed: there is no GitHub remote yet (see
section 6). Commits are by maidenpeter with no AI attribution. Screenshots of the new screens: `index.html` in this
folder, once the screenshot re-run finishes (section 5; open it from the repo, the images are local and not committed).

## 1. Approval checklist

One line per decision that needs the owner (pending confirmation, needs approval or review, DRAFT, blocked, or a
brief default worth confirming), with the default that is built now. The other decisions are built and listed only in
`docs/DECISIONS_LOG.md`, with their reasons.

**Money and payments (Phase 1)**
- [ ] 1.1 Settlement "collected": default **gross premium received**; refunds owed and paid shown separately, never netted.
- [ ] 1.2 SACCO fee before remitting: default **none**; the SACCO remits gross and its fee is settled separately.
- [ ] 1.3 Receiving paybill: default **per-insurer setting**, set only by platform staff (`agroshield-portal set-paybill`, audited); until set, screens say "the insurer's paybill (to be configured)".
- [ ] 1.5 M-Pesa re-check schedule: default **6 status checks at 2, 5, 15, 60, 240 and 1,440 minutes**, then "Payment not confirmed: check with the farmer" for a manager to decide.
- [ ] 1.7 A push confirmed by status query with no callback: default **credited with the CheckoutRequestID as reference** (the query returns no receipt number); a late callback fills in the receipt.
- [ ] 1.9 Payment started before the sales close and confirmed after it: default **counts toward cover**, and the daily job does not lapse the policy meanwhile (brief rule, built).
- [ ] 1.4 Refunds paid: one refund record per payment made back to a farmer, entered by the SACCO's manager on the member page, never more than is still owed.
- [ ] 1.11 Session cookie marked Secure only when `AGROSHIELD_HTTPS=true`; default **false** so local http works. **Must be set on any HTTPS deployment.**

**Roles and access**
- [ ] 1.10 New role `ops` (AgroShield operations) owns weather advisories shown to every SACCO; managers own their SACCO's only. "Check KMD now" moved to operations.
- [ ] 1.12 KIAMIS records are still shared by every SACCO (the review grouped them with weather; the brief scoped only weather). **Needs approval.**
- [ ] 3.4 Photo reviewers are underwriter accounts (the insurer's agronomists); no separate agronomist role yet.
- [ ] 3.3 Champion farmers photograph other members' farms that an officer assigns (same SACCO only).
- [ ] 4.1 Underwriters see every pilot-ward device (wards with their cover listed first).

**Photo app (Phase 3)**
- [ ] 3.1 Installable web app (PWA) for v1, not a native app.
- [ ] 3.2 Farmers sign in with phone number and a 6-digit PIN the officer sets up (shown once); locked 30 minutes after 5 wrong PINs.
- [ ] 3.5 Check thresholds: refuse beyond **250 m** (allowing for the phone's stated GPS accuracy); same picture at a perceptual-hash distance of **6 bits or fewer**; flag camera and app times **2 h** apart, GPS **500 m** apart, accuracy worse than **100 m**, sent more than **14 days** after taking. ILLUSTRATIVE until field-tested.
- [ ] 3.6 Plots with no recorded location: photos accepted and flagged; they count toward the Resilience point only after a reviewer clears them. **Recommend recording plot points at enrolment.**
- [ ] 3.7 Growth-stage windows (days after planting): 7-30, 31-60, 61-90, 91-120, 121-160. ILLUSTRATIVE, for the agronomists to set.
- [ ] 3.8 Resilience photo point: every stage photographed on schedule with no fraud flag (or one a reviewer cleared), applied to the farmer's next policy for the same season (for example next year's long rains) through the existing Resilience points.
- [ ] 3.9 AI suggestions: `claude-opus-5-5`, image only, EXIF-free, only with the photo_ai consent; the reviewer decides.
- [ ] 3.10 New consent purpose `photo_ai` (wording C-2026-11-01): **pending legal review of the cross-border transfer** (Data Protection Act, 2019).
- [ ] 3.12 Picture-based rider: built, ILLUSTRATIVE (2% of sum insured; payout shares 0, 0, 25%, 50%, 80% by damage band), **switched off in quotes**. Needs owner approval to switch on.
- [ ] 3.13 Farmer weather tab: approved summaries for the farmer's SACCO plus the every-SACCO ones, labelled "Source: KMD"; no SMS of KMD content.
- [ ] 3.14 / 4.8 Photo retention (farm photos and device photos): **no retention period set**. Needs a decision.

**Hardware (Phase 4)**
- [ ] 4.6 / 4.7 / 4.9 Device health, greenness and rain-gauge-versus-CHIRPS thresholds are DRAFT.
- [ ] 4.10 Sentinel camera: photos at 10:00 and 13:00 EAT, GSM by default, SD queue of 400 photos. Compiles; **not tested on a board**.
- [ ] 4.13 MQTT bridge: tested with a stand-in client, **not with a live broker**.
- [ ] 4.16 TAHMO: **blocked** until there is an API account under a data-sharing agreement.

**IRA pack and season (Phase 5)**
- [ ] 5.5 Kiswahili consumer disclosure: needs a native-speaker review (all Kiswahili text in the product does).

**Pricing branches (need approval, not merged)**
- [ ] Phase 7 `pricing/soil-whc`: replace the placeholder soil water-holding capacity with ISRIC SoilGrids values (ward-a 100 to 130 mm, ward-b 140 to 121 mm; index B-1.2.1). Also confirm the field-capacity definition (33 kPa used; 10 kPa gives 181 mm at ward-a) and the 100 cm rooting depth.
- [ ] Phase 6 `pricing/chirps3`: move pricing and monitoring to CHIRPS3. **In progress** (section 4).

**Last night's review ("needs approval", `docs/overnight/REVIEW.md`, 17 rows).** Changed by this run (Phase 1,
9ff7db2, with the review fixes in 73a377e): M-Pesa unconfirmed payments are re-checked and flagged for a manager (1.5
to 1.9); weather advisory approval is scoped by SACCO with the ops role (1.10; KIAMIS still open, 1.12); settlement
"collected" is gross with refunds owed and paid shown separately (1.1, 1.4); the session cookie is Secure with
`AGROSHIELD_HTTPS=true` (1.11). CHIRPS v2 end of production: Phase 6, in progress. **Still unchanged:**
- [ ] No way to reverse a mistaken premium payment (reversal entry with a second approver).
- [ ] With real keys, `MPESA_ENV` still defaults to simulated; the simulator should be refused outside development.
- [ ] SMS outbox can send the same message twice after one bad provider response.
- [ ] Public enquiries: deletion exists; a retention period (recommended 12 months) is still to decide.
- [ ] Login has no rate limit and the failed-login audit stores the typed username (officer portal).
- [ ] Replanting voucher expiry is not enforced, and runs from confirmation rather than issue.
- [ ] A payment received on or before the close date can still be refunded if the lapse job ran first (now handled for M-Pesa pushes started before the close; still open for SACCO deductions entered late).
- [ ] Bordereaux and ESG take the UTC date of stored times, and stored times mix UTC and Nairobi time.
- [ ] One missing key silently puts a deployment in development-key mode; `demo` adds accounts with a public password.
- [ ] Seven weather routes lacked web tests: now covered for the new scope rules (Phase 1 tests); the remaining upload-rejection tests are still to add.
- [ ] Session revocation at logout for officers (a per-officer session version, as built for the photo app).

## 2. What was done, per phase

| Phase | What | Commits on main |
|---|---|---|
| Push | Commit trailers removed from all 26 earlier commits (code unchanged: same tree hash); `docs/COMMIT_HASH_MAP.md` maps old to new hashes. Attribution switched off in both settings files. Repo **not pushed**: see section 6. | b35d99f |
| 1 | M-Pesa re-check with backoff, flagged "Payment not confirmed: check with the farmer" on officer Home and manager Reports, manager resolves with the farmer's receipt; payment started before close counts toward cover. Advisory approval scoped by SACCO with a new `ops` role. Secure session cookie behind `AGROSHIELD_HTTPS`. Settlement gross, refunds owed and paid tracked, per-insurer paybill. | 9ff7db2 |
| 1 review | Independent review, 17 confirmed findings, all fixed. The biggest: M-Pesa times were stored in Nairobi time and read back as UTC, so a push after 21:00 on the close day lapsed; callback and re-check could credit twice. (`REVIEW_PHASE1.md`) | 73a377e |
| 2 | Alembic migrations: baseline of 30 October plus one revision per change; every start upgrades in place (a SQLite file is copied to a `.bak` first; PostgreSQL needs a backup before deploying); the 30 October demo database is recognised and upgraded with every row kept (tested from a committed fixture). | e8c93e4 |
| 3 | Crop photo app (installable web app) for farmers and champion farmers: offline queue, camera with the ghost of the last photo, GPS, stage and plot on each photo; anti-fraud checks; review queue at `/uw/photos` where the reviewer decides and AI suggestions are logged beside the decision (consent-gated, image only); advisory SMS; Resilience photo point; picture rider (ILLUSTRATIVE, off); farmer weather tab. | ceda707 |
| 3 review | Independent review, 28 confirmed findings (several duplicates), all fixed: JPEG comments survived stripping; photos without GPS could earn the Resilience point; shared phones leaked the previous farmer's data; PIN reset did not sign phones out. (`REVIEW_PHASE3.md`) | be3c683 |
| 4 | Hardware layer: device registry, ingestion over HTTPS, an MQTT bridge (tested with a stand-in client, no live broker) and a LoRaWAN webhook, idempotent validated readings, health, underwriter Devices pages; sentinel camera firmware (compiles for GSM and Wi-Fi); soil node payload and decoders; rain gauge with a CHIRPS cross-check; simulator; BOM, enclosure and known-issues notes. Device data never decides a payout (tested). Verified by a second agent. (`PHASE4.md`) | c9d1762, 097f8a8, ba91928, 6e37c51, c96886a |
| 5 | IRA documentation pack: one 27-page PDF plus sources, every page DRAFT and ILLUSTRATIVE (`docs/ira/`). End-to-end simulated 2008 long rains at Rongai West (the illustrative ward-a, with a fictional SACCO and members) on the real services: payout paid 3 days after trigger confirmation, inside the 10-day window (asserted). Verified by a second agent. (`PHASE5.md`, `season-2008/`) | 14eaf9f, 999b382, 972b8c9, f7c1b19, a3a3fd1, c275984, 6ee6fac |
| 8 | Integration of 4 and 5; the QA crawl run (its operations and farmer roles and the jargon check were added in Phase 3), fixes from the crawl (and a log scrubber bug the crawl's server log showed), this report. Leftover worktrees and the `work/*` and `worktree-wf_*` branches removed after checking their content is on main. | 86f7fa3, 7bdcd38, 3e1dadc, and the report commits |

`PHASE4.md` and `PHASE5.md` cite their branch hashes, which are not on main; the main commits are the ones in this
table (335cc0e is c9d1762, f3ca971 is 097f8a8, 5bdfa77 is 14eaf9f, 47ae4dd is 999b382, 52298bd is 972b8c9, 9fef985 is
f7c1b19, 64b7e2c is a3a3fd1, 1d1f66e is c275984).

Separate branches (not merged): `pricing/soil-whc` (Phase 7, c9d96ee, e1e4bbf, 09926e2; branched from e8c93e4) and
`pricing/chirps3` (Phase 6, in progress; branched from b35d99f). Merging either one means rebuilding the IRA pack
(`python tools/ira/build_pack.py`) and the 2008 season (`python tools/sim/season.py`); until then
`test_pack_data_sources_checksums_still_match` fails (`PHASE5.md`).

## 3. Not done, or blocked, and exactly what is needed

- **Push to GitHub**: the GitHub CLI (`gh`) is not installed, so the private repo could not be created. Needed: create an empty **private** repo `agroshield` at github.com/new (no README, licence or .gitignore), then I add it as `origin` and push `main` and the two pricing branches (not the `backup/pre-strip` tag). The pre-push checks are done: no secrets tracked; QA crawl screenshots are ignored (the 38 milestone screenshots under
  `docs/screenshots/` are committed, about 4.6 MB, and will be pushed).
- **CHIRPS3 (Phase 6)**: in progress (section 4).
- **TAHMO rain stations**: blocked. Needed: a TAHMO API account under a data-sharing agreement, and the station codes nearest each ward.
- **Camera firmware on real hardware**: compiles only. Needed: an ESP32-CAM board, a SIM800L, a SIM, a microSD card,
  the power parts in `docs/hardware/BOM.md` and a USB-to-serial adapter. To check on the bench: GPIO 12 is a boot
  strapping pin; the modem's 2.8 V serial line may need a level shifter; the SIM800L does not check the server
  certificate, so confirm it can reach the production server over TLS at all; deep-sleep current, the modem power
  switch, the SD card at low battery and a full queue catch-up.
- **Also not done in Phase 4**: a test against a live MQTT broker (only a stand-in client), and a web screen for
  registering devices (a command for now). Future soil-node firmware must spread a backlog to stay within LoRaWAN
  duty-cycle limits.
- **Policy wording and complaints text** (the IRA pack sections say "[To be written]"): needed from an insurer, once
  one is chosen, and its legal advisers.
- **Pilot wards and product terms**: the ward locations are still placeholders, so the pack and prices stay
  ILLUSTRATIVE until the pilot wards, soils, triggers, loadings and sums insured are agreed.
- **Soil node and rain gauge firmware**: not written (the brief asked for the payload format, decoder and ingestion, which are built).
- **Native-speaker review of all Kiswahili** (app, SMS, disclosure, consent): needed from a person.
- **Legal review** of the photo_ai consent (cross-border transfer) and of the consent wording before live enrolment.
- **HTTPS for the photo app on phones**: GPS, the live camera with the ghost, offline opening and installing all need HTTPS (a deployment with a certificate). Over plain http on a local network, photos arrive flagged "No location from the phone".
- **Stray empty folder** `C:\ADMINI~1` at the root of C: (created by a mistyped path; the file inside was deleted, the folder needs a manual `rmdir`).

## 4. Pricing

**`main`: hashes unchanged.** `tools/qa/pricing_guard.py` re-ran both reference pricing runs at the start
(`pricing_before.json`) and the end (`pricing_after.json`): results.json SHA-256 ward-a `76436465...`, ward-b
`a9ad3062...`, identical to the reference of 29 October, with the four hashed config files unchanged.

**Phase 7, soil water-holding capacity (`pricing/soil-whc`, from main, not merged).** ISRIC SoilGrids 2.0, 250 m,
CC BY 4.0, open WCS, 60 GeoTIFFs cached with checksums. Available water = (water at 33 kPa minus 1,500 kPa) x layer
thickness over 0 to 100 cm, averaged over each ward's CHIRPS box. REAL for the box; the ward locations themselves are
still placeholders. Reviewed by a second agent (09926e2: a stale config snapshot in `ward_awc.json` and a citation fixed; a reproduction
test now checks every derived number in the committed summary).

| Long rains, 45 seasons | ward-a before | ward-a after | ward-b before | ward-b after |
|---|---|---|---|---|
| Soil water-holding capacity | 100 mm (placeholder) | 130 mm | 140 mm (placeholder) | 121 mm |
| Median WRSI | 97.2 | 98.6 | 99.6 | 99.6 |
| Main payout frequency | 20.0% | 15.6% | 2.2% | 2.2% |
| Any payout | 26.7% | 22.2% | 13.3% | 13.3% |
| Expected loss | 8.61% | 7.46% | 3.16% | 3.34% |
| Gross rate | 18.84% | 16.70% | 7.46% | 7.86% |
| 1984 test | passes (81%) | passes (83%) | | |

The spread inside each ward box (ward-a 116 to 141 mm, ward-b 106 to 137 mm, 10th to 90th percentile of pixels) is
larger than the 9 mm gap between the wards. The placeholder idea that the Molo soils hold more water is not supported
by SoilGrids, though SoilGrids is too coarse to rule it out. The branch was made from e8c93e4 (Phase 2), so it needs
rebasing onto current main and the tests re-running before a merge; the early-advance and short-rains research were
not re-run on the new soil values. Full comparison: `docs/pricing/soil-whc-comparison.md` on that branch.

**Phase 6, CHIRPS3 (`pricing/chirps3`, not merged): IN PROGRESS.** The first build agent was cut off by a network
error; its partial work was kept (43daf65) and a second agent finished the loader (920e904). The loader fetches only
the compressed chunks that hold the ward pixels from the Climate Hazards Center's CHIRPS v3.0 daily files (about 50
range requests and 45 to 55 MB per year, instead of a 3 to 5 GB global file; no account needed). Already on the
branch, with tests: the loader, a pricing source switch (default still CHIRPS v2) and the monitoring switch (seasons
from 2027 read CHIRPS v3). Still to come: the full download for both wards, pricing, backtest and early-advance
re-runs on CHIRPS3, the side-by-side comparison (season totals, WRSI, payout seasons, gross rate, 1984 and 2008) and
an independent check. This section is updated when it lands.

## 5. Tests

| When | Passed | Failed |
|---|---|---|
| Start of this run (b35d99f) | 295 | 0 |
| After integrating Phases 4 and 5 (86f7fa3) | 409 | 0 |
| Final main (one more test added in 3e1dadc) | FINAL_COUNT | FINAL_FAILED |

New test files: `test_phase1_review_fixes.py`, `test_phase1_review_round2.py`, `test_migrations.py`,
`test_photos.py` (including the offline queue in a real Chrome), `test_photos_review.py`, `test_devices.py`,
`test_device_simulator.py`, `test_phase5_ira.py`.

QA crawl (`qa-final-summary.md`): 58 pages (every role, including the new operations and farmer roles) x 4 widths x light and dark = 464 views: 0 axe-core violations; no horizontal scroll, navbar wrapping, extra or missing h1, console errors, failed requests or broken links. It found two things, both fixed and re-checked (manager and farmer roles at 375 and 1440 px): rainfall index terms (CHIRPS, WRSI, dekad) on the manager Reports page, now behind Details; and an image check that counted the photo app's empty placeholder images. The only tap targets under 44 px are licence and citation links inside sentences, as last night. A re-run with screenshots for `index.html` is in progress (the first re-run hung in the browser after the public pages and was restarted).

## 6. Still needed from the owner

1. The approval checklist in section 1, especially the money defaults (1.1 to 1.3), the photo_ai legal review, photo
   retention, and whether to merge the soil branch (and CHIRPS3 once it lands).
2. A private GitHub repo named `agroshield` (or `gh` installed and signed in as maidenpeter), so I can push.
3. A Kiswahili reviewer, a lawyer for the consent and cross-border wording, and, once an insurer is chosen (none is
   named yet), its policy wording and complaints text.
4. Plot locations at enrolment, so the photo distance check works for every farm.
5. Hardware for a bench test (ESP32-CAM, SIM800L, SIM, microSD card), and, if wanted, a TAHMO API account under a
   data-sharing agreement plus the station codes nearest each ward.
6. A server with HTTPS for field tests of the photo app.
7. Remove the empty folder `C:\ADMINI~1` by hand (`rmdir`).
8. Choose the real pilot wards (and agree the triggers, loadings and sums insured); the soil values and the IRA pack
   numbers must then be re-derived for them.
