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

### Phase 2: database migrations

| # | Decision | Default used | Status |
|---|---|---|---|
| 2.1 | When migrations run | On every start (`init_db`, so the portal, the CLI and tests), not as a separate deploy step, so nobody can run new code on an old schema. A SQLite file is copied to `<name>.pre-<revision>.bak` before any change. For PostgreSQL, take a database backup before deploying. | Built |
| 2.2 | Baseline | Revision 0001 is the schema of 30 October 2026 (commit b35d99f). Revision 0002 is Phase 1. Databases made before migrations are recognised by their exact tables and columns and stamped, never guessed: one that matches no revision is refused and left untouched. | Built |
| 2.3 | New empty database | Created from the models and stamped at the newest revision (fast). A test proves the revisions build exactly the same schema, so the two cannot drift. | Built |
| 2.4 | Pending M-Pesa requests at upgrade | Revision 0002 queues them for a status check at once, so none is left without a re-check. | Built |
| 2.5 | Existing weather advisories | Become "every SACCO" items (managed by operations), because until now every advisory was shown to every SACCO. | Built |

### Phase 1 review fixes (docs/remaining/REVIEW_PHASE1.md)

| # | Decision | Default used | Status |
|---|---|---|---|
| 1.13 | M-Pesa request times | Stored in UTC, like every other platform timestamp written by the models. Payment `received_at` keeps its existing meaning (Nairobi time) so bordereaux do not change. | Built |
| 1.14 | Result code 4999 | "Still being processed": treated as no answer yet, not as a failure. | Built |
| 1.15 | Success callback after the status query said "not paid" | Flagged "Payment not confirmed" for a manager; never credited automatically and never dropped. | Built |
| 1.16 | Same KMD PDF in two audiences | Allowed once for every SACCO and once per SACCO (migration 0003). | Built |
| 1.17 | Paybill change audit | Old and new values kept in full so the previous destination can be recovered; anything that looks like a phone number is still masked. | Built |

### Phase 3: milestone 8, photo app and farmer weather tab

| # | Decision | Default used | Status |
|---|---|---|---|
| 3.1 | App technology | An installable progressive web app (PWA) at `/app`, not a native app: one code base, no app store, works on low-end Android browsers, camera in the browser, offline queue in IndexedDB that sends when signal returns, service worker for opening with no signal. A native app can come later if field tests show a need. | Built (brief) |
| 3.2 | How farmers sign in | Phone number and a 6-digit PIN that the SACCO officer sets up on the member page (shown once, stored hashed, reset by the officer). Locked for 30 minutes after 5 wrong PINs. No SMS one-time codes, because SMS is not sent in development. | Built |
| 3.3 | Champion farmers | A farmer set up as "champion" can photograph the plots of other members of the same SACCO that an officer assigns. | Built (brief) |
| 3.4 | Who reviews photos | Underwriter accounts (the insurer's agronomists) in the underwriter workspace under Photos, for their insurer's policies only. No separate agronomist role yet. | Built |
| 3.5 | Check thresholds | Refused beyond 250 m from the registered plot point; same picture when the 64-bit perceptual hash differs by 6 bits or fewer; flagged for camera and app times more than 2 hours apart, camera and app GPS more than 500 m apart, GPS accuracy worse than 100 m, or more than 14 days between taking and sending. All in `config/photo.yaml`; ILLUSTRATIVE until field-tested. | Pending owner confirmation |
| 3.6 | Plots with no recorded location | Photos are accepted and flagged "the plot has no recorded location" (most current plots have none); the distance check needs a plot point. Recommend recording plot points at enrolment. | Pending owner confirmation |
| 3.7 | Growth stage windows | Days after the season's planting date: emergence 7 to 30, vegetative 31 to 60, tasselling 61 to 90, grain fill 91 to 120, maturity 121 to 160. ILLUSTRATIVE, for the agronomists to set. | Pending owner confirmation |
| 3.8 | Resilience photo point | Earned for a season when every one of the five stages has an on-schedule photo with no fraud flag (or one a reviewer cleared). It applies to the farmer's next policy for the same season, verified at source like KIAMIS; the quote and the point value are unchanged. | Built (brief) |
| 3.9 | AI suggestions | `claude-opus-5-5` through the official Anthropic SDK, low effort, structured output (tag and one-line reason). Only with the farmer's separate photo_ai consent (pending legal review), image only, re-encoded without EXIF or GPS and checked again before sending, no identifiers. With no key or on any error the queue works without suggestions. The key is read from `.env` only and never logged. | Built (brief) |
| 3.10 | photo_ai consent | New consent purpose; wording version C-2026-11-01 (the earlier purposes' wording and hashes unchanged). Asked in the app or recorded by the officer, never at enrolment. | Pending legal review (cross-border transfer) |
| 3.11 | Advisory SMS after review | One short advice SMS per reviewed photo in the farmer's language, only with SMS consent; recorded, not sent while SMS_MODE is log. Each says payouts follow the ward rain index. Kiswahili pending native-speaker review. | Built |
| 3.12 | Picture-based rider | Damage report and reviewer assessment built; ILLUSTRATIVE rate 2% of sum insured and payout shares 0, 0, 25%, 50%, 80% by damage band; switched off in quotes (`rider.enabled_in_quotes: false`); the farmer screen shows only in development. Assessments never create a payout. | Needs owner approval |
| 3.13 | Farmer weather tab | Approved summaries for the farmer's SACCO plus the every-SACCO ones, in the farmer's language first with the other one-tap away, labelled with the source ("Source: KMD"). No SMS of KMD content. | Built (brief) |
| 3.14 | Photo storage | Re-encoded JPEG without metadata under `var/photos` (git-ignored), named by SHA-256; positions and times in the database. No retention period set yet. | Needs owner approval (retention) |
| 3.15 | Underwriter navbar | "Photos" added; "Reinsurer summary" shortened to "Reinsurer" in the navbar (the page title is unchanged) so eight links still fit on one row at 1440 px. | Built |

### Phase 3 review fixes (docs/remaining/REVIEW_PHASE3.md)

| # | Decision | Default used | Status |
|---|---|---|---|
| 3.16 | Photos without a confirmed place or time | Still accepted and reviewed, but they count toward the Resilience photo point only after a reviewer clears them: no GPS, no plot location, far from the farm with a weak fix, or a gallery file with no camera time. | Built |
| 3.17 | Coarse GPS | Refused only when the photo is clearly more than 250 m away even allowing for the phone's stated accuracy; otherwise flagged for the reviewer. | Built |
| 3.18 | Shared phones | Each farmer signs in with their own PIN; the offline queue belongs to whoever took the photo and is sent only when they are signed in. Signing out clears their cached farm list and pages. | Built |
| 3.19 | Lost phones | The officer can turn the photo app off for a member (every session ends); a PIN reset also signs every phone out. | Built |
| 3.20 | Sign-in messages | The same message for an unknown phone, a wrong PIN and a locked account, so the page cannot reveal who is registered. | Built |

### Phase 4: hardware layer (milestone 9)

| # | Decision | Default used | Status |
|---|---|---|---|
| 4.1 | Which devices an underwriter sees | Every device in the pilot wards, with wards where the underwriter's insurer has cover listed first and marked "your cover". Devices are shared platform equipment, hold no personal data and say nothing about another insurer's book, and a new insurer should see the network before writing cover. | Pending owner confirmation |
| 4.2 | Device authentication (new credential type; the officer auth and role model is unchanged) | Each device has its own key: 256 random bits, shown once, stored only as a SHA-256 hash (as strong as a slow hash at that entropy, and cheap per upload). Sent in `X-Device-Id` / `X-Device-Key` headers over TLS, or inside the MQTT payload; never in a URL. Wrong keys are noted on the device at most once per 10 minutes. Keys can be rotated and devices retired. | Built |
| 4.3 | LoRaWAN authentication | LoRaWAN devices hold no AgroShield key: the network authenticates them with their LoRaWAN session keys, and the network server signs in to the webhook with an integration key (`device_integration`, hash only). | Built |
| 4.4 | Idempotency | One stored message per device and message id. Same content again: "duplicate" (harmless). Same id, different content: "conflict", not stored. LoRaWAN readings use the node's sequence number and day, and an identity that ignores the age and flags bytes and the radio signal, so a resent stored reading is stored once. | Built |
| 4.5 | Validation | Physical ranges per reading and device kind; times must have a zone, be no more than 10 minutes in the future, not before 2024 and not older than 90 days (the store-and-forward window). Any bad value refuses the whole message, with reasons, listed on the device's page. | Built |
| 4.6 | Device health | Late after two report intervals; "Not heard from" after six intervals or 24 hours, whichever is longer. Report interval: camera 720 minutes, soil and rain 60. Battery low under 3.45 V (camera) or 3.3 V (others). A late batch never overwrites the newest battery or signal. | DRAFT thresholds |
| 4.7 | Greenness index | Image-mean green chromatic coordinate, excess green (2g - r - b) and the share of plant-like pixels (excess green above 0.10), analysed at 512 px; photos with under 5% usable pixels refused as too dark. | DRAFT threshold |
| 4.8 | Photo storage and access | JPEG files next to a SQLite database (`device_images/`) or in `AGROSHIELD_DEVICE_STORE`, named by hash; shown only to signed-in underwriters. Retention period not set. | Needs approval (retention) |
| 4.9 | Rain gauge check against CHIRPS | 10-day totals against the ward CHIRPS file in the repo (gaps over 30 mm and a factor of 3; zero in a wet dekad is "possible blocked funnel"), only for dekads the gauge fully reported; single days above twice the wettest CHIRPS day on record for the month. Flags are for people; they never change data or payouts. | DRAFT thresholds |
| 4.10 | Sentinel camera defaults | Photos at 10:00 and 13:00 East Africa Time; GSM (SIM800L) in the default `esp32cam` build, Wi-Fi in `esp32cam-wifi`; SD queue of 400 photos, oldest dropped first; at most 12 uploads per wake. | Built (not tested on hardware) |
| 4.11 | Soil and rain payloads | Compact big-endian binary, version byte first, age field for store and forward (byte layouts in docs/hardware). The server decodes raw bytes itself; a TTN JavaScript formatter is provided for the console and tested equal. The Things Stack and ChirpStack webhooks both accepted. | Built |
| 4.12 | Device administration | A separate command, `python -m agroshield_platform.devices` (register, rotate-key, retire, add-integration, list, mqtt-bridge), so shared modules (`cli.py`) are untouched. No web screen for registering devices yet. | Built |
| 4.13 | MQTT | A bridge process (paho-mqtt, optional extra `agroshield[hardware]`) subscribed to `agroshield/v1/devices/+/up`, answering on `.../ack`; it checks the device key itself, so a broker misconfiguration cannot let one device write as another. | Built (tested with a stand-in client, not a live broker) |
| 4.14 | Underwriter navbar | "Devices" added as the eighth link; underwriter links use 8 px side padding instead of 12 px (app.css) so the bar still fits at 1280 px and wider. | Built |
| 4.15 | Simulator clock | The simulator sets `app.state.device_clock` (in-process only) so readings arrive at simulated times; unset, the server uses the real clock. | Built |
| 4.16 | TAHMO | Labelled stub raising `TahmoBlocked`; no sign-up or contact. | Blocked (credentials) |
