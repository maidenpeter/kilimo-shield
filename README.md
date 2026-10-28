# AgroShield

Parametric maize insurance for Kenyan smallholders, distributed through SACCOs and
underwritten by a licensed insurer. AgroShield is the technology and pricing layer,
not the risk carrier.

> "AgroShield protects the season before it fails, and rewards farmers who farm smarter."

**Status:** milestones 1-4 of 10 (quote API added in milestone 4). Layer B is a seasonal WRSI index (v1.1) with
failed-onset and germination dry-spell triggers; the superseded per-phase index (v0) is
kept for comparison only. Layer A (anticipatory seed voucher) runs on a synthetic forecast.
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

## Layer A: pre-season seed voucher

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
ILLUSTRATIVE pending KAIP and the underwriter. Layer A can be quoted only where it is
offered (Ward A). `POST /v1/quotes` takes everything in the request body and logs each
quote to `var/audit/quotes.jsonl`; quotes carry no personal data.

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
tests/                   payout functions, WRSI, onset, PET, burn cost, premium, config,
                         data integrity, validation, regression, end to end
docs/                    BORROWED_FROM_MVP.md: ideas taken from the old demo, by milestone
```

## Open questions

- Which Nakuru wards for the pilot (currently two labelled placeholders), and their soils.
- Underwriter partner: loadings, margin, target payout frequency, Resilience discount cap.
- Real ward yields, KMD/ICPAC hindcasts (Layer A) and KIAMIS access.
- GSM or LoRa for the Sentinel camera pilot; picture-based rider in v1 or v2.
