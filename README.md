# ShambaShield 360 & ShambaRecon

A pitch-ready prototype for a Kenyan mixed-farm (crop and livestock) parametric insurance calculating agent, with
automated SACCO reconciliation. One Streamlit app, three tabs:

1. **Reinsurer backtest engine.** Ten years (2015-2024) of daily weather for five pilot wards, three payout layers
   (crop inputs, fodder gap, vet and health), burn cost, loss ratio, worst year and a basis-risk check.
2. **SACCO reconciliation matcher.** Matches a messy M-Pesa paybill statement to SACCO members (exact, then fuzzy),
   allocates every shilling by waterfall (premium, then overdue interest, then principal or savings), and exports
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

Tests (58, including a headless run of the whole app that presses every button):

```
pip install -r requirements-dev.txt
pytest
```

## Five-step demo for a reinsurer or a SACCO CEO

1. **Backtest, a known drought.** Pick *Kangundo, Machakos County*. Point at the payout bars, then the trajectory
   chart: long rains 2022 (drought) against 2020 (very wet). The soil moisture line drops below the crop trigger
   through flowering in 2022 and stays well above normal in 2020.
2. **Price it live.** Move the premium rate and the soil moisture trigger in the sidebar and watch the burn cost,
   loss ratio and basis-risk score respond. Switch wards to show how the same terms behave in wet Bureti and dry
   Kangundo.
3. **Clear the suspense account.** On the SACCO tab press *Run automated reconciliation*. The unallocated suspense
   rate drops from about 39% (an exact lookup) to under 3%, twelve duplicate rows are held instead of credited
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
| Sums insured, premium rate, triggers, fees, 70/30 split | **Illustrative**: need actuarial sign-off, the partner insurer's agreement and IRA approval |
| Insurer | "Partner insurer (to be named)" |

If there is no cache and no network, the app falls back to clearly labelled synthetic weather. *Refresh weather from
Open-Meteo* in the sidebar downloads the record again and updates the cache (`python -m engine.parametric_engine`
does the same for all five wards).

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

- Real SAR soil moisture and NDVI in place of the proxies, and triggers set per ward (the 180 mm excess-rain line
  fires often in wet highlands such as Kericho).
- Basis-risk testing against SACCO yield or loan-default records.
- Members' written consent to send part of a claim to their loan, and to share data (Data Protection Act, 2019).
- Live rails: M-Pesa Daraja C2B and B2C, WhatsApp Business Cloud API, the SACCO core banking export.

The earlier AgroShield platform (FastAPI, CHIRPS pricing engine, IRA pack) is kept in git: tag
`archive/agroshield-v1` and branch `archive/agroshield`.
