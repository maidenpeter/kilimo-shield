# Phase 5 (milestone 10): IRA pack and end-to-end season

Branch `work/phase5-ira`, from main at 73a377e. No migration (no model changes). Every number below comes from a run
I did on this branch, and the file it is in is named next to it.

## What was built

### 1. IRA documentation pack (DRAFT, ILLUSTRATIVE)

`python tools/ira/build_pack.py` (about 30 seconds) writes `docs/ira/`:

| File | What |
|---|---|
| `AgroShield-IRA-pack-DRAFT-ILLUSTRATIVE.pdf` | The pack, 27 A4 pages. Header and footer of every page say DRAFT and ILLUSTRATIVE and "not submitted to or approved by the Insurance Regulatory Authority" |
| `pack.html` | The PDF's HTML source |
| `disclosure.html` | Consumer disclosure, plain English and Kiswahili (Kiswahili marked pending native-speaker review) |
| `data/pricing_summary.csv`, `data/backtest_<ward>.csv`, `data/trigger_sensitivity_<ward>.csv`, `data/soil_sensitivity_<ward>.csv`, `data/data_sources.csv` | The figures, each CSV starting with a `# DRAFT / ILLUSTRATIVE` line naming its source run |
| `data/figures.json` | Everything the pack quotes, with its sources |
| `data/engine_<ward>.json` | The engine's own results.json and run manifest, unchanged, inside a marked wrapper |
| `manifest.json` | Size and SHA-256 of every file above |

Sections: policy wording placeholder (the insurer is "Partner insurer (to be named)", every heading "[To be written]",
plus the schedule of index terms read from config); pricing methodology (from `src/agroshield_pricing` and README:
WRSI on CHIRPS, triggers, burn cost, risk margin, loadings, subsidy and Resilience split, what is not in the
product); index development (from the commit history: v0 per-phase index, v1 WRSI, B-1.2.0 decisions, Layer A
dropped; v1 against v0; the 1984 test; trigger and soil sensitivity; FEWS NET validation pending); data sources and
provenance (every `data/raw/*/*.meta.json` with retrieval date, recorded SHA-256 and a fresh check); backtest results
per ward; basis-risk statement (what cannot be measured without ward yields, what is measured now); payout timeline
(10 days from confirmation, `monitoring.payout_within_days`, with the simulated season as evidence); consumer
disclosure; data protection summary (encryption, masking, consent purposes and their SHA-256 from
`config/consent.yaml`, local storage, the KMD and SMS rules from `config/weather.yaml`). No logo, no partner names.

Figures from the engine run the build made (`agroshield-price run --all --offline --out var/ira-engine-run`; source
`docs/ira/data/figures.json`):

| Ward | Seasons | Any payout | Expected loss | Gross rate | Gross per acre at KES 5,000 / 10,000 / 15,000 |
|---|---|---|---|---|---|
| Rongai West (ward-a) | 45 (1981 to 2025) | 26.7% | 8.61% | 18.84% | KES 1,173.17 / 1,884.05 / 2,619.36 |
| Molo Highlands (ward-b) | 45 (1981 to 2025) | 13.3% | 3.16% | 7.46% | KES 709.46 / 745.69 / 788.66 |

### 2. Simulated season: Rongai West, long rains 2008 (SIMULATION / REPLAY)

`python tools/sim/season.py --year 2008` (or `python -m agroshield_platform.simulate`, about 100 seconds) replays the
season day by day in a throwaway SQLite database (deleted afterwards) with a fictional SACCO, officers and six
fictional members. It writes `docs/remaining/season-2008/index.html`, `season.json` and `bordereaux/*.zip`. Every
step calls the existing service; nothing about prices, triggers or payouts is re-implemented.

Dates and numbers from `docs/remaining/season-2008/season.json`:

| Step | Date | Service | What happened |
|---|---|---|---|
| Enrolment | 15 to 20 Oct 2007 | `services.enrol` | 6 members, sales window 15 Sep 2007 to 14 Feb 2008 |
| Premium | 2 Nov 2007 to 25 Jan 2008 | `mpesa.request_premium` + simulated callback + `mpesa.handle_callback`; `services.record_payment` | STK pushes (one cancelled on the phone, then paid), SACCO deductions, instalments |
| Settlement | 31 Jan, confirmed 4 Feb 2008 | `settlement.record`, `settlement.review` | KES 11,964 remitted gross and confirmed by the underwriter |
| Sales close | 15 Feb 2008 | `services.close_sales_windows` daily; `settlement.record_refund` | reminders on 7 and 13 Feb; one cover did not start; its KES 1,178 refunded 20 Feb |
| Daily monitoring | 29 Feb to 13 Aug 2008 | `monitoring.run_monitoring(mode="replay")` | 167 daily runs, each audited |
| Trigger confirmed | 1 Aug 2008 | (inside `run_monitoring`) | final WRSI 67.58, payout 41.4% of sum insured, 5 payouts for active cover only |
| Underwriter approval | 2 Aug 2008 | `monitoring.approve` | 5 approved |
| Payout | 4 Aug 2008 | `monitoring.pay` | KES 48,645 to 5 members (4 by simulated M-Pesa B2C, 1 to the SACCO loan); 3 days after confirmation, due by 11 Aug: **asserted within 10 days** |
| SMS log | whole season | `sms.send_pending` with `LogOnlySender` | 23 messages, recorded and not sent; none to the member without SMS consent |
| Missed-payout report | 6 Aug, reviewed 12 Aug 2008 | `monitoring.report_missed` (USSD), `monitoring.review_missed` | basis risk recorded; payouts unchanged (checked) |
| Bordereaux | 31 Aug 2008 | `underwriting.bordereaux` | 2007-10 (6 premium rows) and 2008-08 (5 payout rows), masked, with checksums |
| Reinsurer summary | 31 Aug 2008 | `underwriting.portfolio`, `as_if_losses`, `esg` | KES 117,500 in force; as-if expected loss KES 10,112, 1-in-10 KES 37,694, 1-in-20 KES 54,661 over 45 seasons |

The final WRSI and payout share equal the pricing engine's 2008 result (tested). The report shows the 10-day clock.

### 3. Tests

`tests/test_phase5_ira.py`, 14 tests (12, plus 2 added in review), all passing (about 115 seconds): the pack builds from scratch with a PDF; every
PDF page and every file carries DRAFT and ILLUSTRATIVE and no em dash; the manifest hashes and sizes match; the
figures are the engine's (the embedded results, written the engine's way, give the engine's own SHA-256); input
checksums match their metadata; the simulation covers every step in order; the trigger and payouts equal the engine's
2008 result; every payout lands within 10 days (and a late one fails the check); SMS are log-only and only with
consent; outputs are labelled, fictional and masked (including inside the bordereaux ZIPs); the clock is put back.

Full suite (review run at `1d1f66e`, import path checked to point at the branch's `src/`): 353 passed in 836
seconds. `tests/test_uw.py::test_pricing_runs_and_reports` needs engine run folders in the git-ignored `runs/`; in a
fresh checkout it fails until `agroshield-price run --all --offline` has been run once (not caused by this phase).

## Commits

- `5bdfa77` Phase 5: simulated season, end to end on the real services
- `47ae4dd` Phase 5: IRA documentation pack builder (DRAFT, ILLUSTRATIVE)
- `52298bd` Phase 5: tests for the IRA pack and the simulated season
- `9fef985` Phase 5: report, decisions and README
- `64b7e2c` Phase 5: generated IRA pack and 2008 season report
- `1d1f66e` Phase 5 review: simulator runs any year, pack build guards its folder

## Review (independent check of this branch)

- Rebuilt the pack into a scratch folder (32 seconds): the engine results SHA-256 and every figure in
  `data/*.csv` match the committed pack; only run ids and timestamps differ.
- Re-ran the 2008 season (136 seconds): same result (5 payouts, KES 48,645, paid 3 days after confirmation).
- Found and fixed: `--year 2010` (no trigger) stopped with "steps missing: approval, payout", and `--year 2007`
  (replanting voucher only) stopped with "sms after payout". Both now run (2010: no payouts; 2007: 5 vouchers,
  KES 28,750, 3 days after confirmation); the report words an early trigger correctly. Decision 5.12.
- Found and fixed: `build_pack.py --out` deleted whatever folder it was given; it now refuses a folder that is not
  empty and holds no earlier pack.
- Checked: no changes to pricing, triggers, payouts, consent, masking, auth, money handling or the hashed config
  files; no em dashes, no personal data, no logo or partner name in the outputs; commits carry no AI attribution.
- Still open: the committed pack and season report are snapshots. If main changes the engine or adds files under
  `data/raw/` before this branch merges, rebuild both (`python tools/ira/build_pack.py`, `python tools/sim/season.py`);
  `test_pack_data_sources_checksums_still_match` fails on any new `data/raw/*/*.meta.json` until the pack is rebuilt.

## Blocked

Nothing blocked. Still pending outside this phase (not things I could do):

- **Kiswahili review** of the consumer disclosure (written by me, marked pending native-speaker review).
- **Policy wording and complaints text**: need the partner insurer (to be named) and its legal advisers.
- The pack's numbers stay ILLUSTRATIVE until the pilot wards, soils, triggers, loadings and sums insured are agreed.

## Decisions (defaults used; also in docs/DECISIONS_LOG.md under Phase 5)

1. Commands are tools scripts (`tools/ira/build_pack.py`, `tools/sim/season.py`) and `python -m
   agroshield_platform.simulate`, not new `agroshield-portal` subcommands, so `cli.py` is untouched for the merge.
2. The pack's engine run goes to `var/ira-engine-run/` (git-ignored, its own audit log), so the committed
   `runs/audit_log.jsonl` is unchanged. The run's id, command, git commit and SHA-256 are in the pack.
3. Every file is marked: CSVs carry a first `# DRAFT / ILLUSTRATIVE` line; the engine's results are embedded unchanged
   in a marked JSON wrapper; the engine's own report.html is not copied (it is not marked DRAFT; the command
   regenerates it).
4. PDF: Playwright's bundled Chromium, falling back to the installed Chrome or Edge (the bundled headless shell is not
   installed on this machine; Chrome printed it).
5. Simulation clock: while the replay runs, `datetime` in the platform modules (models, monitoring, settlement, sms,
   mpesa, services, underwriting) is replaced by one that reads the simulated clock, then put back (tested). No
   production code changed.
6. Simulation calendar (set for Ward A's window): enrol from 30 days after sales open; remit before the close so the
   steps follow the brief's order; approve the day after confirmation, pay two days later; the missed-payout report
   two days after payment, reviewed six days later; bordereaux and the reinsurer summary at month end.
7. In a replay the index confirms the day after the season's last dekad (the record is complete); live, CHIRPS final
   arrives about three weeks later. The 10-day clock starts at confirmation either way; both reports say so.
8. The season report's "days left" is counted on the replay calendar. The workspace's own trigger view judges a replay
   from its confirmation day, and its ESG "median days to pay" leaves replays out by design (stated in the report).
9. The consumer disclosure explains the WRSI as a "ward score out of 100" and lists what the cover does not pay for
   (pests, disease, floods, theft), because it only measures lack of rain.
