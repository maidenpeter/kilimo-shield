# Soil water holding capacity from SoilGrids: before and after

**Needs owner approval: not merged into main.** Branch `pricing/soil-whc`.

Machine-readable version: `docs/pricing/soil-whc-comparison.json`.
Per-ward soil numbers: `data/soil/ward_awc.json`. Raw rasters: `data/raw/soil/soilgrids/`.

## In short

| | Ward A (Rongai West, lowland) | Ward B (Molo Highlands) |
|---|---|---|
| Soil water capacity before (placeholder) | 100 mm | 140 mm |
| Soil water capacity after (SoilGrids, 0-100 cm) | **130 mm** | **121 mm** |
| Gross rate, before | 18.84% | 7.46% |
| Gross rate, after | **16.70%** | **7.86%** |
| Gross premium per acre (KES 10,000 cover), before | KES 1,884 | KES 746 |
| Gross premium per acre, after | **KES 1,670** | **KES 786** |

- Ward A gets cheaper. Its soil holds more water than the placeholder assumed, so
  fewer seasons fall below the WRSI trigger (7 instead of 9). Main payouts drop
  from 1 season in 5 (20%) to about 1 in 6.4 (16%), still inside its target band.
- Ward B gets slightly dearer. The placeholder assumed deeper volcanic soils
  (140 mm), but SoilGrids shows about the same water holding as Ward A. Payout
  frequency does not change; only the size of the 2009 payout grows.
- The 1984 drought test at Ward A still passes (payout 83%, was 81%).
- The test quote for the fictional farmer Wanjiku Kamau (Ward A, 2 acres, Layer B,
  7 Resilience points) falls from KES 1,752.17 to KES 1,552.66 for the farmer's share.
  The regression tests that pin this quote, the 1984 WRSI (55.56 to 54.96) and the
  2008 replay WRSI (67.58 to 67.99) were re-recorded on this branch.
- The Layer B index version moves from B-1.2.0 to **B-1.2.1**, because a ward
  term changed. The method is unchanged.

The soil values are **REAL**: derived from ISRIC SoilGrids 2.0 for each ward's
rainfall box. The ward locations themselves, the triggers, loadings and sums
insured are still **ILLUSTRATIVE**. When the real pilot wards are chosen, the
soil values must be re-derived for them (one command, below).

## Where the numbers come from

**Dataset.** ISRIC SoilGrids 2.0, 250 m grid, licence CC BY 4.0. Downloaded on
2026-11-01 from ISRIC's open map service (`https://maps.isric.org/mapserv`, WCS
2.0.1). No account, no sign-up. 60 small GeoTIFFs (about 1 MB in all), each with
a `.meta.json` recording the exact request, retrieval time and SHA-256:

- water content at 10 kPa (`wv0010`), 33 kPa (`wv0033`) and 1500 kPa (`wv1500`),
  for the six SoilGrids depths (0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm),
  each as the mean prediction and the 5% and 95% quantiles;
- coarse fragments (`cfvo`, mean) for the same depths, for a sensitivity check.

The ISRIC REST point service returned "503 Service Temporarily Unavailable" on
2026-11-01, so the map service was used. It is better anyway: it gives every
pixel in the ward, not one point.

**Why SoilGrids and not iSDAsoil.** SoilGrids publishes water content at field
capacity and wilting point directly. Using iSDAsoil would have needed an extra
step (a pedotransfer function from texture and carbon). iSDAsoil was not
contacted.

**Formula.** Available water capacity (AWC) for each 250 m pixel:

    AWC (mm) = sum over layers of (water at 33 kPa - water at 1500 kPa) x layer thickness (mm)

over the top 100 cm, i.e. the layers 0-5, 5-15, 15-30, 30-60 and 60-100 cm. A
layer with wilting point above field capacity would count as zero (none did).
SoilGrids stores water content as integers in thousandths of cm3/cm3: 326 means
0.326. The ISRIC FAQ page that lists the units could not be reached on
2026-11-01 (HTTP 502). This is the only scale that gives physically possible
values here (polygon means: field capacity 0.32 to 0.33, wilting point 0.19 to 0.22).

**Area.** The ward value is the plain mean over every pixel whose centre lies
inside the ward's rainfall box: the same 0.10 degree square used for CHIRPS
(`ward_geometry` in `rainfall/chirps.py`, recorded in `data/raw/chirps/ward-*.meta.json`).
That is 2,022 pixels at Ward A and 2,006 at Ward B, about 126 km2 each. The map
is downloaded in SoilGrids' own equal-area grid (Interrupted Goode Homolosine),
so nothing is resampled and every pixel counts equally.

**Depth: 0 to 100 cm.** FAO-56 (Table 22) gives maize a maximum effective
rooting depth of 1.0 to 1.7 m. We use the shallow end because:

1. the WRSI water balance uses one bucket for the whole season, and young maize
   roots are much shallower than 1 m for the first weeks;
2. smallholder fields often have a plough pan or shallow topsoil that limits roots;
3. 100 cm is a SoilGrids layer boundary, so no layer has to be split.

60 cm and 150 cm are shown below as the plausible range.

**Field capacity at 33 kPa.** This is the usual definition. Some soil
scientists use 10 kPa for free-draining tropical and volcanic soils, which
gives a much larger number (below). This choice should be confirmed by an
agronomist or soil scientist familiar with Nakuru soils.

## Uncertainty

All values in mm of plant-available water.

| | Ward A | Ward B |
|---|---|---|
| **Used: 0-100 cm, 33 kPa, polygon mean** | **130** | **121** |
| Pixels in the box, 10th to 90th percentile | 116 to 141 | 106 to 137 |
| Pixels in the box, lowest to highest | 90 to 153 | 89 to 154 |
| Rooting depth 60 cm | 78 | 74 |
| Rooting depth 150 cm | 187 | 174 |
| Field capacity at 10 kPa instead of 33 kPa | 181 | 179 |
| Stones subtracted (coarse fragments, 7 to 18% by volume) | 116 | 101 |

- **SoilGrids' own prediction interval is wide.** For every layer, the 90%
  interval for field capacity is roughly 0.15 to 0.49 cm3/cm3 and for wilting
  point roughly 0.06 to 0.34 (per-layer values in `data/soil/ward_awc.json`).
  These quantiles cannot simply be subtracted to give an AWC interval, so none
  is quoted, but they show that a single-ward value from a global model is
  uncertain by tens of millimetres.
- **The two wards are not clearly different.** The 9 mm gap between them is
  smaller than the spread inside either box. The placeholder's assumption that
  Molo's highland soils hold more water than Rongai's is not supported by
  SoilGrids, but SoilGrids is also too coarse to rule it out.
- **Stones.** It is not clear from the documentation available to me whether
  SoilGrids water content is per volume of whole soil or of fine earth only, so
  the main value does not subtract stones. If it is per fine earth, the
  stone-corrected value (116 and 101 mm) is the better one.
- **Local data would be better.** A soil survey of the actual pilot wards
  (for example KALRO or Kenya Soil Survey profiles) should replace this when available.

## Before and after: pricing

Command: `agroshield-price run --all --offline` (run as
`python -m agroshield_pricing.cli run --all --offline` on the branch). Long rains,
45 seasons (1981 to 2025), KES 10,000 sum insured per acre.

The "before" run on this branch, with the placeholder soil, gives exactly the
reference `results.json` hashes on main (ward-a `76436465...`, ward-b
`a9ad3062...`), so the only change in "after" is the soil. Two "after" runs gave
identical hashes (ward-a `19615cee...`, ward-b `d760c212...`).

| | Ward A before | Ward A after | Ward B before | Ward B after |
|---|---|---|---|---|
| Soil water capacity | 100 mm | 130 mm | 140 mm | 121 mm |
| Median WRSI | 97.2 | 98.6 | 99.6 | 99.6 |
| Lowest WRSI | 55.6 | 55.0 | 74.8 | 72.4 |
| Seasons with WRSI below trigger (80) | 9 | 7 | 1 | 1 |
| Main payout frequency (WRSI or failed onset) | 20.0% | 15.6% | 2.2% | 2.2% |
| Any payout, including replanting | 26.7% | 22.2% | 13.3% | 13.3% |
| Expected loss (share of sum insured) | 8.61% | 7.46% | 3.16% | 3.34% |
| Gross rate | 18.84% | 16.70% | 7.46% | 7.86% |
| 1984 drought test | WRSI 55.6, pays 81% | WRSI 55.0, pays 83% | WRSI 83.3, pays 0 (reported only) | WRSI 84.2, pays 0 |

Ward A's main payout frequency stays inside its target band (1 season in 5 to 7).
Ward B's main payout frequency was already far below its band and still is;
the soil change does not fix that.

### WRSI per season

- Ward A: WRSI changed in 34 of 45 seasons, by -2.0 to +6.5 points (mean +1.3).
- Ward B: WRSI changed in 27 of 45 seasons, by -2.5 to +1.0 points (mean -0.4).

Every season, before and after, is listed in the JSON (`per_year`).

A larger bucket does not always raise WRSI. In the model, stress starts once the
soil holds less than 45% of its capacity (depletion fraction 0.55), so a larger
capacity can start stress at a higher absolute water level. In very dry seasons
like 1984 that can lower WRSI slightly.

### Seasons where the payout changed

Payout as a share of sum insured.

| Ward | Season | WRSI before | WRSI after | Payout before | Payout after |
|---|---|---|---|---|---|
| A | 1984 | 55.56 | 54.96 | 81.5% | 83.5% |
| A | 1999 | 68.96 | 68.23 | 36.8% | 39.2% |
| A | 2000 | 72.99 | 72.48 | 23.4% | 25.1% |
| A | 2002 | 69.75 | 74.89 | 59.2% | 42.0% |
| A | 2004 | 65.66 | 72.18 | 47.8% | 26.1% |
| A | 2008 | 67.58 | 67.99 | 41.4% | 40.0% |
| A | 2009 | 76.29 | 81.11 | 12.4% | 0% |
| A | 2014 | 78.20 | 78.56 | 6.0% | 4.8% |
| A | 2022 | 78.83 | 84.29 | 3.9% | 0% |
| B | 2009 | 74.79 | 72.36 | 17.4% | 25.5% |

Payouts in 2002 include the replanting payment, which is unchanged; only the
WRSI part moved.

### Soil sensitivity after the change

The report's soil sensitivity table now always includes the ward's own value.

| Soil capacity | Ward A gross rate | Ward A any payout | Ward B gross rate | Ward B any payout |
|---|---|---|---|---|
| 60 mm | 26.54% | 33.3% | 11.45% | 15.6% |
| 100 mm | 18.84% | 26.7% | 8.61% | 15.6% |
| 121 mm (Ward B value) | | | 7.86% | 13.3% |
| 130 mm (Ward A value) | 16.70% | 22.2% | | |
| 140 mm | 16.36% | 22.2% | 7.46% | 13.3% |
| 180 mm | 16.28% | 22.2% | 6.82% | 13.3% |

Above about 120 mm the price moves much less (Ward A: 16.7% at 130 mm, 16.3% at 180 mm). Below 100 mm it rises quickly. So the
remaining soil uncertainty matters mostly if the true rooting depth is shallow
(60 cm gives about 75 mm).

## What was not re-run

- The EXPERIMENTAL early advance research (`research/advance.py`) and the short
  rains research also use the ward soil value. They were not re-run on this
  branch, so their committed reports still reflect the placeholder soil.
- The demo database fixture keeps its B-1.2.0 policies; they are historical.

## For the owner to decide

1. Accept SoilGrids AWC (0-100 cm, 33 kPa) as the ward soil value, or choose a
   different depth or field capacity definition.
2. Accept the index version bump to B-1.2.1 and the new prices (Ward A cheaper,
   Ward B slightly dearer).
3. Merge `pricing/soil-whc` into main, or not.

## Reproduce

    pip install -e .[soil]                       # adds rasterio, only for the soil step
    agroshield-price fetch-soil                  # downloads (skips cached files), then writes data/soil/ward_awc.json
    agroshield-price soil-awc                    # recompute from the cache only, no download
    agroshield-price run --all --offline         # prices with the soil value in config/wards.yaml
    python tools/soil_whc_comparison.py BEFORE_RUNS AFTER_RUNS docs/pricing/soil-whc-comparison.json

`soil-awc` never edits config: the chosen value is copied into
`config/wards.yaml` by hand, so a soil refresh can never change a price on its own.
