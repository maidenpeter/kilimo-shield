# AgroShield

Parametric maize insurance for Kenyan smallholders, distributed through SACCOs and
underwritten by a licensed insurer. AgroShield is the technology and pricing layer,
not the risk carrier.

> "AgroShield protects the season before it fails, and rewards farmers who farm smarter."

**Status:** milestones 1-7 of 10 (quote API in 4; SACCO portal and data model in 5; USSD, M-Pesa
and SMS in 6; ward monitoring, Payout Tracker and weather advisories in 7) and research task 3b.
Layer B is a seasonal WRSI index (B-1.2.0) with failed-onset and germination dry-spell
triggers; the superseded per-phase index (v0) is kept for comparison only. Layer A
(anticipatory seed voucher) is **dropped from the product** (2026-10-29): its code is kept,
switched off. An EXPERIMENTAL early advance on Layer B at Ward A is validated and priced,
but not in quotes.
Everything priced here is **illustrative**: pilot wards, soil, crop calendars, trigger
levels, loadings and sum insured are placeholders. Rainfall is real (CHIRPS); PET is a
flagged fallback (Hargreaves from NASA POWER temperature).

Pilot scope: maize, long rains only, at two placeholder Nakuru wards.

## Quick start

```bash
python -m venv .venv --system-site-packages
.venv/Scripts/pip install -e .[dev]          # Windows; use .venv/bin/pip elsewhere
.venv/Scripts/agroshield-price run --ward ward-a
```

That prices one ward from the committed inputs and prints where its report is:
`runs/<run_id>/report.html` (open in any browser, works offline), with
`results.json` and `manifest.json` beside it.

| Command | What it does |
|---|---|
| `agroshield-price run --ward ward-a` | Price one ward (default: `pilot.default_ward`) |
| `agroshield-price run --all` | Every pilot ward |
| `agroshield-price run --source synthetic` | Generated rainfall and PET instead of real data |
| `agroshield-price run --offline` | Never download; fail if inputs are not cached |
| `agroshield-price fetch-rainfall --all [--refresh]` | Download and cache CHIRPS |
| `agroshield-price fetch-climate --all [--refresh]` | Download and cache NASA POWER temperature |
| `agroshield-price quote --ward ward-a --acres 2 --layers A,B --resilience certified_seed_verified` | Quote a farmer from the command line |
| `agroshield-api` | Quote API on http://127.0.0.1:8770 (interactive docs at `/docs`) |
| `agroshield-price validate` | Check the config without pricing |
| `agroshield-portal demo` | Two fictional demo SACCOs with fictional members, an officer, a manager and an underwriter, a 2008 replay and one demo remittance (development keys only) |
| `agroshield-portal enquiries [--delete REF]` | Public-site demo requests and livestock interest, contact details masked; delete one on request |
| `agroshield-portal serve` | SACCO officer portal on http://127.0.0.1:8780 |
| `agroshield-portal add-sacco` / `add-officer` | Set up a SACCO and its officers (password prompted) |
| `agroshield-portal daily` | M-Pesa re-check, lapse cover not fully paid at sales close, SMS reminders, send queued SMS |
| `agroshield-portal mpesa-recheck` | Status-check M-Pesa payments that have no final answer yet (every 5 minutes) |
| `agroshield-portal send-sms` | Send queued SMS now |
| `pytest` | Run the tests |

## Layer B v1: seasonal WRSI

The FAO / FEWS NET Water Requirement Satisfaction Index, on a dekadal water balance:

1. Daily CHIRPS rain and daily PET are summed to dekads.
2. **Failed onset:** if the whole planting window gets less than a threshold of rain, the
   season never started; it pays a fixed share of sum insured and there is no WRSI season.
   Otherwise the **start of season** is the first dekad with at least 25 mm (planting rain).
   **Germination dry spell:** if the 20 days after that planting rain bring too little rain,
   the replanting seed cost is paid (fixed KES per acre) and the season restarts at the next
   planting rain.
3. From the start, for each dekad of the growing period: crop coefficient Kc from the
   FEWS NET maize curve (0.3, 0.3, 1.2, 1.2, 0.35 at 0/16/44/76/100% of the season),
   water requirement `Kc x PET`, and a soil bucket of the ward's water holding capacity.
   Actual ET falls below the requirement once the soil is drier than `(1 - p) x capacity`.
4. **WRSI** = 100 x total actual ET / total requirement at the end of the season.
5. **Payout**: 0 at or above the trigger (80), linear to full at or below the exit (50,
   crop failure).

An **EXPERIMENTAL flowering dry-spell component** (longest dry spell or rainfall deficit in
the flowering window) is priced separately, off by default, and shown beside WRSI-only.

The engine applies this to every season since 1981 and prices the product per sum-insured
option in KES (the replanting payout is a fixed amount). It reports each ward's own target
payout frequency (placeholders: Ward A 1 in 5-7, Ward B 1 in 8-12), every season an
early-season trigger fired and why, each component priced alone, trigger and soil-capacity
sensitivity, the 1984 event (required at Ward A, reported at Ward B), the 10 worst seasons,
and v1 against v0.

There is no claims flow for the parametric layers: they pay on the index.

## Layer A: pre-season seed voucher (dropped, code kept)

**Dropped from the product on 2026-10-29** (`layer_a.enabled: false`): measured C3S
March-May skill caught 2 of 11 Layer B payout seasons with a 67% false alarm ratio. Nothing
is priced, quoted or sold; the code and tests stay so it can return where forecast skill is
real (see the short-rains research below). What follows describes the switched-off code.

Before planting, if the seasonal outlook gives at least a set probability (45%,
placeholder) of below-normal rain over March-May at the ward, insured farmers get a fixed
voucher per acre for drought-tolerant certified seed through their SACCO.

Until KMD / ICPAC hindcasts are available the forecast is **SYNTHETIC**: generated from the
observed CHIRPS rainfall with a set skill (correlation), calibrated so that zero skill is
climatology and never triggers. Each draw is one possible 45-season hindcast; the report
summarises 2,000 draws (median and 5-95% range) because with so few seasons the realised
scores vary a lot by chance. It reports voucher frequency, expected cost and gross premium
per acre, and hit rate / false alarm rate / false alarm ratio scored against both
below-normal rain and Layer B payout seasons, plus sweeps over forecast skill and the
probability threshold. Skill is configured per season (long and short rains separately);
the real values must come from hindcasts.

## EXPERIMENTAL: early advance on Layer B (Ward A)

At day 35 after the start of season, the end-of-season WRSI is projected from observed
CHIRPS, the CHIRPS-GEFS 15-day forecast and climatology. Below 95, the farmer is paid 20% of
the sum insured at once. The advance is deducted from the end-of-season Layer B payout and
never clawed back, so the farmer receives the larger of the two; only the net extra cost is
priced. Terms are in `product.yaml` (`layer_b.advance`), and config refuses to put an
EXPERIMENTAL advance into quotes. Validation (2000-2025, leave-one-out) and pricing:
`research/advance.py`, report in `docs/research/advance-and-short-rains.html`. Not offered
at Ward B.

## Quotes: subsidy split and Resilience discount

A quote takes the per-acre gross premium straight from the engine (a rate book built
from `price_ward` for each ward; the API never re-prices), then splits who pays:

```
gross            = sum of chosen layers' gross per acre x acres
government share = 50% of gross (KAIP), only for 0.5-20 acres; "not yet received" until paid
farmer share     = gross - government share
Resilience       = min(15%, points x 1%) x farmer share      (farmer share only)
farmer pays      = farmer share - Resilience discount
```

Resilience points come from a table in `product.yaml` (certified seed, photos on
schedule, verified practices, irrigation, SACCO standing); within a group such as
irrigation only the highest item counts. Subsidy terms, the cap and the points are
ILLUSTRATIVE pending KAIP and the underwriter. `POST /v1/quotes` takes everything in the
request body and logs each quote to `var/audit/quotes.jsonl`; quotes carry no personal data.

- **Subsidy:** none at all outside 0.5-20 acres. Whether KAIP would subsidise the first 20
  acres of a larger farm is unconfirmed.
- **Who funds the Resilience discount:** the insurer always receives the full gross
  premium. The discount is paid by the funder in config (`resilience.funder`: `platform`,
  meaning out of AgroShield's platform fee, or a partner, `seed_company` or `sacco`). Every
  quote shows the funder and who pays the insurer what, and flags a discount larger than
  the platform fee. The discount rewards good practice; it does **not** reduce the
  parametric risk, because payouts follow the ward index whatever the farmer does.

## SACCO portal and data model (milestone 5)

Since milestone 6b the portal serves two audiences:
- **Officers** (the default) see Home, Enrol a farmer and Members, in plain words.
  - Home shows who still owes, with a Send reminder button for each, then the ward alert line and the Enrol button.
  - Enrolment is one step per screen: member, farm, agreement, then cover, price and payment, then a done screen.
  - Each price is first given as one sentence.
- **Managers** also get Reports (the portfolio, map and export) and Import (bulk CSV and KIAMIS together).
- **Details toggles:** pricing build-up, quote IDs and index versions sit behind them.
- **Developer menu:** the SMS log and M-Pesa simulator appear only with development keys.
- **Ward names:** display names come from `config/wards.yaml` (placeholders).

Before and after screenshots are in `docs/screenshots/m6b/` (open `index.html`).

A server-rendered portal (FastAPI + Jinja, no JavaScript build, works on slow office
connections) for SACCO officers:

- **Enrolment wizard** (see above): member, farm, consent, then cover, price and payment, and a
  confirmation. Prices come from the same rate book as the quote API.
- **Bulk enrolment** from CSV: a dry run reports every problem row; saving is then
  all-or-nothing.
- **Dashboard**: members, policies, acres, sum insured, premium due, KAIP subsidy
  receivable ("not yet received"), loan-linked exposure, a by-ward table and a
  placeholder ward map. Live trigger status arrives with monitoring in milestone 7.
- **Members** (masked IDs and phones), each with its policies and consent record;
  masked CSV export; **KIAMIS** CSV import for managers (manual fallback, IDs hashed).

Data protection (Kenya Data Protection Act):

- Consent is recorded per purpose (data processing, which is required, then SMS and
  loan-linked payout), with the wording version and its SHA-256
  (`config/consent.yaml`).
- National IDs and phone numbers are stored only AES-256-GCM encrypted, with a keyed
  HMAC for look-ups. They are masked in every page, export, audit event and log line.
- Personal data never goes into a URL: search is POST, and wizard state stays on the
  server under a random token.
- Tests read the raw database file, rendered pages, links and audit rows for any clear
  ID or phone.

Since 2026-10-29:

- **Consent:** all consent text is marked "pending legal and Kiswahili review", and live
  enrolment is blocked until both reviews are recorded in `config/consent.yaml` with a new
  version. Demo SACCOs (fictional members only) can still enrol.
- **Sales windows:** each ward and season has a sales window in `phenology.yaml`. It opens
  after the local harvest (placeholder dates) and closes at least 14 days before the
  planting window opens; config validation enforces this.
- **Enrolment and payment:** enrolments outside the window are refused. The farmer share can
  be paid in instalments, and cover becomes active only once it is fully paid by the close
  date. Anything paid after the close date, or above the amount due, is recorded as a
  refund due.
- **References:** `AGS-...` is the AgroShield certificate reference. A separate insurer
  policy number is added by a manager once the underwriter issues it.

Storage is SQLite for development, with portable SQLAlchemy models. PostgreSQL and
PostGIS come for deployment, via `DATABASE_URL`. Keys come from the environment
(`.env.example`). Without them, development keys are generated into
`var/dev-keys.json` and the portal shows a development banner.

## USSD, M-Pesa and SMS (milestone 6)

- **USSD** (Africa's Talking callback, `POST /ussd/<CALLBACK_TOKEN>`) for enrolled members, in
  English or Kiswahili. The menu offers: my cover; pay premium (full balance or an
  instalment); payouts (from milestone 7); language; help. Enrolment stays with the SACCO
  officer, who reads the consent statements aloud. Each screen is at most 182 characters.
- **M-Pesa** premium collection through Daraja STK push. A push can be started by an officer
  from the member page or by the farmer over USSD, and Safaricom posts the result to
  `POST /mpesa/callback/<CALLBACK_TOKEN>`. The callback is credited only if all of these hold:
  - it matches a push we sent, and its amount equals the amount requested;
  - each receipt is credited once;
  - outside simulated mode, an STK query confirms it first.
- **M-Pesa re-check** (`agroshield-portal mpesa-recheck`; also inside `serve` every `MPESA_RECHECK_SECONDS`, and in
  `daily`): every push with no final answer is queried again 2, 5, 15, 60, 240 and 1,440 minutes after it was sent.
  Confirmed: credited. Refused: failed. Still unknown after the last check: shown on the officer's Home and the
  manager's Reports as "Payment not confirmed: check with the farmer" until a manager records paid (with the
  receipt from the farmer's SMS) or not paid. A payment started before the sales close counts toward cover even if
  it is confirmed after it, and the daily job does not lapse a policy while such a payment is unresolved.
- **M-Pesa modes:** `MPESA_ENV=simulated` (the default) needs no keys and no network. Requests
  are completed from the portal's *M-Pesa simulator* page. `sandbox` uses the Daraja sandbox
  and needs your Daraja app keys and a public https callback URL.
- **SACCO deductions** are recorded by officers as instalments.
- **SMS** in the farmer's language, from `locales/en.yaml` and `locales/sw.yaml`, at most
  160 GSM-7 characters each (tested). Messages cover: enrolled, payment received, cover
  active, reminders 7 days and 1 day before close, cover not started, late payment, and
  overpayment.
  - They are sent only to farmers whose SMS consent is yes, through an outbox. The phone is
    decrypted at send time only.
  - `SMS_MODE=log` (the default) records messages without sending them; `sandbox` or `live`
    sends through Africa's Talking.
  - The Kiswahili text is pending native-speaker review.
  - Weather advisories are not sent: there is no KMD permission.

Database schema: managed by Alembic migrations (`src/agroshield_platform/migrations`). Every start brings the
database to the newest revision in place, after copying a SQLite file to `<name>.pre-<revision>.bak`; nothing is
reset. A database from before migrations (30 October 2026) is recognised and upgraded. `agroshield-portal db-status`
shows the revision; `alembic.ini` is there for hand work. A model change needs a new revision
(`alembic revision --autogenerate -m "..."`): `tests/test_migrations.py` fails until the two match.

### API keys

Put keys in a local `.env` in the repo root (git-ignored; copy `.env.example`). Real
environment variables always win. **Never paste a key into a chat, an issue or a commit.**
`ANTHROPIC_API_KEY` is reserved for the photo rider (milestone 8). It will assist human
reviewers with crop-photo triage, and reviewers keep the decision. Layer B payouts, triggers
and prices never depend on a language model, so they stay reproducible and auditable.

## Monitoring, payouts and weather (milestone 7)

- **Daily ward monitoring** (`agroshield_pricing/monitor.py`, `agroshield-portal monitor` and `daily`).
  - Runs the same `season_wrsi` the prices come from, on observed CHIRPS up to the latest day, with each ward's
    climatology (all other years) for the rest of the season.
  - A failed onset is confirmed at the end of the planting window; a germination dry spell after its 20-day
    check; the WRSI payout at the end of the growing period. Before that everything is a labelled projection.
  - A test checks that the season's own later rain never changes a mid-season result (no look-ahead).
  - Every run is stored (`ward_status`) and audited with the index version, the config hash and a SHA-256 of
    the rainfall it used.
  - CHIRPS final rainfall lags by about three weeks, so the 10-day payout clock starts when the index is
    confirmed, not when the rain fell.
- **Payouts** come only from confirmed triggers, and only for cover that was active (fully paid by sales close).
  - Drought payouts and failed-onset payouts are a share of sum insured, capped at the cover. Replanting seed
    vouchers have a code.
  - They are due within 10 days (`monitoring.payout_within_days`) and go to M-Pesa (simulated B2C until the
    insurer's initiator credentials exist) or to the SACCO loan when loan-linked.
  - Farmers get SMS when a payout is calculated and when it is paid.
- **Payout Tracker** (`/payouts`): each ward's status in plain words, payouts and their due dates, late flags,
  "Pay now" for managers, and technical detail under Details.
- **Missed-payout reports** (the basis-risk channel): farmers use USSD option 5 ("Report crop loss"); officers
  use the member page.
  - Each report snapshots the ward status, is reviewed by a manager with an outcome, and never changes a payout.
- **Weather advisories** (`config/weather.yaml`, `/weather`) are display only. Pricing, monitoring and payouts
  never import the weather module (tested).
  - KMD Nakuru county forecasts are fetched politely: identifying User-Agent, robots.txt checked on every run,
    at most once per URL every 6 hours, every request logged, PDFs stored by SHA-256 with their validity dates.
  - A manual PDF upload is the fallback.
  - An item shows on officers' Home only after a manager writes and approves English and Kiswahili summaries,
    and it disappears after its validity date.
  - No automatic sends, and no SMS of KMD content until written permission is on file
    (`sms_distribution_allowed: false`).
  - Tuko and Kenya News Agency stay off and are never contacted.
- **Demo:** `agroshield-portal demo` adds a labelled **replay** of the 2008 long rains at Ward A, a real drought
  in the CHIRPS record (final WRSI 67.6, 41% payout), so the tracker has something to show.

## Underwriter workspace (milestone 7)

The underwriter is the paying customer; SACCOs are distribution. An `Insurer` underwrites one or more SACCOs, and
each policy records its insurer at sale. The `underwriter` role belongs to one insurer, sees every SACCO's policies
for that insurer and never another insurer's book (tested). SACCO users cannot open the workspace, and
underwriters are kept out of SACCO pages.

| Page | What |
|---|---|
| `/uw` Portfolio | KPI strip; charts of exposure by ward, premium by month and payout events; season and SACCO filters; tables by SACCO, ward and season; exposure concentration (largest single-ward loss if the index fully triggers); aggregated CSV |
| `/uw/triggers` | WRSI and trigger status per ward; payouts waiting for approval; approve or hold with a reason (audited); the 10-day clock per event |
| `/uw/money` | Farmer premium received (M-Pesa and SACCO deductions), outstanding, KAIP receivable ("not yet received"), refunds owed, payouts; premium settlement by SACCO (collected, remitted, confirmed, outstanding), confirm or query each remittance, CSV |
| `/uw/bordereaux` | Monthly premium and payout bordereaux: ZIP of masked CSVs plus `manifest.json` with SHA-256 and row counts; exports audited |
| `/uw/pricing` | Engine runs (index version, config hashes, links to the HTML reports), the run audit log, trigger and payout audit for its own policies |
| `/uw/reinsurer` | One page: portfolio, exposure by ward, expected loss and 1-in-10 / 1-in-20 annual loss (as-if, from the engine's 1981-2025 seasons), ESG/TCFD reporting (never pricing) |

Payouts now wait for the underwriter: calculated, then approved (cash) or issued (seed voucher), then paid. A held
payout carries its reason. Farmers are told about a payout only once it is approved, and SACCO managers can pay only
approved payouts. Set up with `agroshield-portal add-insurer`, `add-sacco --insurer`, `add-officer --insurer ...
--role underwriter`. The demo adds `demo-underwriter`. Screenshots: `docs/screenshots/m7/index.html`.

## Public site and premium settlement (overnight work, 29 to 30 Oct 2026)

- **Public site**: Home, Crops, Livestock (in development, not quotable), How it works, For insurers, For SACCOs, Learn
  (eight articles with sources, glossary in English and Kiswahili pending native-speaker review), Questions, Credits and
  Request a demo. Photos are openly licensed Wikimedia Commons files, self-hosted (`tools/fetch_images.py`,
  `docs/design/IMAGE_CREDITS.md`). The two public forms store to the local database only, encrypted, and nothing is
  emailed; list or delete them with `agroshield-portal enquiries`.
- **Premium settlement**: a SACCO manager records premium sent to the insurer at `/reports/premium`; the underwriter
  confirms or queries it on `/uw/money`. A ledger only, audited, never edited (a correction is a negative entry).
  "Collected" is gross premium received. Refunds owed to farmers and refunds paid (recorded by a manager on the member
  page) are tracked separately and never netted. SACCOs remit gross, with no fee deducted first, to the insurer's
  premium paybill: `agroshield-portal set-paybill --insurer CODE --paybill "..."` (audited; until set, screens say
  "the insurer's paybill (to be configured)"). These three rules are pending owner confirmation
  (`docs/DECISIONS_LOG.md`).
- **Weather advisories by scope**: a SACCO manager uploads and approves advisories for their own SACCO only. Advisories
  shown to every SACCO (KMD fetches, and uploads by operations) belong to AgroShield operations staff:
  `agroshield-portal add-officer --username ops1 --name "..." --role ops`. Operations staff see only `/weather`.
- **HTTPS**: set `AGROSHIELD_HTTPS=true` when the portal runs over HTTPS (directly or behind a TLS proxy such as nginx
  or Caddy); session cookies are then Secure as well as HttpOnly and SameSite=Lax.
- **Design system**: `static/tokens.css` (light and dark), `static/app.css`, `static/nav.js`; see `docs/design/THEME.md`.
- **Running in production**: schedule `agroshield-portal daily` once a day (for example 06:00 Africa/Nairobi, by cron or
  Task Scheduler). It re-checks M-Pesa payments, closes sales windows and lapses unpaid cover, sends reminders, runs ward
  monitoring (which creates payouts once a trigger is confirmed) and sends queued SMS. Without it, cover never lapses
  and no payout is calculated. If `serve` runs with `MPESA_RECHECK_SECONDS=0`, schedule `agroshield-portal
  mpesa-recheck` every 5 minutes instead.
- Overnight QA, review and morning report: `docs/overnight/`.

## Crop photo app (milestone 8, remaining brief 1 to 3 Nov 2026)

- **For farmers and champion farmers**: an installable web app at `/app` (works offline; photos wait on the phone and
  send when there is signal). The SACCO officer sets it up on the member page (PIN shown once). The camera shows the
  last photo from the same spot faintly, to keep the framing.
- **Checks on every photo**: refused if taken more than 250 m from the farm; flagged if it is the same picture as one
  sent before (perceptual hash), if the camera's time or GPS disagrees with the app's, if the GPS fix is weak, or if
  it was taken long before it was sent. The stored file has no EXIF or GPS in it.
- **Review**: underwriters (the insurer's agronomists) review at `/uw/photos`: tag and how much of the plot is
  affected. They decide; an AI "Suggestion" appears only when the farmer agreed to AI photo checks (a separate consent,
  pending legal review), and only the stripped picture is sent. With no `ANTHROPIC_API_KEY` the queue works without it.
- **After review** the farmer gets a short advice SMS (with SMS consent; recorded, not sent in development).
- **Resilience Score**: the "photos on schedule" point is earned when every growth stage was photographed in its window
  with clean checks, and applies to the next season.
- **Weather tab** in the app: approved KMD summaries in English and Kiswahili, labelled "Source: KMD". No SMS.
- **Picture-based rider**: damage report and assessment built, ILLUSTRATIVE, switched off in quotes.
- Settings: `config/photo.yaml` (not part of pricing). Demo: phone 0712 000 001, PIN 246810 (fictional farmer).

## Research (task 3b: forecast skill)

`research/` holds analysis that informs the product but is not part of the pricing
package. Run in order:

```bash
.venv/Scripts/python research/fetch_data.py          # C3S hindcasts, GHACOF outlooks, eastern Kenya CHIRPS
.venv/Scripts/python research/fetch_data.py c3s-neighbours
.venv/Scripts/python research/early_trigger.py       # CHIRPS-GEFS at each check day + prototype
.venv/Scripts/python research/report_3b.py           # -> docs/research/3b-forecast-skill.html
.venv/Scripts/python research/advance.py             # EXPERIMENTAL advance: LOOCV and pricing
.venv/Scripts/python research/short_rains.py fetch   # short-rains candidates: CHIRPS, NASA POWER, C3S
.venv/Scripts/python research/short_rains.py run
.venv/Scripts/python research/report_advance_sr.py   # -> docs/research/advance-and-short-rains.html
```

Short-rains candidates near Mbooni and Kitui are research cells with their own generated
config in `research/short_rains/`; they are **not** pilot wards and `config/` is unchanged.

Sources: C3S ECMWF SEAS5.1 hindcasts through the IRI Data Library (download URLs need no
login), GHACOF consensus outlooks from the ICPAC geoportal (GeoServer WFS point queries),
CHIRPS-GEFS 15-day forecasts from the Climate Hazards Center (byte-range reads of 9
pixels per file), CHIRPS monthly from IRI. Inputs are cached in `data/raw/research/`
with URLs and checksums.

## Validation status

- **FEWS NET WRSI comparison: pending.** The USGS "CHIRPS Croplands WRSI, Apr-Nov long
  rains, grains" product and FEWS NET daily PET are hosted on a server that returned
  503 on 2026-10-28. Drop end-of-season values in `data/raw/fewsnet_wrsi/<ward>_LR.csv`
  (`year,eos_wrsi`) and the next run reports correlation and large gaps.
- **Basis risk: not measurable** until real ward yields exist
  (`data/raw/yields/<ward>_LR.csv`, `year,yield_t_per_ha`). Rainfall-derived synthetic
  yields were dropped: they agree with a rainfall index by construction.

## Configuration

Everything that drives a price is in `config/`. Changing a ward, planting window,
growing period, soil, trigger, loading or sum insured is a config edit, never a code change.

| File | Holds |
|---|---|
| `pilot.yaml` | County, crop, pilot wards, rainfall and PET sources, history window, validation inputs |
| `wards.yaml` | Insurance units: centroid, extraction box, elevation, soil water capacity, seasons offered |
| `phenology.yaml` | Planting window, variety and growing period per ward and season (plus v0's fixed phases) |
| `product.yaml` | WRSI terms (Kc, onset rule, trigger, exit, failed-onset payout, overrides), target frequency, event tests, v0 terms, sum insured, risk margin and loadings |

The config is validated on load, so a bad edit fails loudly instead of mispricing.

## Data and provenance

Every input carries a label, shown at the top of every report and in `results.json`:
**REAL** (observed, named source), **SYNTHETIC** (generated here), **ILLUSTRATIVE**
(placeholder awaiting a decision) or **PENDING** (not available; dependent results not
computed).

- **Rainfall:** CHIRPS v2.0 daily, averaged over a 0.10 degree box around each ward
  centroid, from SERVIR ClimateSERV. Committed in `data/raw/chirps/`.
- **PET:** FAO-56 Hargreaves from NASA POWER daily Tmax/Tmin, shifted from the POWER
  grid-cell elevation to the ward's (6.5 C/km). A fallback for FEWS NET Penman-Monteith
  PET, which was unreachable and only starts in 2001. Committed in `data/raw/nasapower/`.

Each raw file has a `.meta.json` with the exact request, retrieval time and SHA-256; a
changed file or a moved ward is refused until re-fetched. `.gitattributes` pins LF line
endings so the hashes hold on every checkout.

## Reproducibility and audit

Each run writes `manifest.json` (code version and git commit, index versions, SHA-256 of
every config file, both raw inputs and `results.json`) and appends one line to the
committed `runs/audit_log.jsonl`. Identical inputs give an identical `results.json`.
`layer_b.version` must be bumped on any change to the index rules.

## Layout

```
config/                  product and pilot settings (YAML)
data/raw/                committed CHIRPS and NASA POWER inputs + metadata and checksums
src/agroshield_pricing/
  config.py              load + validate config
  provenance.py          REAL / SYNTHETIC / ILLUSTRATIVE / PENDING labels
  rainfall/              CHIRPS (ClimateSERV) loader, synthetic generator
  pet/                   Hargreaves, NASA POWER loader, synthetic PET
  wrsi.py                v1: dekads, onset and germination triggers, Kc, water balance, WRSI payout
  layer_a.py             Layer A: synthetic tercile forecast, verification scores, voucher pricing
  index.py, phenology.py v0 per-phase index (comparison only)
  burn.py, premium.py    burn cost and gross premium
  validation.py          FEWS NET comparison, real-yield basis risk
  backtest.py            yield backtest metrics (used once real yields exist)
  engine.py              prices one ward, v1 with v0 alongside
  report.py, svgcharts.py, templates/report.html   HTML report (inline SVG)
  audit.py, cli.py       run manifest, audit log, command line
src/agroshield_platform/
  settings.py, crypto.py keys from the environment; encryption, masking, log scrubbing, passwords
  models.py, db.py       SACCO, officer, farmer, plot, consent, policy, KIAMIS, audit tables
  services.py            enrolment, bulk CSV, portfolio, export
  monitoring.py          daily ward monitoring, payouts (approve, hold, pay), missed-payout reports
  underwriting.py        the insurer's workspace: portfolio, triggers, money, bordereaux, reinsurer summary
  settlement.py          SACCO-to-insurer premium settlement ledger (records only; moves no money)
  enquiries.py           public-site forms, stored locally and encrypted; nothing is emailed
  content.py, articles.json   Learn articles (each claim with a source)
  csvsafe.py             CSV exports that cannot run as spreadsheet formulas
  weather.py             KMD advisories (display only, polite fetch rules)
  kiamis.py              KIAMIS adapter (not connected / CSV import)
  web/                   portal routes, templates, CSS
  locale.py, sms.py      English and Kiswahili strings (locales/); SMS outbox and senders
  mpesa.py, ussd.py      Daraja STK push and callbacks; USSD menu
  cli.py                 agroshield-portal
tests/                   payout functions, WRSI, onset, PET, burn cost, premium, config,
                         data integrity, validation, regression, end to end
docs/                    BORROWED_FROM_MVP.md: ideas taken from the old demo, by milestone
```

## Open questions

- Which Nakuru wards for the pilot (currently two labelled placeholders), and their soils.
- Underwriter partner: loadings, margin, target payout frequency, Resilience discount cap.
- Real ward yields and KIAMIS access (manual CSV import for now).
- Legal and Kiswahili review of the consent text, USSD menus and SMS.
- Daraja app keys and a public callback URL for the M-Pesa sandbox; an Africa's Talking
  account and USSD code; the SACCO paybill or till.
- GSM or LoRa for the Sentinel camera pilot; picture-based rider in v1 or v2.
