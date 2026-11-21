# ShambaShield360

App ID `shambashield360`, version 2.0.0.

A pitch-ready prototype for a Kenyan mixed-farm (crop and livestock) parametric insurance calculating agent, with
automated SACCO reconciliation (ShambaRecon). The app tells one story in four chapters, each opening with the sentence
its numbers support:

1. **The risk.** Ten years (2015-2024) of daily weather for five pilot wards, three payout layers (crop inputs,
   fodder gap, vet and health) under a seasonal cap, burn cost, zone pricing to a target loss ratio with a sellable
   ceiling, worst year and a basis-risk check.
2. **A farmer's quote.** Ward, season, acres of maize and dairy cows, and last season's verified practices give the
   price: gross premium, any government share, the Resilience discount, what the farmer pays (also per day of milk
   check-off), who pays the insurer, what the cover would have paid on past weather, and what happens when it pays.
   Downloadable as text with a quote ID.
3. **Collecting the money.** Matches a messy M-Pesa paybill statement to SACCO members (exact, then fuzzy),
   allocates every shilling by waterfall (the ward's premium, then overdue interest, then principal or savings), and
   exports the underwriter bordereau and a 70/30 claim-split settlement.
4. **Trust and the numbers.** When a ward's VCI sits in the 35% to 40% amber zone, lead farmers and agro-vets send
   geotagged photos for KSh 100 airtime; 60% agreement unlocks the payout. Plus a pilot calculator for the platform,
   the insurer and the reinsurer.

No API keys are needed. The weather and the typeface (IBM Plex) ship with the repo, so the demo runs offline.

## Run it

Python 3.11 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS or Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tests (243, including a headless run of the whole app that presses every button, a sweep of 30 random product
settings, 60 random farm quotes, money-conservation checks on several synthetic statements, and adversarial matcher tests):

```
pip install -r requirements-dev.txt
pytest
```

## Five-step demo for a reinsurer or a SACCO CEO

1. **Backtest, a known drought.** In chapter 1, pick *Kangundo, Machakos County*. Point at the payout bars, then the trajectory
   chart: long rains 2022 (drought) against 2020 (very wet). In 2022 the soil moisture index sits below the crop
   trigger through the whole flowering window; in 2020 it stays well above normal.
2. **Price it live.** In chapter 1, show the zone pricing table: the same terms priced per ward to a 60% target loss ratio.
   Bureti is flagged *not offered* at the 12% ceiling. Drag the ceiling to 18% and it unlocks across the pricing
   table and, after a re-run, the reconciliation. Switch to *One flat rate* to show why a single national rate fails.
3. **Clear the suspense account.** In chapter 3 press *Run reconciliation*. Each member owes their ward's
   premium. The unallocated share of rows drops from about 39% (an exact lookup) to about 4%, twelve duplicate
   rows are held instead of credited twice, and on this demo statement every credited row lands on the right member.
   Filter the ledger by *Spouse Name Match* or *Fuzzy Reference* to show how.
4. **Quote one farm, then pay its claim.** In chapter 2, quote a Njoro farm (2 acres, 2 cows: KSh 5,160 a
   season, about KSh 57 a day of milk check-off) and tick a practice to show the Resilience discount. Then, in chapter
   3, download the bordereau and *Simulate payout* for Kangundo: 70% to the
   farmer by M-Pesa, 30% to the member's loan, never more than they owe.
5. **Settle a grey-zone reading on the ground.** In chapter 4 keep VCI at 36.5% (amber), press
   *Simulate 12 photo replies*, and watch the ward flip from AMBER (HOLD) to RED (PAYOUT UNLOCKED). Finish on the
   unit economics: platform revenue, and how a season's premium splits between the platform, insurer and reinsurer.

## The quote (chapter 2)

Cover follows the farm. The standard farm (2 acres of maize, 2 dairy cows) gets the product's sum insured: KSh 60,000 by
default, which is KSh 15,000 of crop inputs per acre and KSh 10,000 of fodder plus KSh 5,000 of vet and health cover
per cow. Change the sum insured in the sidebar and every per-acre and per-cow amount scales with it, so a standard
farm's quote always equals its ward's price in the zone table, with the cap from chapter 1's terms. Other farms are priced by the same engine on
their own mix. Then, as in AgroShield:

- **Gross premium** = sum insured x the farm's rate (the risk price; nothing below changes it).
- **Government share** = the sidebar subsidy x gross, only for farms of 0.5 to 20 acres. No subsidy is agreed.
- **Resilience discount** = 1% of the farmer's share per point, capped at 15%: certified seed (5), crop photos at every
  stage (4), stored hay or silage (3), full or partial irrigation (3 or 2, only the higher counts), SACCO member in good
  standing (2). The platform pays it out of its fee (the sidebar's platform fee, 10% by default); the quote and its
  text copy warn when the discount is larger than that fee.
- **Farmer pays** = farmer share - discount. For a farm with cows, that divided by 90 is shown as a daily milk
  check-off.
- Money is whole shillings, rounded half up from exact decimals.
- Enrolment closes 14 days before the season window (15 February 2027 for the long rains). No quote is given for a
  ward that is not offered, for a farm whose own mix prices above the sellable ceiling (a dairy-only farm can), or for
  a farm outside 0 to 20 acres and 0 to 20 cows. The quote ID fingerprints the quote's content (farm, cover, price and
  the payout history behind it), so the same quote always gets the same ID and any change gets a new one.

## What is real and what is not

| Item | Status |
|---|---|
| Daily rainfall, reference ET (FAO-56) and maximum temperature | **Real**: Open-Meteo Historical Weather API (ERA5-based reanalysis), CC BY 4.0, cached in `data/weather_cache/` with request URL, grid cell and retrieval date |
| Soil moisture index and pasture NDVI | **Synthetic proxies** computed from that weather (a root-zone water balance; the index is relative to each ward's own record, 50 = normal). They stand in for Sentinel-1 SAR and Sentinel-2 until real satellite feeds are connected |
| WRSI used for the basis-risk check | Model output from the same water balance (FAO maize crop curve); not yields |
| SACCO members, M-Pesa payments, verifiers, photos | **Synthetic and fictional**, fixed seed; phone numbers and national IDs are masked on screen and in exports |
| Sums insured, sub-limits, cap, target loss ratio, ceiling, triggers, fees, 70/30 split | **Illustrative**: need actuarial sign-off, the partner insurer's agreement and IRA approval |
| Subsidy slider | Shows what a farmer would pay under a subsidy; **no subsidy is agreed** |
| Basis-risk score "with check" | A scenario: seasons within 5 points of the soil moisture trigger are assumed to go to a photo check that settles a set share (default 80%) correctly. The trust-loop tab demonstrates the photo loop on a VCI reading; no VCI is computed in the backtest |
| Insurer | "Partner insurer (to be named)" |

If there is no cache and no network, the app falls back to clearly labelled synthetic weather. *Refresh weather from
Open-Meteo* (sidebar, *More settings*) downloads the record again and updates the cache
(`python -m engine.parametric_engine` does the same for all five wards).

## Product terms (version 2, ILLUSTRATIVE)

- Sum insured KSh 60,000 per farm per season: sub-limits KSh 30,000 crop inputs, KSh 20,000 fodder, KSh 10,000
  vet and health, with a KSh 50,000 cap across all three in one season.
- Crop: soil moisture index (50 = normal) weighted 35% germination and 65% flowering; once it falls below 32 it pays
  25%, rising in a straight line to 100% at 12.
- Fodder: only after a severe crop loss (crop payout at least 50% of its limit) and when pasture greenness from
  day 61 is below the ward's 25th percentile.
- Vet and health: KSh 10,000 when the wettest 10 days pass the ward's own 90th percentile line, or after 7 days in a
  row above 31 deg C.
- Price: each ward's burn cost divided by a 60% target loss ratio, rounded up to 0.1%, and never below 1% (ten
  seasons without a payout do not make the cover free). On 2015-2024 that gives Njoro
  8.6%, Kangundo 9.8%, Kimilili 10.0%, Imenti North 11.3% and Bureti 17.9%.
- Sellable ceiling: a ward priced above 12% is **not offered** the standard bundle. Its members owe no premium, their
  money goes to loans and savings, and they stay out of the bordereau and the claim split.

## Why Bureti is not offered (an underwriting decision, not a gap)

On 2015-2024, Bureti (Kericho, wet tea-dairy highland) prices at 17.9% (KSh 10,740 a season) on the standard
bundle: the soil moisture index reads relative dryness against a very wet normal, so the crop layer pays 4 seasons in
20 even though the maize water-satisfaction index (WRSI) never fell below 60 there (its lowest was 60.2). The engine
flags it instead of selling it at a price farmers will not pay or hiding it inside a flat national rate.

A dairy-and-excess-rain tier for Bureti without the maize layer (KSh 20,000 fodder plus KSh 10,000 vet and health)
was tested and does not fix it: roughly KSh 5,000 to 8,000 a season for KSh 30,000 of cover (16% to 26%), depending on the
pasture trigger. A pasture trigger set at a percentile of the ward's own record fires in a fixed share of seasons by
construction (4 in 20 at the 25th percentile, 2 in 20 at the 15th), in a wet ward as in a dry one. A highland tier
needs data the proxies cannot give: milk volumes from dairy co-operatives or green-leaf deliveries from tea
factories, to price yield-linked or area-yield cover. Frost and hail are not in ERA5-class weather data.

## How the matcher protects the money

A wrong credit is worse than a short review queue, so the matcher weighs all the evidence on a payment and sends it to
*Ambiguous (review)* whenever the evidence disagrees:

- A repeated receipt number is held as a duplicate, comparing receipts without case or spaces; a re-export with the
  receipt column blank is caught by matching the whole row. Amounts written as `5,160.00` or `KES 5,160` are read as
  numbers. A blank, zero, negative or unreadable amount is held as *Bad amount (review)*; blank loan or interest cells
  count as none.
- An exact member ID, or a national ID standing alone (not inside a longer number), is the payer's instruction and
  decides on its own. A reference that names two members (`MBR-1001/1002`, the shorthand `MBR-1001/02`, or an ID next
  to another member's national ID) goes to review, and so does a phone or national ID that two members share.
- A mistyped ID (`MBR 1042`, `MBR:1042`, `mbr-1O42-milk`) counts only if it points at one member and neither the
  registered phone, the payer's name nor a name written in the reference points at someone else. The payer's own names
  written in the reference ("FROM PETER") are not someone else. Letter-for-digit repairs happen only inside the
  number: `MBR-104 OTIENO` is a truncated `MBR-104`, not `MBR-1040`. A bare number with no MBR (`1042`) needs the
  phone or the payer's name to agree. A number equal to the amount (`1200` on a KSh 1,200 payment) is read as the
  amount, not an ID, so the member's own phone still decides.
- A transposed ID is caught by the payer's name: if two or more of the payer's names fit another member whose number
  is also close to the reference (`MBR 1103` paid by NJERI MWANGI when she is MBR-1013), it goes to review.
- When a reference fits several members (a truncated `MBR-104` is as close to two dozen member numbers), a tie is
  settled only by a payer name with exactly the words of one candidate's record that no other candidate carries, or,
  when the reference starts with MBR, by a reference that spells exactly one candidate's surname. Close spellings
  (NEKESA for WEKESA) never count.
- With no usable reference, a registered phone decides unless the payer's name, or a name in the reference ("FOR
  OTIENO"), belongs to someone else.
- With only a name, it must have three or more words, in the same order as one member's or spouse's record, and no one
  else may carry all of them. Two names are too common; reversed names can be different people. Known limit: a
  non-member who has exactly a member's three names cannot be told apart from that member.
- Names are compared without case, punctuation or apostrophes (NDUNG'U and NDUNGU are the same).

On 64 synthetic statements, on every member paid with a truncated reference or only a name
(`tests/test_matcher_adversarial.py`), and on the cases in `tests/test_recon.py`, it made no wrong credits (30,856 credited
rows, recall about 97%); about 2.5% of payments go to review.

## Layout

```
app.py                       app shell: top bar, tabs, footer
assets/                      logo (SVG and 256 px PNG)
static/fonts/                IBM Plex Sans and Mono (SIL Open Font License, OFL.txt), served with the app
engine/parametric_engine.py  Open-Meteo fetch and cache, water balance, indices, payout layers, pricing, KPIs
engine/recon_engine.py       phone and reference cleaning, RapidFuzz matcher, waterfall, bordereau, claim split
engine/whatsapp_simulator.py amber-zone state machine, verifier network, simulated photos
engine/unit_economics.py     pilot revenue and premium split
engine/quote.py              farm quotes: cover, price, subsidy, Resilience discount, payment, history
data/seed_generator.py       500 members and a 520-row paybill statement with ground truth
data/weather_cache/          five wards, 2015-2024, with .meta.json
ui/                          one module per tab, brand.py (name, app ID, version, logo) and theme.py
tests/                       engine tests, an invariant sweep and a headless app test
```

## Before real money moves

- Real SAR soil moisture and NDVI in place of the proxies, and a longer record than 2015-2024 before pricing.
- A highland tea-dairy tier for Bureti built on co-operative milk or tea-leaf records (see above).
- Basis-risk testing against SACCO yield or loan-default records.
- Members' written consent to send part of a claim to their loan, and to share data (Data Protection Act, 2019).
- Live rails: M-Pesa Daraja C2B and B2C, WhatsApp Business Cloud API, the SACCO core banking export.

The earlier AgroShield platform (FastAPI, CHIRPS pricing engine, IRA pack) is kept in git: tag
`archive/agroshield-v1` and branch `archive/agroshield`.
