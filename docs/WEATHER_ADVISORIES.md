# Weather News and Advisories: plan and pre-build checks

**Display only.** Nothing in this module is ever read by pricing, triggers or payouts.
A test will assert that the pricing, trigger and payout packages do not import it.

**Status:** planned, not built. It is scheduled below and waits for milestone 3 approval.

## Pre-build checks (2026-10-28)

### KMD county forecasts (primary)

- `https://meteo.go.ke/robots.txt` returns **404**: the site declares no crawl rules.
  We still behave as if it did: an identifying User-Agent with contact details, at most one
  fetch per product every 6 hours, a local cache, and a back-off on errors.
- The site footer has no terms-of-use or copyright page.
- **Decision (2026-10-28): no SMS distribution of KMD content until we hold written
  permission from KMD.** The portal and farmer app may display KMD items with
  "Source: KMD" and a link; the SMS step stays disabled by a config switch
  (`sms_distribution_allowed: false`) that the code checks before every send.
- `https://meteo.go.ke/our-products/county-forecasts/` lists per-county pages. The Nakuru
  weekly forecast page links its PDF directly, e.g.
  `/documents/5450/Nakuru_County_weekly_weather_forecast_valid_27th__October_to_2nd_November_2026.pdf`.
  Validity dates appear in the page slug and file name.

### Tuko news headlines (secondary): stopped, as instructed

- Tuko publishes RSS: `https://www.tuko.co.ke/rss/all.rss` and `/rss/kenya.rss` (HTTP 200,
  XML). `robots.txt` does not disallow `/rss/`.
- Its terms (`https://www.tuko.co.ke/terms-and-conditions/`) do **not** allow our use:
  - the licence is "solely for your personal, non-commercial purposes";
  - users may not "access the Service through automated or non-human means, whether through
    a bot, script or otherwise";
  - users may not "systematically retrieve data or other content from the Service to create
    or compile ... a collection ... without written permission from us";
  - users may not "use the Service for any revenue generating endeavor, commercial enterprise".
  RSS is not exempted anywhere in the terms.
- **Result:** not built, and stays off (decision 2026-10-28). It would need written permission
  from Tuko (Legit Media) covering automated feed reading and showing headline, source, date
  and link in a commercial product.

### Kenya News Agency (checked 2026-10-28): terms unclear, not built

- Site `https://www.kenyanews.go.ke/` (government agency). Reachable only with Windows TLS from
  this machine; curl's TLS handshake failed.
- `robots.txt` disallows only `/wp-admin/`. An RSS feed exists at `/feed/` (WordPress, hourly).
  Item dates look correct, but the channel's `lastBuildDate` reads 29 Sep **2029**, so feed
  metadata cannot be trusted blindly.
- **No terms of use are published.** The "Disclaimer" and "Privacy Policy" pages both say
  "SORRY! This page is still under construction."
- The site offers a paid **"Subscription for KNA content"** e-service, which suggests KNA
  licenses its content.
- **Result:** terms are unclear, so not built. Ask KNA in writing whether showing headline,
  source, date and link (no full text, no images) in the portal and farmer app is allowed
  without a subscription.

## What gets built, by milestone

| Piece | Milestone |
|---|---|
| KMD fetcher: polite scraper (User-Agent, 6-hour minimum interval, cache, robots check on every run), PDF download with SHA-256 and validity dates, text extraction, manual PDF upload fallback when parsing fails | 7 (monitoring jobs) |
| Advisory review queue: an officer writes or edits a short English and Kiswahili summary and **approves** it before any SMS; no automatic sends; every approval is in the audit log. SMS sending stays disabled until KMD's written permission is on file | 7 (with SMS notifications) |
| News source list in config (`sources: [{name, rss_url, terms_checked_on, allowed}]`), keyword filter for weather and agriculture, headline/source/date/link only, no full text or images unless a source's terms allow it | 7, but only for sources whose terms are cleared |
| SACCO officer portal "Weather" panel, every item labelled "Source: KMD" (or the news source) with a link | 7 (portal from milestone 5) |
| Farmer app "Weather" tab, same labels | 8 (farmer app) |

## Tests planned

- The PDF parser against saved sample KMD PDFs (committed as fixtures with their checksums).
- The keyword filter on sample headlines.
- Stale-item expiry: an advisory disappears from every view after its validity end date.
- The fetcher never calls the same KMD URL twice within 6 hours.
- No SMS leaves without an approved summary.
- The pricing, trigger and payout code never imports this module.
