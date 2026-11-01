# Review of the Phase 3 commit (ceda707)

Five independent reviewers (privacy, checks, web security, the offline app, product rules) read the commit; a skeptic tried to refute each finding.
28 findings were confirmed (several are the same issue seen by two reviewers) and all are fixed; 5 were refuted. Tests: tests/test_photos_review.py.

| # | Severity | Finding | Outcome |
|---|---|---|---|
| 1 | medium | JPEG comment (COM) metadata survives stripping, reaches stored files and the Anthropic API, and is not caught by has_metadata (`src/agroshield_platform/photos.py:152`) | Fixed: images are rebuilt from pixels only before storing and before sending; has_metadata now rejects comments and APP1 to APP15 segments. |
| 2 | medium | Resetting a farmer's PIN does not sign out existing app sessions, and there is no way to deactivate an app user (`src/agroshield_platform/photos.py:173`) | Fixed: a sign-in version on each app user (migration 0004a); a PIN reset or the new 'Turn off the photo app' ends every session. |
| 3 | medium | Signing out leaves the previous farmer's data on the phone and lets their queued photos upload under the next user's session (`src/agroshield_platform/web/static/app/sw.js:36`) | Fixed with 19. |
| 4 | low | PIN sign-in reveals whether a phone number is registered (lockout message and reversed timing equaliser) (`src/agroshield_platform/photos.py:189`) | Fixed with 16. |
| 5 | high | Missing GPS (or no plot location) skips the distance rule and the photo still earns the Resilience photo point (`src/agroshield_platform/photos.py:333`) | Fixed with 27. |
| 6 | medium | App strips EXIF in the browser and sets taken_at to the time of picking, so the metadata checks never run and old gallery photos look new (`src/agroshield_platform/web/static/app/photoapp.js:149`) | Fixed: gallery files are uploaded as the original (the server strips them), so camera time and GPS are checked; a gallery file with no camera time is flagged. |
| 7 | medium | Distance rule hard-rejects genuine photos when the GPS fix is coarse (`src/agroshield_platform/photos.py:370`) | Fixed: refused only when the distance minus the phone's stated accuracy is over 250 m; otherwise flagged 'far_or_low_accuracy' and reviewed. |
| 8 | medium | Perceptual-hash check compares against every photo ever, so photos lined up with the ghost get flagged as 'duplicate' (`src/agroshield_platform/photos.py:351`) | Fixed: same-plot 'duplicate' only for the same bytes or a near-identical picture of the same stage within two days. |
| 9 | low | Duplicate search ignores rejected photos, so a picture refused for distance can be resent clean (`src/agroshield_platform/photos.py:351`) | Fixed: a match with a refused picture is flagged 'previously_rejected' (a fraud flag). |
| 10 | medium | Login only tries the first farmer for a phone number, so a shared phone locks out household members (`src/agroshield_platform/photos.py:191`) | Fixed: every active account on the phone number is tried; household members keep their own PINs. |
| 11 | low | Champion assignments cannot be removed, and old ones come back when the role is reset (`src/agroshield_platform/photos.py:173`) | Fixed: officers can remove a champion's farm; a champion reset to farmer loses the assignments. |
| 12 | low | ghost() returns the newest photo at any point within the radius, not the nearest photo point (`src/agroshield_platform/photos.py:388`) | Fixed: the nearest photo point is chosen first, and flagged photos are never used as the ghost. |
| 13 | medium | PIN lockout counter loses updates under concurrent logins, so 6-digit PINs can be brute-forced much faster than 5 tries per 30 minutes (`src/agroshield_platform/photos.py:194`) | Fixed: the failure counter is raised in the database before the PIN is checked. |
| 14 | medium | Logout leaves the farmer's data on the phone: service worker caches no-store JSON and photos; localStorage and the IndexedDB queue survive and are shown to, and sent by, the next user (`src/agroshield_platform/web/static/app/sw.js:36`) | Fixed with 19. |
| 15 | medium | Photo with no GPS skips the 250 m distance rejection and still earns the Resilience photo point (`src/agroshield_platform/photos.py:333`) | Fixed with 27. |
| 16 | low | Phone number enumeration on /app/login via the lockout message and response timing (`src/agroshield_platform/photos.py:189`) | Fixed: one scrypt check and the same message on every path (unknown phone, wrong PIN, locked). |
| 17 | low | Malformed or hostile upload input returns 500s instead of a 4xx (non-dict meta or JSON, non-numeric, NaN or inf coordinates, decompression bombs) (`src/agroshield_platform/web/photo_app.py:177`) | Fixed: non-object meta, non-finite or out-of-range coordinates are form errors; images over 50 megapixels are refused before decoding. |
| 18 | low | Underwriter photo page shows the 'previous photo from the same spot' without checking that it belongs to the same insurer (`src/agroshield_platform/web/photo_app.py:361`) | Fixed: the earlier photo from the same spot is limited to the underwriter's own insurer. |
| 19 | high | Shared phone: signing out leaves the previous farmer's data cached, and their queued photos are sent under the next user's session (`src/agroshield_platform/web/static/app/sw.js:35`) | Fixed: queue and sent list tagged with an opaque per-user key and only sent or shown for that user; the service worker never stores the API or photos; signing out clears the person's cached data and warns about unsent photos. |
| 20 | medium | One bad queue item blocks the whole upload queue forever and cannot be removed (`src/agroshield_platform/web/static/app/photoapp.js:223`) | Fixed: one item's server error no longer stops the queue; after five tries it shows with Remove. |
| 21 | medium | Service worker caches error responses for static files forever and never updates the app script (`src/agroshield_platform/web/static/app/sw.js:26`) | Fixed: only good answers are cached; scripts and styles refresh in the background (cache v2). |
| 22 | low | Pre-caching sign-in-only pages at install stores redirected login responses, so offline tabs fail with a browser error (`src/agroshield_platform/web/static/app/sw.js:6`) | Fixed: sign-in pages are no longer pre-cached; pages are cached only after a good signed-in visit. |
| 23 | low | An expired session makes the app jump to the sign-in page as soon as signal returns, even with the camera open (`src/agroshield_platform/web/static/app/photoapp.js:237`) | Fixed: an expired session shows 'Sign in again' and keeps the camera and queue working. |
| 24 | low | Camera screen: focus is not managed and queue changes are not announced (`src/agroshield_platform/web/static/app/photoapp.js:84`) | Fixed: focus moves to the camera heading and back; a status line announces saved and sent photos. |
| 25 | low | Kiswahili users see English-only text, and English text inside a Kiswahili page has no lang attribute (`src/agroshield_platform/web/static/app/photoapp.js:207`) | Fixed: all app messages and flag words in Kiswahili; the English-only rider screen is marked lang=en. |
| 26 | low | Opening the camera for a second farm leaves the first camera stream and GPS watch running (`src/agroshield_platform/web/static/app/photoapp.js:87`) | Fixed: opening a second farm stops the first camera and GPS watch. |
| 27 | high | Photos without a GPS fix (or on a plot with no recorded location) skip the 250 m check and still earn the Resilience photo point (`src/agroshield_platform/photos.py:333`) | Fixed: photos with no GPS, no plot location, a coarse fix far away or no camera time count toward the photo point only after a reviewer clears them. |
| 28 | medium | The app re-encodes every image in the browser, so the camera-time and camera-GPS checks never fire and a gallery picture gets a fresh timestamp (`src/agroshield_platform/web/static/app/photoapp.js:149`) | Fixed with 6. |

## Refuted

- Farmer photos are sent abroad under photo_ai wording that is still pending legal review, with no gate for live SACCOs
- on_schedule and policy_id come from the plot's newest policy, not the policy covering taken_at
- Non-numeric or non-finite lat/lon/accuracy cause unhandled 500 errors
- The photo point carries over from any earlier same-season policy, however old, not only from last season
- Unreviewed photos and photos an agronomist tags as not a crop still count toward the photo point
