# CHIRPS v2.0 against CHIRPS v3.0: what changes for AgroShield pricing

**Needs owner approval: not merged into main.** This work lives on branch `pricing/chirps3`.
Pricing on main, and the default config on this branch, stay on CHIRPS v2.0.

Written 2026-11-02. Numbers come from `docs/pricing/chirps3-comparison.json`, made by
`research/chirps3_comparison.py` from the committed inputs (no downloads). Index version B-1.2.0,
history 1981 to 2025, long rains only, sum insured KES 10,000 per acre.

## Why this matters

The Climate Hazards Center (CHC) stops producing CHIRPS v2 after December 2026. CHIRPS v3.0 was
released in 2025. The long rains 2027 cover now on sale will be monitored after that date, so its
payouts must be calculated on CHIRPS v3. If the price was set on CHIRPS v2 but the payouts are decided
on CHIRPS v3, the price and the payouts no longer come from the same rainfall record. This note shows
how far apart the two records are for our two wards and what that does to the price.

## Short answer

- **Ward A (lowland):** the price hardly moves. Gross rate 18.84% on v2, 19.05% on v3 (KES 1,884 and
  KES 1,905 per acre). But the payout years are not the same: 9 of the 12 v2 payout seasons also pay
  on v3, 3 stop paying and 2 new ones start. Single seasons move a lot (2002: 59% on v2, nothing on v3;
  2014: 6% on v2, 46% on v3).
- **Ward B (highland):** the price falls by about a fifth. Gross rate 7.46% on v2, 5.79% on v3
  (KES 746 and KES 579 per acre). Two seed-voucher seasons disappear and no season is added.
- **1984 and 2008** (the two drought years we use as checks) still pay at Ward A on v3: 1984 pays 74%
  (81% on v2) and still passes the required test (at least 50%); 2008 pays 44% (41% on v2).
- **CHIRPS v3 is wetter**, by about 7% a year on average, and much more so in the 1980s and 1990s
  than in recent years. The CHC says why (see "Why the two records differ").
- **The early-advance check gets weaker on v3.** At Ward A it would have caught 4 of 7 payout seasons
  on v2 and only 1 of 5 on v3.
- **Recommendation for the owner:** re-price the long rains 2027 on CHIRPS v3 before any further sales,
  and do not use the v2 price for cover that will be settled on v3. The decision is yours; nothing has
  been merged.

## How the comparison was made

- Same engine, same product terms, same PET (NASA POWER Hargreaves), same ward boxes. Only the
  rainfall changes.
- **CHIRPS v2.0:** the committed ClimateSERV polygon means in `data/raw/chirps/` (unchanged).
- **CHIRPS v3.0:** daily "final" data, "rnl" version (ERA5 used to split each 5-day total across
  days; the only v3 daily version that starts in 1981). Read straight from the CHC yearly files on
  data.chc.ucsb.edu with HTTP range requests, only the chunks that hold the ward pixels. Cached in
  `data/raw/chirps3/` with `.meta.json` (request, files, retrieved_at, SHA-256 of both CSVs). No
  account was needed. Coverage: 1981-01-01 to 2026-09-30 (the 2026 file on the server ends there).
- **Same polygon mean as v2:** the plain average of the 0.05 degree pixels whose centres fall inside
  the ward box from `data/raw/chirps/<ward>.meta.json`. That is 4 pixels per ward:
  Ward A at latitude -0.175 and -0.125, longitude 35.825 and 35.875; Ward B at latitude -0.275 and
  -0.225, longitude 35.725 and 35.775. Every pixel's daily value is kept in `<ward>.pixels.csv` so
  the mean can be checked.
- **Check that this is really the v2 rule:** raw CHIRPS v2.0 daily for 2008 was read from the CHC file
  with the same reader and averaged the same way. It matches the ClimateSERV series exactly on every
  day of 2008 at both wards (largest difference 0.0001 mm, a rounding digit). Two other rules (all
  pixels touching the box, area-weighted) do not match. Record:
  `data/raw/chirps3/checks/v2_pixel_rule_2008.json`. So the differences below come from the data, not
  from how we average it.
- **Labels:** both rainfall records are REAL. PET is REAL (FALLBACK method, as on main). Ward
  locations are ILLUSTRATIVE placeholders, as on main.

Commands (from the repo root, with this branch's `src` on `PYTHONPATH`):

```
python -m agroshield_pricing.cli fetch-rainfall --dataset chirps3 --all --through 2026-12-31
python -m agroshield_pricing.cli run --all --offline                    # CHIRPS v2.0, the default
python -m agroshield_pricing.cli run --all --offline --source chirps3   # CHIRPS v3.0
python research/early_trigger.py chirps3
python research/advance.py chirps3 all
python research/chirps3_comparison.py
```

## Side by side

| | Ward A v2 | Ward A v3 | Ward B v2 | Ward B v3 |
|---|---:|---:|---:|---:|
| Mean annual rain 1981-2025 (mm) | 1,056 | 1,129 | 1,284 | 1,374 |
| Mean March to May rain (mm) | 368 | 389 | 439 | 451 |
| Seasons with any payout (of 45) | 12 | 11 | 6 | 4 |
| of which WRSI or failed-onset payouts | 9 | 9 | 1 | 1 |
| of which seed vouchers (germination dry spell) | 4 | 2 | 5 | 3 |
| Failed onsets | 0 | 1 | 0 | 0 |
| Median WRSI | 97.19 | 97.44 | 99.57 | 100.00 |
| Lowest WRSI | 55.56 | 57.68 | 74.79 | 72.27 |
| Expected loss (share of sum insured) | 8.61% | 8.82% | 3.16% | 2.24% |
| 1-in-10 year loss | 32.1% | 35.1% | 22.0% | 0.0% |
| 1-in-20 year loss | 46.5% | 45.7% | 25.0% | 25.0% |
| **Gross rate** | **18.84%** | **19.05%** | **7.46%** | **5.79%** |
| Gross premium per acre (KES) | 1,884 | 1,905 | 746 | 579 |
| Main payouts in target band (1 in 5 to 1 in 7) | yes (20%) | yes (20%) | no (2%) | no (2%) |
| 1984 WRSI, payout | 55.56, 81% | 57.68, 74% | 83.26, 0 | 96.98, 0 |
| 2008 WRSI, payout | 67.58, 41% | 66.77, 44% | 100.00, 0 | 100.00, 0 |

The two counts by type overlap in one season: Ward A 2002 on v2 has both a WRSI payout and a voucher.
Payout here is the share of the sum insured, voucher included (a voucher is KES 2,500, 25%).

**Payout years.**

- Ward A, both: 1984, 1999, 2000, 2004, 2008, 2009, 2014, 2016, 2022. Only on v2: 1994, 2002, 2007.
  Only on v3: 1993, 2012.
- Ward B, both: 2002, 2009, 2012, 2016. Only on v2: 1986, 2007. Only on v3: none.

**The 1984 and 2008 results.**

- 1984, Ward A: the season starts in the same dekad (April dekad 1) on both. v3 has 7% more rain in
  the season (321 mm against 298 mm), WRSI 57.68 against 55.56, payout 74% against 81%. It still passes
  the required test (at least 50%).
- 1984, Ward B: v3 has 18% more rain in the season (561 mm against 474 mm). WRSI rises from 83.26 to
  96.98. Neither pays, and this ward's 1984 test is "reported only". It is the largest single WRSI gap
  at Ward B.
- 2008, Ward A (the season used in the portal demo replay): almost the same on both. WRSI 66.77
  against 67.58, payout 44% against 41%. The replay's figures on main (WRSI 67.6, 41%) are v2 figures.
- 2008, Ward B: WRSI 100 on both, no payout.

**How closely the rainfall agrees.** Correlation between the two records:

| | Ward A | Ward B |
|---|---:|---:|
| Day by day | 0.47 | 0.46 |
| Dekad (10-day) totals | 0.89 | 0.89 |
| March to May totals | 0.91 | 0.93 |
| Annual totals | 0.88 | 0.91 |
| Season WRSI (seasons with a WRSI on both) | 0.91 | 0.84 |

**Mean annual rain by decade (mm).** The gap is large early in the record and small recently:

| Years | Ward A v2 | Ward A v3 | Ward B v2 | Ward B v3 |
|---|---:|---:|---:|---:|
| 1981-1990 | 988 | 1,160 | 1,214 | 1,387 |
| 1991-2000 | 912 | 1,037 | 1,143 | 1,246 |
| 2001-2010 | 1,042 | 1,080 | 1,232 | 1,343 |
| 2011-2020 | 1,229 | 1,220 | 1,471 | 1,473 |
| 2021-2025 | 1,163 | 1,163 | 1,438 | 1,470 |

## Why the two records differ, in plain words

1. **CHIRPS v3 is wetter by design.** The CHC README for v3.0 (copy in
   `data/raw/chirps3/docs/README-CHIRPSv3.0.txt`) says v3 corrects station rain gauges for "undercatch"
   (wind blowing rain past the gauge), which v2 did not, and that "as a result, CHIRPS v3.0 is overall
   wetter compared to CHIRPS v2.0". It also uses a new long-term average map built with about 80,000
   more station normals, almost four times as many station sources, and a satellite formula that
   spreads values over a wider range.
2. **The extra rain is mostly in the old years.** In the 1980s v3 has 17% (Ward A) and 14% (Ward B)
   more rain a year than v2; since 2011 the two are within about 2%. We have not seen a CHC statement on why
   the gap shrinks over time. One likely reason is that station coverage and the new corrections
   affect early years differently, but this is our reading, not a CHC finding. For pricing it matters:
   on v3 the history makes the early years look less dry compared with recent years than on v2.
3. **Rain is placed on different days.** Both datasets are built as 5-day totals and then split into
   days. v3 "rnl" splits them using ERA5 weather model timing (CHC daily readme, copy in
   `data/raw/chirps3/docs/readme_daily.txt`). Day-by-day agreement is therefore poor (0.47) even when
   10-day totals agree well (0.89).
4. **The day-sensitive parts of the product move most.** The replanting voucher (less than 20 mm in
   the 20 days after planting rain), the failed onset (less than 80 mm in the planting window) and the
   start-of-season dekad all depend on a few days of rain. They account for most of the payout changes:
   - Ward A 1994, 2002, 2007 and Ward B 1986, 2007: a voucher on v2 only. On v3 the 20 days after
     planting rain were wet enough. In Ward A 1994 and 2002 and Ward B 1986 the season therefore
     starts earlier on v3, because on v2 it was restarted after the dry spell.
   - Ward A 2012: a voucher on v3 only (11 mm in the 20 days after planting rain on v3).
   - Ward A 1993: a failed onset on v3 only (56 mm in the planting window, below 80 mm; on v2 the
     season started in April dekad 3 and reached WRSI 83.43, no payout).
5. **Large WRSI gaps (10 points or more)** follow from the points above:
   - Ward A 2002 (+18.5 on v3): v2 restarts the season after a germination dry spell (April dekad 2)
     and the later crop ends with WRSI 69.75; v3 has no dry spell, the season starts in March dekad 1
     and ends with WRSI 88.23.
   - Ward A 2004 (+11.0), 2017 (+10.2): earlier or later start on v3 and more rain in the season.
   - Ward A 2014 (-12.0): v3 has 15% less rain in the season (264 mm against 310 mm), payout rises from
     6% to 46%.
   - Ward B 1984 (+13.7): 18% more season rain on v3, see above.

## Early-season check and the early advance (research, not in the product)

The early trigger projects the end-of-season WRSI 35 days after the start of season from observed
rain, a 15-day forecast and climatology. Each rainfall record is paired with the forecast made from
it: v2 with CHIRPS-GEFS v12 (committed cache), v3 with **CHIRPS3-GEFS** (new: 15-day totals from
`products/EWX2/CHIRPS3-GEFS/` on the CHC server, read 3 x 3 pixels at a time, cached in
`data/raw/research/chirps_gefs_15day.chirps3.json` with its `.meta.json`). On the 37 issue dates
that both caches share, the two forecasts agree closely (correlation 0.96, mean 96 mm and 90 mm).

| | Ward A v2 | Ward A v3 | Ward B v2 | Ward B v3 |
|---|---:|---:|---:|---:|
| Seasons checked | 25 (2000-2025) | 24 (2001-2025) | 25 | 24 |
| Missing seasons | 2020 | 2000, 2020 | 2020 | 2000, 2020 |
| Seasons below the WRSI trigger | 7 | 5 | 1 | 1 |
| Correlation, projected and final WRSI | 0.58 | 0.44 | 0.40 | 0.38 |
| Early trigger (projected WRSI below 80) fires | 0 | 0 | 0 | 0 |
| Advance (projected WRSI below 95) fires | 4 | 1 | 0 | 0 |
| Advance catches payout seasons (in sample) | 4 of 7 | 1 of 5 | 0 of 1 | 0 of 1 |
| Leave-one-out: caught, false alarms | 4, 0 | 1, 1 | 0, 4 | 0, 2 |
| Advance gross premium per acre (KES) | 98 | 0 | 0 | 0 |

- Missing seasons: there is no forecast file for the check day (HTTP 404). CHIRPS3-GEFS starts on
  2001-01-01, so 2000 cannot be checked on v3; 2020 is missing on both.
- On v3 the advance at Ward A fires only in 2009. In 2008 the projection is 95.8, just above the 95
  line. Its extra cost on v3 is zero in these seasons, because the one season where it fired (2009)
  paid more than 20% in the end (28%). The leave-one-out test mostly chose 97.5 instead of 95, a sign that 95 is not
  stable on v3.
- The advance is offered only at Ward A (product.yaml). Ward B is shown for comparison only, on both
  records; the v2 Ward B figures were computed for this note and are not in the committed
  `advance_results.json`.
- The old CHIRPS-GEFS v12 folder (`products/EWX/...`) now answers HTTP 404 (checked 2026-11-01). The
  v2 results above come from the committed cache; they cannot be refreshed from the server any more.

There is no yield backtest on either record: no real ward yields are in the repository yet (as on
main), so basis risk cannot be measured. The "backtest" here is the 45-season replay above.

## Monitoring

- Seasons planted in 2027 or later are monitored on CHIRPS v3 for both the observed rain and the
  climatology that fills the rest of the season (`rainfall.monitoring_chirps3_from_year: 2027` in
  `config/pilot.yaml`). Earlier seasons keep CHIRPS v2. The two are never mixed in one season: live v3
  data is cached as `<ward>_<year>.chirps3.csv`, apart from the v2 files.
- Each stored ward status and its audit entry record which dataset was used (`rainfall_dataset`).
- Tests: `tests/test_chirps3.py` (the switch by season, no ClimateSERV call for a 2027 season, the
  committed v3 data used as the 2027 climatology, a new year whose file is not published yet).
- **Open point: data delay.** v3 "final" daily for a month appears in the middle of the next month
  (the 2026 file was last updated on 15 October and ends on 30 September). The CHC also publishes a
  preliminary v3 daily, but it splits days with IMERG ("sat"), not ERA5 ("rnl"). Monitoring here reads
  final data only, so for 2027 the index is confirmed about two to seven weeks after the rain fell.
  Whether to use preliminary data for early warnings (never for payouts) is a decision for the owner.

## What the owner is asked to decide

1. Approve moving pricing for long rains 2027 to CHIRPS v3.0 (set `rainfall.source: chirps3`). Ward A's
   price barely changes; Ward B's falls from KES 746 to KES 579 per acre.
2. Decide what to do with policies already sold at v2 prices but settled on v3.
3. Decide whether the early advance stays in research at Ward A, since on v3 it catches 1 of 5 payout
   seasons instead of 4 of 7.
4. Approve merging this branch. It has not been merged into main.

## Checks done

- Default config (CHIRPS v2) on this branch still reproduces the main reference exactly
  (`docs/overnight/pricing_reference.json`): `results.json` SHA-256 ward-a 76436465..., ward-b
  a9ad3062....
- CHIRPS v3 runs: `results.json` SHA-256 ward-a d23e9f16..., ward-b 3f779d45....
- Cached v3 inputs: `data/raw/chirps3/ward-a.csv` SHA-256 c9bde1ab..., `ward-b.csv` 2d173bfb...;
  each `.meta.json` lists every yearly file read (URL, size, last modified, requests, bytes).
- Full test suite green on the branch.

## Sources

- CHC, CHIRPS v3.0 README: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt
- CHC, CHIRPS v3 daily readme: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt
- CHIRPS v3.0 daily rnl files:
  https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/netcdf/byYear/
- CHIRPS v2.0 daily (used only for the 2008 pixel check):
  https://data.chc.ucsb.edu/products/CHIRPS/v2.0/global_daily/netcdf/p05/
- CHIRPS3-GEFS 15-day:
  https://data.chc.ucsb.edu/products/EWX2/CHIRPS3-GEFS/chirps3_gefs_global_15day_data/
- CHIRPS v2.0 polygon means: SERVIR ClimateSERV (committed in `data/raw/chirps/`).
