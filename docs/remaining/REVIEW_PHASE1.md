# Review of the Phase 1 commit (9ff7db2)

Four independent reviewers (M-Pesa, access, money, privacy and tests) read the commit; a skeptic tried to refute each finding.
17 findings were confirmed and all are fixed; 7 were refuted. Tests: tests/test_phase1_review_round2.py.

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | high | Push started after 21:00 EAT on the close day is lapsed and refunded instead of starting cover (Nairobi wall time stored, read back as UTC) (`src/agroshield_platform/mpesa.py:169`) | Fixed: every M-Pesa request time stored in UTC (mpesa._utc); regression test reloads between steps. |
| 2 | medium | Re-check schedule runs 3 hours late (first check at ~3h02m, flag at ~27h) for the same naive-datetime reason (`src/agroshield_platform/mpesa.py:270`) | Fixed with 1. |
| 3 | medium | Callback and scheduled re-check can both credit the same push (different references, so the receipt check does not catch it) (`src/agroshield_platform/mpesa.py:280`) | Fixed: compare-and-set claim (mpesa._claim) for every move out of pending/unconfirmed; race test. |
| 4 | low | Manager resolve can credit a receipt that already paid another push (receipts of query-confirmed payments are never stored) (`src/agroshield_platform/mpesa.py:326`) | Fixed: resolve also rejects receipts held by any other request; a late callback fills in the receipt of a push paid on the query alone. |
| 5 | low | Serve-thread re-check holds the SQLite write lock across slow Safaricom queries, so callbacks fail with 'database is locked' (`src/agroshield_platform/cli.py:249`) | Fixed: run_recheck uses one short transaction per request and makes the HTTP query before any write. |
| 6 | medium | A PDF already held in another scope stops the every-SACCO advisory or the SACCO copy from being created, and the manager can't see the existing one (`src/agroshield_platform/weather.py:168`) | Fixed: PDF hash unique per audience (migration 0003); KMD URL check only among every-SACCO items. |
| 7 | medium | Re-check and callback can both credit the same M-Pesa payment (double credit) (`src/agroshield_platform/mpesa.py:275`) | Fixed with 3. |
| 8 | low | Errors on the new /mpesa/{id}/resolve form show raw JSON instead of the error page (`src/agroshield_platform/web/app.py:1282`) | Fixed: only /mpesa/callback/ is excluded from HTML error pages. This also exposed an older bug: error and public pages for signed-in users crashed (navbar read after the session closed); fixed and tested. |
| 9 | low | /uw/money shows two different figures both labelled 'Refunds owed to farmers' (`src/agroshield_platform/web/templates/_uw_settlement.html:13`) | Fixed: labels distinguish total owed from still to pay. |
| 10 | low | Manager settlement page shows a blank paybill when the SACCO has no insurer (`src/agroshield_platform/web/app.py:480`) | Fixed: fallback names the paybill default. |
| 11 | low | set-paybill silently truncates the paybill or bank details to 60 characters (`src/agroshield_platform/cli.py:165`) | Fixed: refuses values over 60 characters and prints the stored value. |
| 12 | low | Prefilled refund amount rounds up and is then rejected as over the limit (`src/agroshield_platform/web/templates/member.html:32`) | Fixed: prefill shows the exact amount; error shows cents when needed. |
| 13 | low | 'nan' passes amount parsing and crashes the refund POST with a 500 (`src/agroshield_platform/settlement.py:56`) | Fixed: non-finite amounts are form errors. |
| 14 | high | M-Pesa push times are stored as Nairobi wall-clock time but read back as UTC: late-evening pushes on the close day lapse, and every re-check runs 3 hours late (`src/agroshield_platform/mpesa.py:172`) | Fixed with 1. |
| 15 | medium | Phase 1 M-Pesa tests never reload from the database, so they pass despite the timezone bug (`tests/test_phase1_review_fixes.py:155`) | Fixed: new tests commit and reload (tests/test_phase1_review_round2.py). |
| 16 | medium | STK query result code 4999 ('still under processing') is treated as a final failure (`src/agroshield_platform/mpesa.py:285`) | Fixed: 4999 means still processing; a success callback after a query failure is flagged for a manager. |
| 17 | low | Paybill change audit masks bank account numbers, so the old destination cannot be recovered (`src/agroshield_platform/cli.py:171`) | Fixed: paybill_old and paybill_new kept in full unless phone-shaped. |

## Refuted

- Manager resolve reports 'recorded as paid' even when no payment was recorded
- Manager weather list fetches 80 rows that include every-SACCO drafts, so their own SACCO's advisories can drop off
- Refund over-limit check can be bypassed by a double submit or two concurrent refunds
- MPESA_RECHECK_SECONDS parsed with a bare int(): a typo crashes every command, including daily
- Refund reference is shown in clear on the member page and can hold the farmer's phone number
- Refund test's status assertion is always true
- Manager Home tells them to 'record what you found' but gives no form or link
