"""Milestone 8 web routes: the farmer photo app (a progressive web app under /app), the officer's set-up on the
member page, and the underwriter's photo review queue (/uw/photos).

Farmer app
  /app                      the app: plots, camera with the ghost of the last photo, an offline queue that sends
                            when signal returns (static/app/photoapp.js, service worker /app/sw.js)
  /app/login, /app/logout   phone number and PIN (set up by the SACCO officer)
  /app/api/me               plots, stages and progress (JSON, no ID or phone numbers)
  /app/api/photos           POST one photo (multipart); idempotent on the app's photo id
  /app/api/ghost/{plot}     POST the phone's position, get the last photo from the nearest photo point
  /app/photos/{ref}.jpg     a photo the signed-in farmer may see
  /app/weather              approved KMD summaries for the farmer's SACCO (English and Kiswahili, "Source: KMD")
  /app/consent              the separate "photo analysis by an AI service" choice (pending legal review)
  /app/damage               picture-based rider damage report (ILLUSTRATIVE, development only, not on sale)

Officer (member page): set up the app (PIN shown once), champion farmers and their plots, the photo_ai choice.
Underwriter: /uw/photos queue, one photo with its checks and the AI suggestion, the reviewer's decision.

Personal data stays out of URLs (photo refs and plot ids only; positions go in POST bodies).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from .. import locale as L
from .. import photos as ph
from .. import weather as wx
from ..db import transaction
from ..models import AppUser, Farmer, Photo, PhotoReview, PhotoSuggestion, Plot, Policy, RiderClaim

HERE = Path(__file__).parent

# The app's own words (short; Kiswahili pending native-speaker review like the rest of the Kiswahili text).
WORDS = {
    "en": {"title": "Crop photos", "sign_in": "Sign in", "phone": "Phone number", "pin": "PIN from your SACCO",
           "farms": "Your farms", "take": "Take a photo", "stage": "Growth stage", "queue": "Waiting to send",
           "sent": "Sent", "offline": "No signal. Photos wait on this phone and send by themselves later.",
           "weather": "Weather", "photos": "Photos", "sign_out": "Sign out", "ai": "AI photo checks",
           "due": "Due now", "done": "Done", "not_yet": "Not yet", "damage": "Report crop damage",
           "acres": "acres", "no_farm": "No farm is linked to you yet. Ask your SACCO officer.",
           "gps_none": "No GPS on this phone.", "gps_off": "Location is off. Turn it on so the photo can be checked.",
           "gps_within": "GPS: within {m} m", "remove": "Remove", "not_accepted": "not accepted",
           "received": "received", "outside": "outside this stage's dates", "to_check": "to check",
           "could_not_send": "Could not send. It will try again.", "saved": "Saved on this phone. It sends when there is signal.",
           "sign_in_again": "Sign in again to send your photos.", "hello": "Hello",
           "unsent_out": "{n} photos have not been sent yet. They stay on this phone and send the next time you sign in. Sign out?"},
    "sw": {"title": "Picha za mazao", "sign_in": "Ingia", "phone": "Nambari ya simu", "pin": "PIN kutoka SACCO yako",
           "farms": "Mashamba yako", "take": "Piga picha", "stage": "Hatua ya ukuaji", "queue": "Zinasubiri kutumwa",
           "sent": "Zimetumwa", "offline": "Hakuna mtandao. Picha zinasubiri kwenye simu na zitatumwa zenyewe baadaye.",
           "weather": "Hali ya hewa", "photos": "Picha", "sign_out": "Toka", "ai": "Ukaguzi wa picha kwa AI",
           "due": "Wakati wake sasa", "done": "Imekamilika", "not_yet": "Bado", "damage": "Ripoti uharibifu wa mazao",
           "acres": "ekari", "no_farm": "Hakuna shamba lililounganishwa nawe bado. Muulize afisa wa SACCO yako.",
           "gps_none": "Simu hii haina GPS.", "gps_off": "Mahali pamezimwa. Pawashe ili picha ikaguliwe.",
           "gps_within": "GPS: ndani ya mita {m}", "remove": "Ondoa", "not_accepted": "haikukubaliwa",
           "received": "imepokelewa", "outside": "nje ya tarehe za hatua hii", "to_check": "ya kukagua",
           "could_not_send": "Haikutumwa. Itajaribu tena.", "saved": "Imehifadhiwa kwenye simu. Itatumwa kukiwa na mtandao.",
           "sign_in_again": "Ingia tena ili kutuma picha zako.", "hello": "Habari",
           "unsent_out": "Picha {n} bado hazijatumwa. Zitabaki kwenye simu na kutumwa utakapoingia tena. Utoke?"},
}


def register(app, d) -> None:
    """d: the portal's helpers (factory, render, templates, cfg, ctx, require, check_csrf, csrf, vault, settings,
    flush_sms, own_farmer). Kept in one place so the photo app needs only one line in create_app."""
    factory, render, cfg, settings = d.factory, d.render, d.cfg, d.settings
    pcfg = ph.config(cfg.root)
    store = Path(settings.photo_dir) if getattr(settings, "photo_dir", None) else Path(cfg.root).parent / pcfg["storage_dir"]
    wording = d.wording

    def now() -> datetime:
        return d.ctx().now().astimezone(timezone.utc)

    def app_user(request: Request, s) -> AppUser | None:
        """The signed-in farmer, if their sign-in is still valid (a PIN reset or a disable ends every session)."""
        uid = request.session.get("app_user_id")
        u = s.get(AppUser, uid) if uid else None
        if u is None or not u.active or request.session.get("app_ver") != (u.session_version or 0):
            return None
        return u

    def owner_key(u: AppUser) -> str:
        """An opaque, stable id for this app user on the phone (tags the offline queue); no personal data."""
        return hmac.new(settings.session_secret.encode(), f"app-user:{u.id}".encode(), hashlib.sha256).hexdigest()[:20]

    def need_user(request: Request, s, api: bool = False) -> AppUser:
        u = app_user(request, s)
        if u is None:
            if api:
                raise HTTPException(401, "Sign in again.")
            raise HTTPException(303, headers={"Location": "/app/login"})
        return u

    def check_header_csrf(request: Request) -> None:
        tok = request.headers.get("x-csrf-token", "")
        if not tok or tok != request.session.get("csrf"):
            raise HTTPException(403, "Sign in again.")

    def lang(u: AppUser | None) -> str:
        return u.farmer.language if u and u.farmer.language in WORDS else "en"

    def page(request: Request, name: str, u: AppUser | None, status: int = 200, **kw):
        lg = lang(u)
        return d.templates.TemplateResponse(request, f"app/{name}", {
            "u": u, "lg": lg, "w": WORDS[lg], "csrf": d.csrf(request), "dev_keys": settings.dev_keys,
            "rider_demo": settings.dev_keys and not ph.rider_offered(pcfg), "flash": request.session.pop("flash", None),
            **kw}, status_code=status)

    def plot_label(plot: Plot, u: AppUser) -> str:
        if plot.farmer_id == u.farmer_id:
            return f"{L.first_name(plot.farmer.full_name)}'s farm" if lang(u) == "en" else f"Shamba la {L.first_name(plot.farmer.full_name)}"
        return f"{L.first_name(plot.farmer.full_name)} ({plot.farmer.member_no})"

    def can_see(s, u: AppUser, photo: Photo) -> bool:
        return photo.plot_id in {p.id for p in ph.plots_for(s, u)}

    # ------------------------------------------------------------------ PWA shell, manifest and service worker
    @app.get("/app/manifest.webmanifest")
    def manifest():
        return JSONResponse({
            "name": "AgroShield crop photos", "short_name": "Crop photos", "start_url": "/app", "scope": "/app",
            "display": "standalone", "background_color": "#0B1F17", "theme_color": "#0F766E",
            "icons": [{"src": "/static/app/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/app/icon-512.png", "sizes": "512x512", "type": "image/png"}]},
            media_type="application/manifest+json")

    @app.get("/app/sw.js")
    def service_worker():
        return Response((HERE / "static" / "app" / "sw.js").read_bytes(), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/app", "Cache-Control": "no-cache"})

    @app.get("/app", response_class=HTMLResponse)
    def app_home(request: Request):
        with transaction(factory) as s:
            u = app_user(request, s)
            if u is None:
                return RedirectResponse("/app/login", status_code=303)
            return page(request, "home.html", u, stages=pcfg["stages"])

    @app.get("/app/login", response_class=HTMLResponse)
    def app_login_form(request: Request):
        return page(request, "login.html", None)

    @app.post("/app/login")
    def app_login(request: Request, phone: str = Form(""), pin: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            try:
                u = ph.authenticate(s, d.vault, phone, pin, pcfg, now())
            except ph.PhotoError as e:
                return page(request, "login.html", None, status=401, error=str(e))
            csrf = request.session.get("csrf")
            request.session.clear()
            request.session["app_user_id"], request.session["csrf"] = u.id, csrf or secrets.token_urlsafe(24)
            request.session["app_ver"] = u.session_version or 0
        return RedirectResponse("/app", status_code=303)

    @app.post("/app/logout")
    def app_logout(request: Request, csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse("/app/login", status_code=303)

    # ------------------------------------------------------------------ JSON for the app
    @app.get("/app/api/me")
    def app_me(request: Request):
        with transaction(factory) as s:
            u = need_user(request, s, api=True)
            today = d.ctx().date()
            plots = []
            for plot in ph.plots_for(s, u):
                pol = ph.latest_policy(s, plot)
                stages = []
                done = ph.photo_point_earned(s, pcfg, pol)["stages"] if pol else {}
                for key, st in pcfg["stages"].items():
                    a, b = ph.stage_window(pcfg, cfg, pol, key) if pol else (None, None)
                    stages.append({"key": key, "label": st[lang(u)], "from": a.isoformat() if a else None,
                                   "to": b.isoformat() if b else None, "done": bool(done.get(key)),
                                   "due": bool(a and a <= today <= b)})
                plots.append({"id": plot.id, "label": plot_label(plot, u), "acres": plot.acreage,
                              "has_location": plot.lat is not None, "season": pol and f"{pol.season} {pol.year}",
                              "stages": stages, "photos": len(s.scalars(select(Photo.id).where(Photo.plot_id == plot.id)).all())})
            return JSONResponse({"user": {"name": L.first_name(u.farmer.full_name), "role": u.role, "lang": lang(u),
                                          "key": owner_key(u)},
                                 "csrf": d.csrf(request), "plots": plots, "words": WORDS[lang(u)]},
                                headers={"Cache-Control": "no-store"})

    @app.post("/app/api/photos")
    async def app_upload(request: Request, background: BackgroundTasks, file: UploadFile, meta: str = Form("{}"),
                         plot_id: str = Form("")):
        check_header_csrf(request)
        data = await file.read(pcfg["max_upload_mb"] * 1_000_000 + 1)
        try:
            m = json.loads(meta)
        except ValueError:
            m = None
        if not isinstance(m, dict):
            return JSONResponse({"ok": False, "error": "Update the app and try again."}, status_code=422)
        with transaction(factory) as s:
            u = need_user(request, s, api=True)
            try:
                p = ph.submit(s, cfg, pcfg, u, plot_id, data, m, store, now())
            except ph.PhotoError as e:
                return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
            lg = lang(u)
            reason = p.reject_reason
            if p.status == "rejected" and lg == "sw" and p.distance_m is not None:
                reason = (f"Ilipigwa mita {p.distance_m:,.0f} kutoka shamba lililosajiliwa "
                          f"(kikomo ni mita {pcfg['checks']['max_distance_m']}).")
            out = {"ok": True, "ref": p.ref, "status": p.status, "reason": reason, "on_schedule": p.on_schedule,
                   "flags": [ph.FLAG_WORDS[lg].get(f, f) for f in p.flags]}
            pid = p.id
        if out["status"] != "rejected":
            background.add_task(suggest_later, pid)
        return JSONResponse(out)

    def suggest_later(photo_id: int) -> None:
        with transaction(factory) as s:
            p = s.get(Photo, photo_id)
            if p is not None:
                ph.suggest(s, pcfg, p, caller=d.ai_caller)

    @app.post("/app/api/ghost/{plot_id}")
    async def app_ghost(request: Request, plot_id: str):
        check_header_csrf(request)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        try:
            lat, lon = ph.number(body.get("lat"), -90, 90), ph.number(body.get("lon"), -180, 180)
        except ph.PhotoError as e:
            return JSONResponse({"error": str(e)}, status_code=422)
        with transaction(factory) as s:
            u = need_user(request, s, api=True)
            plot = s.get(Plot, plot_id)
            if plot is None or plot.id not in {p.id for p in ph.plots_for(s, u)}:
                raise HTTPException(404)
            g = ph.ghost(s, plot, lat, lon, pcfg["checks"]["photo_point_radius_m"])
            return JSONResponse({"url": f"/app/photos/{g.ref}.jpg", "stage": g.stage} if g else {})

    @app.get("/app/photos/{ref}.jpg")
    def app_photo(request: Request, ref: str):
        with transaction(factory) as s:
            u = need_user(request, s, api=True)
            p = s.scalar(select(Photo).where(Photo.ref == ref))
            if p is None or not can_see(s, u, p):
                raise HTTPException(404)
            return FileResponse(p.file_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    # ------------------------------------------------------------------ weather tab, consent, damage report
    @app.get("/app/weather", response_class=HTMLResponse)
    def app_weather(request: Request):
        with transaction(factory) as s:
            u = need_user(request, s)
            items = wx.visible_items(s, d.ctx().date(), [u.farmer.sacco_id])
            return page(request, "weather.html", u, items=items)

    @app.get("/app/consent", response_class=HTMLResponse)
    def app_consent(request: Request):
        with transaction(factory) as s:
            u = need_user(request, s)
            return page(request, "consent.html", u, wording=wording["purposes"]["photo_ai"],
                        granted=ph.consent_granted(s, u.farmer_id, "photo_ai"))

    @app.post("/app/consent")
    def app_consent_post(request: Request, choice: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            u = need_user(request, s)
            ph.record_consent(s, u.farmer, "photo_ai", choice == "yes", wording, "app", f"app:{u.id}")
        request.session["flash"] = ["ok", "Saved." if lang(u) == "en" else "Imehifadhiwa."]
        return RedirectResponse("/app/consent", status_code=303)

    @app.get("/app/damage", response_class=HTMLResponse)
    def app_damage(request: Request):
        with transaction(factory) as s:
            u = need_user(request, s)
            if not (settings.dev_keys or ph.rider_offered(pcfg)):
                raise HTTPException(404)
            pols = [pol for plot in ph.plots_for(s, u) if (pol := ph.latest_policy(s, plot))]
            recent = {pol.id: list(s.scalars(select(Photo).where(Photo.policy_id == pol.id, Photo.status != "rejected")
                                             .order_by(Photo.taken_at.desc()).limit(6))) for pol in pols}
            return page(request, "damage.html", u, policies=pols, recent=recent, causes=pcfg["rider"]["causes"],
                        labels={pol.id: plot_label(pol.plot, u) for pol in pols})

    @app.post("/app/damage")
    async def app_damage_post(request: Request):
        form = await request.form()
        d.check_csrf(request, form.get("csrf_token", ""))
        with transaction(factory) as s:
            u = need_user(request, s)
            if not (settings.dev_keys or ph.rider_offered(pcfg)):
                raise HTTPException(404)
            pol = s.get(Policy, form.get("policy_id", ""))
            try:
                if pol is None:
                    raise ph.PhotoError("Choose the farm.")
                c = ph.report_damage(s, pcfg, u, pol, form.get("cause", ""), form.get("note", ""), form.getlist("photo"))
                request.session["flash"] = ["ok", f"Recorded as {c.ref}. A reviewer will look at it."]
            except ph.PhotoError as e:
                request.session["flash"] = ["crit", str(e)]
        return RedirectResponse("/app/damage", status_code=303)

    # ------------------------------------------------------------------ officer: set up on the member page
    @app.post("/members/{farmer_id}/app-user")
    def officer_app_user(request: Request, farmer_id: str, role: str = Form("farmer"), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s)
            f = d.own_farmer(s, off, farmer_id)
            try:
                _, pin = ph.set_up_user(s, f, off.username, role)
            except ph.PhotoError as e:
                return d.member_page(request, s, off, f, status=422, app_error=str(e))
            # Shown once on this page (never stored in clear, never put in the session cookie).
            return d.member_page(request, s, off, f, new_pin=pin)

    @app.post("/members/{farmer_id}/app-assign")
    def officer_assign(request: Request, farmer_id: str, member_no: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s)
            f = d.own_farmer(s, off, farmer_id)
            user = s.scalar(select(AppUser).where(AppUser.farmer_id == f.id))
            other = s.scalar(select(Farmer).where(Farmer.sacco_id == off.sacco_id, Farmer.member_no == member_no.strip()))
            try:
                if user is None or other is None:
                    raise ph.PhotoError("Set up the champion farmer first, and enter a member number from your SACCO.")
                for plot in other.plots:
                    ph.assign(s, user, plot, off.username)
                request.session["flash"] = ["ok", f"Member {other.member_no}'s farm added for this champion farmer."]
            except ph.PhotoError as e:
                request.session["flash"] = ["crit", str(e)]
        return RedirectResponse(f"/members/{farmer_id}#photo-app", status_code=303)

    @app.post("/members/{farmer_id}/app-disable")
    def officer_app_disable(request: Request, farmer_id: str, csrf_token: str = Form("")):
        """Turn the photo app off for this member (a lost phone, a champion who left): signs every phone out."""
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s)
            f = d.own_farmer(s, off, farmer_id)
            user = s.scalar(select(AppUser).where(AppUser.farmer_id == f.id))
            if user is not None:
                ph.disable_user(s, user, off.username)
        request.session["flash"] = ["ok", "The photo app is turned off for this member. Set it up again to give a new PIN."]
        return RedirectResponse(f"/members/{farmer_id}#photo-app", status_code=303)

    @app.post("/members/{farmer_id}/app-unassign/{plot_id}")
    def officer_unassign(request: Request, farmer_id: str, plot_id: str, csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s)
            f = d.own_farmer(s, off, farmer_id)
            user = s.scalar(select(AppUser).where(AppUser.farmer_id == f.id))
            plot = s.get(Plot, plot_id)
            if user is None or plot is None or plot.farmer.sacco_id != off.sacco_id:
                raise HTTPException(404)
            ph.unassign(s, user, plot, off.username)
        request.session["flash"] = ["ok", "Farm removed from this champion farmer's list."]
        return RedirectResponse(f"/members/{farmer_id}#photo-app", status_code=303)

    @app.post("/members/{farmer_id}/photo-consent")
    def officer_photo_consent(request: Request, farmer_id: str, choice: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s)
            f = d.own_farmer(s, off, farmer_id)
            ph.record_consent(s, f, "photo_ai", choice == "yes", wording, "portal", off.username, captured_by=off.id)
        request.session["flash"] = ["ok", "The farmer's choice on AI photo checks is recorded."]
        return RedirectResponse(f"/members/{farmer_id}#photo-app", status_code=303)

    # ------------------------------------------------------------------ underwriter: review queue
    def uw_photo(s, off, ref: str) -> Photo:
        p = s.scalar(select(Photo).where(Photo.ref == ref))
        if p is None or p.policy_id is None or s.get(Policy, p.policy_id).insurer_id != off.insurer_id:
            raise HTTPException(404)
        return p

    def insurer_policies(s, off) -> set[str]:
        return {pid for (pid,) in s.execute(select(Policy.id).where(Policy.insurer_id == off.insurer_id))}

    @app.get("/uw/photos", response_class=HTMLResponse)
    def uw_photos(request: Request):
        with transaction(factory) as s:
            off = d.require(request, s, role="underwriter")
            pids = insurer_policies(s, off)
            queue = ph.queue_for(s, pids)
            done = [p for p in s.scalars(select(Photo).where(Photo.status.in_(("reviewed", "rejected")))
                                         .order_by(Photo.received_at.desc()).limit(60)) if p.policy_id in pids][:30]
            reviews = {r.photo_id: r for r in s.scalars(select(PhotoReview).where(PhotoReview.photo_id.in_([p.id for p in done] or [-1])))}
            claims = [c for c in s.scalars(select(RiderClaim).order_by(RiderClaim.created_at.desc()).limit(50)) if c.policy_id in pids]
            sugg = {g.photo_id: g for g in s.scalars(select(PhotoSuggestion).where(PhotoSuggestion.photo_id.in_([p.id for p in queue] or [-1])))}
            return render(request, "uw_photos.html", off, queue=queue, done=done, reviews=reviews, claims=claims,
                          sugg=sugg, tags=ph.TAGS, extents=ph.EXTENTS, flag_words=ph.FLAG_WORDS["en"], pcfg=pcfg,
                          rider_on=ph.rider_offered(pcfg), fraud=ph.FRAUD_FLAGS)

    @app.get("/uw/photos/{ref}.jpg")
    def uw_photo_file(request: Request, ref: str):
        with transaction(factory) as s:
            off = d.require(request, s, role="underwriter")
            p = uw_photo(s, off, ref.removesuffix(".jpg"))
            return FileResponse(p.file_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/uw/photos/{ref}", response_class=HTMLResponse)
    def uw_photo_page(request: Request, ref: str):
        with transaction(factory) as s:
            off = d.require(request, s, role="underwriter")
            p = uw_photo(s, off, ref)
            sug = s.scalar(select(PhotoSuggestion).where(PhotoSuggestion.photo_id == p.id))
            rev = s.scalar(select(PhotoReview).where(PhotoReview.photo_id == p.id))
            pol = s.get(Policy, p.policy_id)
            prev = s.scalar(select(Photo).where(Photo.photo_point_id == p.photo_point_id, Photo.id != p.id,
                                                Photo.photo_point_id.is_not(None), Photo.taken_at < p.taken_at,
                                                Photo.policy_id.in_(insurer_policies(s, off)))
                            .order_by(Photo.taken_at.desc()))
            window = ph.stage_window(pcfg, cfg, pol, p.stage)
            return render(request, "uw_photo.html", off, p=p, sug=sug, rev=rev, pol=pol, prev=prev, window=window,
                          tags=ph.TAGS, extents=ph.EXTENTS, flag_words=ph.FLAG_WORDS["en"], stages=pcfg["stages"],
                          fraud=ph.FRAUD_FLAGS, unverified=ph.UNVERIFIED_FLAGS)

    @app.post("/uw/photos/{ref}/review")
    def uw_photo_review(request: Request, background: BackgroundTasks, ref: str, tag: str = Form(""),
                        extent: str = Form(""), note: str = Form(""), clear_flags: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s, role="underwriter")
            p = uw_photo(s, off, ref)
            try:
                ph.review(s, p, off.username, tag, extent, note, bool(clear_flags), settings.ussd_code)
                request.session["flash"] = ["ok", f"{p.ref} reviewed: {ph.TAGS[tag]}."]
                background.add_task(d.flush_sms)
            except ph.PhotoError as e:
                request.session["flash"] = ["crit", str(e)]
                return RedirectResponse(f"/uw/photos/{ref}", status_code=303)
        return RedirectResponse("/uw/photos", status_code=303)

    @app.post("/uw/photos/claims/{ref}/assess")
    def uw_claim_assess(request: Request, ref: str, extent: str = Form(""), csrf_token: str = Form("")):
        d.check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = d.require(request, s, role="underwriter")
            c = s.scalar(select(RiderClaim).where(RiderClaim.ref == ref))
            if c is None or c.policy.insurer_id != off.insurer_id:
                raise HTTPException(404)
            try:
                ph.assess(s, pcfg, c, off.username, extent, now())
                request.session["flash"] = ["ok", f"{c.ref} assessed (illustrative only, nothing is paid)."]
            except ph.PhotoError as e:
                request.session["flash"] = ["crit", str(e)]
        return RedirectResponse("/uw/photos#claims", status_code=303)

    app.state.photo_store = store
