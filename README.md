# ShambaShield 360 & ShambaRecon

A pitch-ready prototype for a Kenyan mixed-farm (crop and livestock) parametric insurance calculating agent, with
automated SACCO reconciliation. One Streamlit app, three tabs:

1. **Reinsurer backtest engine.** Ten years (2015-2024) of daily weather for five pilot wards, three payout layers
   (crop inputs, fodder gap, vet and health) under a seasonal cap, burn cost, zone pricing to a target loss ratio,
   worst year, and a basis-risk check with and without the WhatsApp verification step.
2. **SACCO reconciliation matcher.** Matches a messy M-Pesa paybill statement to SACCO members (exact, then fuzzy),
   allocates every shilling by waterfall (the ward's premium, then overdue interest, then principal or savings), and exports
   the underwriter bordereau and a 70/30 claim-split settlement.
3. **WhatsApp trust loop and unit economics.** When a ward's VCI sits in the 35% to 40% amber zone, lead farmers
   and agro-vets send geotagged photos for KSh 100 airtime; 60% agreement unlocks the payout. Plus a pilot revenue
   calculator for the platform, the insurer and the reinsurer.

No API keys are needed. The weather is cached in the repo, so the demo runs offline.

## Run it

Python 3.11 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS or Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tests (69, including a headless run of the whole app that presses every button):

```
pip install -r requirements-dev.txt
pytest
```

## Five-step demo for a reinsurer or a SACCO CEO

1. **Backtest, a known drought.** Pick *Kangundo, Machakos County*. Point at the payout bars, then the trajectory
   chart: long rains 2022 (drought) against 2020 (very wet). The soil moisture line drops below the crop trigger
   through flowering in 2022 and stays well above normal in 2020.
2. **Price it live.** Show the zone pricing table: the same terms priced per ward to a 60% target loss ratio.
   Move the target, the soil moisture trigger or the subsidy in the sidebar and watch the premium, burn cost and
   basis-risk score respond. Switch to *One flat rate* to show why a single national rate does not work.
3. **Clear the suspense account.** On the SACCO tab press *Run automated reconciliation*. Each member owes their
   ward's premium. The unallocated suspense rate drops from about 39% (an exact lookup) to under 3%, twelve
   duplicate rows are held instead of credited
   twice, and every credited row lands on the right member. Filter the ledger by *Spouse Name Match* or
   *Fuzzy Reference* to show how.
4. **Pay a claim through the SACCO.** Download the bordereau, then *Simulate drought payout* for Kangundo: 70% to
   the farmer by M-Pesa B2C, 30% to the member's loan, never more than they owe.
5. **Settle a grey-zone reading on the ground.** On the last tab keep VCI at 36.5% (amber), press
   *Simulate 12 farmer geotagged submissions*, and watch the ward flip from AMBER (HOLD) to RED (PAYOUT UNLOCKED).
   Finish on the unit economics: founder revenue per season and per year, and the insurer and reinsurer split.

## What is real and what is not

| Item | Status |
|---|---|
| Daily rainfall, reference ET (FAO-56) and maximum temperature | **Real**: Open-Meteo Historical Weather API (ERA5-based reanalysis), CC BY 4.0, cached in `data/weather_cache/` with request URL, grid cell and retrieval date |
| Soil moisture index and pasture NDVI | **Synthetic proxies** computed from that weather (a root-zone water balance; the index is relative to each ward's own record, 50 = normal). They stand in for Sentinel-1 SAR and Sentinel-2 until real satellite feeds are connected |
| WRSI used for the basis-risk check | Model output from the same water balance (FAO maize crop curve); not yields |
| SACCO members, M-Pesa payments, verifiers, photos | **Synthetic and fictional**, fixed seed; phone numbers and national IDs are masked on screen and in exports |
| Sums insured, sub-limits, cap, target loss ratio, triggers, fees, 70/30 split | **Illustrative**: need actuarial sign-off, the partner insurer's agreement and IRA approval |
| Subsidy slider | Shows what a farmer would pay under a subsidy; **no subsidy is agreed** |
| Basis-risk score "with check" | A scenario: **assumes** the WhatsApp photos settle a set share of close seasons correctly |
| Insurer | "Partner insurer (to be named)" |

If there is no cache and no network, the app falls back to clearly labelled synthetic weather. *Refresh weather from
Open-Meteo* in the sidebar downloads the record again and updates the cache (`python -m engine.parametric_engine`
does the same for all five wards).

## Product terms (version 2, ILLUSTRATIVE)

- Sum insured KSh 60,000 per farm per season: sub-limits KSh 30,000 crop inputs, KSh 20,000 fodder, KSh 10,000
  vet and health, with a KSh 50,000 cap across all three in one season.
- Crop: soil moisture index (50 = normal) weighted 35% germination and 65% flowering; pays 25% at 32, rising to
  100% at 12.
- Fodder: only after a severe crop loss (crop payout at least 50% of its limit) and when pasture greenness from
  day 61 is below the ward's 25th percentile.
- Vet and health: KSh 10,000 when the wettest 10 days pass the ward's own 90th percentile line, or after 7 days
  above 31 deg C.
- Price: each ward's burn cost divided by a 60% target loss ratio, rounded up to 0.1%.
- Sellable ceiling: a ward priced above 12% is **not offered** the standard bundle. Its members owe no premium, their
  money goes to loans and savings, and they stay out of the bordereau and the claim split.

## Why Bureti is not offered (an underwriting decision, not a gap)

On 2015-2024, Bureti (Kericho, wet tea-dairy highland) prices at 17.9% (KSh 10,740 a season) on the standard
bundle: the soil moisture index reads relative dryness against a very wet normal, so the crop layer pays 4 seasons in
20 even though the maize water-satisfaction index (WRSI) never fell below 60 there. The engine flags it instead of
selling it at a price farmers will not pay or hiding it inside a flat national rate.

A dairy-and-excess-rain tier without the maize layer (KSh 20,000 fodder plus KSh 10,000 vet and health) was tested
and does not fix it: KSh 4,900 to 7,900 a season for KSh 30,000 of cover (16% to 26%), because a pasture trigger set at
a percentile of the ward's own record fires 2 to 4 seasons in 20 in every ward, Bureti included. A highland tier
needs data the proxies cannot give: milk volumes from dairy co-operatives or green-leaf deliveries from tea
factories, to price yield-linked or area-yield cover. Frost and hail are not in ERA5-class weather data.

## Layout

```
app.py                       dashboard shell, header and tabs
engine/parametric_engine.py  Open-Meteo fetch and cache, water balance, indices, payout layers, KPIs
engine/recon_engine.py       phone and reference cleaning, RapidFuzz matcher, waterfall, bordereau, claim split
engine/whatsapp_simulator.py amber-zone state machine, verifier network, simulated photos
engine/unit_economics.py     pilot revenue and premium split
data/seed_generator.py       500 members and a 520-row paybill statement with ground truth
data/weather_cache/          five wards, 2015-2024, with .meta.json
ui/                          one module per tab, plus theme.py (colours, CSS, KPI cards)
tests/                       engine tests and a headless app test
```

## Before real money moves

- Real SAR soil moisture and NDVI in place of the proxies, and a longer record than 2015-2024 before pricing.
- A highland tea-dairy tier for Bureti built on co-operative milk or tea-leaf records (see above).
- Basis-risk testing against SACCO yield or loan-default records.
- Members' written consent to send part of a claim to their loan, and to share data (Data Protection Act, 2019).
- Live rails: M-Pesa Daraja C2B and B2C, WhatsApp Business Cloud API, the SACCO core banking export.

The earlier AgroShield platform (FastAPI, CHIRPS pricing engine, IRA pack) is kept in git: tag
`archive/agroshield-v1` and branch `archive/agroshield`.
