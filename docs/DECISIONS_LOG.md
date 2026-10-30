# Decisions log

Decisions taken while working unattended, with the default used. Each one is listed again in the approval
checklist of the run's report. "Pending owner confirmation" means the default is built and can be changed.

## Remaining brief (30 October 2026)

### Phase 1: approved review fixes

| # | Decision | Default used | Status |
|---|---|---|---|
| 1.1 | Settlement "collected" | Gross premium received from members. Refunds owed and refunds paid are shown separately and never netted out. | Pending owner confirmation |
| 1.2 | SACCO fee before remitting | None. The SACCO remits gross premium; its distribution fee is settled separately. | Pending owner confirmation |
| 1.3 | Receiving paybill | A per-insurer setting (`Insurer.premium_paybill`), set only by platform staff with `agroshield-portal set-paybill` (audited), never from a web form, because changing where money goes is a fraud risk. Until set, screens say "the insurer's paybill (to be configured)". | Pending owner confirmation |
| 1.4 | Refunds paid | A new `refund` record per refund actually paid (amount, date, method, reference), entered by the SACCO's manager on the member page. It cannot exceed what is still owed on the policy. The amount owed stays on the policy as before. | Built (brief: track refunds paid separately) |
| 1.5 | M-Pesa re-check schedule | Status queries 2, 5, 15, 60, 240 and 1,440 minutes after the push (6 checks over a day). Run by `serve` every 5 minutes (`MPESA_RECHECK_SECONDS`), by `agroshield-portal mpesa-recheck`, and at the start of `daily`. | Built |
| 1.6 | What a status query answer means | 0: paid (credited once). Any other result code: failed, unless Safaricom had already sent a success callback, in which case the conflict is flagged for a person. No answer or an error: try again later. | Built |
| 1.7 | A push confirmed by query with no callback | Credited with the CheckoutRequestID as the payment reference, because the status query does not return the M-Pesa receipt number. The member page says "no receipt number was received". | Built |
| 1.8 | Still unknown after the last check | Status "unconfirmed": shown on officer Home and manager Reports as "Payment not confirmed: check with the farmer". A manager records paid (with the receipt from the farmer's SMS) or not paid; both audited. | Built |
| 1.9 | Payment started before close, confirmed after | The sales window is judged by when the push was started. The daily job does not lapse a policy while a push started on or before its close date has no final answer. | Built (brief) |
| 1.10 | Weather approval scope | A SACCO manager uploads, approves and withdraws advisories for their own SACCO only. Advisories shown to every SACCO (KMD fetches and operations uploads) are approved or withdrawn only by the new role `ops` (AgroShield operations), which has no SACCO and no insurer and sees only `/weather`. "Check KMD now" moved to operations, because fetched items are shown to every SACCO. | Built (brief) |
| 1.11 | HTTPS cookies | `AGROSHIELD_HTTPS=true` marks the session cookie Secure. HttpOnly and SameSite=Lax were already on. Default stays false so local development over http still works. | Built (brief) |
| 1.12 | KIAMIS records | Still shared by every SACCO (the review grouped them with weather). Left unchanged, because the brief scoped only weather advisories. | Needs approval (listed in the report) |
