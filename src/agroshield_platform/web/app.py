"""SACCO officer portal (server-rendered: FastAPI + Jinja2, no JavaScript build).

Pages
  /                    public landing page for farmers and SACCOs
  /login, /logout      officer sign-in (scrypt passwords, signed session cookie)
  /dashboard           officer Home: who still owes, payment reminders, ward alerts, Enrol
  /enrol               enrolment wizard, one step per screen: farmer, farm, agreement, price and pay
  /quote               quick price, no enrolment
  /members             members (national ID and phone masked); cover, payments, Details
  /reports             managers: portfolio, sales windows, subsidy receivable, ward map, export
  /import              managers: bulk enrolment from CSV (check, then all-or-nothing) and KIAMIS import
  /payouts             Payout Tracker: ward rainfall status, payouts, missed-payout reports
  /weather             managers: KMD advisories, review and approve summaries (display only)
  /sms, /dev/mpesa     Developer menu (development mode only): SMS log, M-Pesa simulator
  /uw/...              Underwriter workspace (role underwriter only; its own insurer's book only): portfolio,
                       triggers and payout approval, money, bordereaux, pricing runs and audit, reinsurer summary

Two audiences: officers get plain language and their next task; pricing and portfolio
detail sits under Reports and behind "Details" toggles.
  /export/policies.csv policy export, masked

Callbacks (no session; a secret token in the path, never personal data)
  POST /ussd/{token}             Africa's Talking USSD
  POST /mpesa/callback/{token}   Safaricom STK push results

Personal data never goes into URLs or cookies. A half-finished enrolment is held
server-side under a random token (in memory: one process, cleared on restart).
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path

import jinja2
from markupsafe import Markup
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from agroshield_pricing.config import load_config
from agroshield_pricing.quote import QuoteError, RateBook, quote

from .. import enquiries as enq
from .. import locale as L
from .. import monitoring as mon
from .. import mpesa as mp
from .. import services as sv
from .. import settlement as stl
from .. import weather as wx
from .. import sms as smsmod
from .. import underwriting as uw
from .. import ussd as ussdmod
from ..crypto import PIIError, Vault, mask_national_id, mask_phone, normalise_national_id, normalise_phone, verify_password
from ..db import audit, init_db, make_engine, transaction
from ..kiamis import CsvKiamis
from ..models import Consent, Farmer, MissedPayoutReport, MpesaRequest, Officer, Payout, Policy, Sacco, SmsMessage, WeatherItem
from ..settings import Settings, load_settings

HERE = Path(__file__).parent
PENDING_TTL = 30 * 60
log = logging.getLogger("agroshield.portal")


class PendingStore:
    """Short-lived server-side store for wizard state and checked bulk files."""
    def __init__(self):
        self._d: dict[str, tuple[float, int, object]] = {}

    def put(self, officer_id: int, value) -> str:
        self._purge()
        token = secrets.token_urlsafe(16)
        self._d[token] = (time.time(), officer_id, value)
        return token

    def get(self, token: str, officer_id: int):
        self._purge()
        item = self._d.get(token)
        if not item or item[1] != officer_id:
            raise HTTPException(400, "This form has expired. Please start again.")
        return item[2]

    def pop(self, token: str, officer_id: int):
        v = self.get(token, officer_id)
        self._d.pop(token, None)
        return v

    def _purge(self):
        now = time.time()
        for k in [k for k, v in self._d.items() if now - v[0] > PENDING_TTL]:
            self._d.pop(k, None)


def _float(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", ".")      # some Android keyboards type a decimal comma
    return float(v) if v else None


def _masked(raw: str, normalise, mask) -> str:
    try:
        return mask(normalise(raw))
    except PIIError:
        return "(invalid)"


def ward_map(wards, counts: dict[str, int], width: int = 520, height: int = 300) -> dict:
    """Placeholder ward boxes (the extraction boxes) drawn to scale for an inline SVG.
    Real ward boundaries replace these with the IEBC shapes (milestone 7)."""
    boxes = [(w, w.centroid.lon - w.extraction_box_deg / 2, w.centroid.lat - w.extraction_box_deg / 2,
              w.extraction_box_deg) for w in wards]
    pad = 0.05
    x0, x1 = min(b[1] for b in boxes) - pad, max(b[1] + b[3] for b in boxes) + pad
    y0, y1 = min(b[2] for b in boxes) - pad, max(b[2] + b[3] for b in boxes) + pad
    k = min(width / (x1 - x0), height / (y1 - y0))
    ox, oy = (width - k * (x1 - x0)) / 2, (height - k * (y1 - y0)) / 2
    shapes = [{"id": w.id, "name": w.name, "policies": counts.get(w.id, 0),
               "x": round(ox + k * (bx - x0), 1), "y": round(oy + k * (y1 - by - bs), 1),
               "w": round(k * bs, 1), "h": round(k * bs, 1)} for w, bx, by, bs in boxes]
    return {"width": width, "height": height, "wards": shapes}


def create_app(settings: Settings | None = None, book: RateBook | None = None, *, today=None,
               mpesa_client=None, sms_sender=None) -> FastAPI:
    settings = settings or load_settings()
    cfg = load_config(settings.config_dir)
    factory: sessionmaker = init_db(make_engine(settings.database_url))
    vault = Vault(settings.encryption_key, settings.lookup_key)
    callback_url = f"{settings.mpesa.callback_base_url.rstrip('/')}/mpesa/callback/{settings.callback_token}"
    state = {"book": book, "today": today, "tables": None,
             "mpesa": mpesa_client or mp.make_client(settings.mpesa, callback_url),
             "sms": sms_sender or smsmod.make_sender(settings.sms)}
    pending = PendingStore()
    wording = sv.load_consent_wording(cfg)

    def ctx() -> sv.Context:
        if state["book"] is None:
            from agroshield_pricing.pet import make_pet_source
            from agroshield_pricing.rainfall import make_source
            state["book"] = RateBook.build(cfg, make_source(cfg, allow_download=False),
                                           make_pet_source(cfg, allow_download=False))
        return sv.Context(cfg, state["book"], vault, CsvKiamis(vault), today=state["today"], mpesa=state["mpesa"],
                          ussd_code=settings.ussd_code)

    def flush_sms() -> None:
        with transaction(factory) as s:
            smsmod.send_pending(s, state["sms"], vault)

    app = FastAPI(title="AgroShield SACCO portal", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax",
                       https_only=False, max_age=8 * 3600)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    def missing(v) -> bool:                     # None, or a key a result dict does not have
        return v is None or isinstance(v, jinja2.Undefined)
    templates.env.filters["kes"] = lambda v: "n/a" if missing(v) else f"KES {v:,.0f}"
    templates.env.filters["pct"] = lambda v, d=0: "n/a" if missing(v) else f"{v * 100:.{d}f}%"
    templates.env.filters["num"] = lambda v, d=0: "n/a" if missing(v) else f"{v:,.{d}f}"
    templates.env.filters["day"] = lambda d: "" if d is None else d.strftime("%d %b %Y")
    templates.env.filters["mask_id"] = lambda v: _masked(v, normalise_national_id, mask_national_id)
    templates.env.filters["mask_phone"] = lambda v: _masked(v, normalise_phone, mask_phone)
    templates.env.filters["label"] = lambda v: (v or "").replace("_", " ")
    templates.env.filters["days"] = lambda n: timedelta(days=n)
    templates.env.filters["short_day"] = lambda d: "" if d is None else f"{d.day} {d:%b}"
    templates.env.globals["season_label"] = sv.season_label
    templates.env.globals["ward_line"] = lambda st: L.t("en", f"ward.{mon.ward_key(st)}")
    templates.env.globals["payout_kind"] = lambda k: {"wrsi": "Drought payout", "failed_onset": "Rains failed to start",
                                                       "replant_voucher": "Replanting seed voucher"}.get(k, k)
    templates.env.globals["missed_kind"] = lambda k: {"failed_no_payout": "Crop failed, no payout",
                                                       "payout_too_small": "Payout too small", "other": "Other"}.get(k, k)
    weather_raw, weather_sources = wx.load_sources(settings.config_dir)
    templates.env.globals["ward_label"] = lambda wid: cfg.ward(wid).label if wid in cfg.wards else wid
    # Licence-checked photos (tools/fetch_images.py): key -> credit, alt text and the sizes on disk.
    # Demo screenshots of the workspace (tools/qa/shots.py) share the same macro but are not credited photos.
    images = {}
    for f in (HERE / "static" / "img" / "credits.json", HERE / "static" / "img" / "shots" / "shots.json"):
        if f.exists():
            images.update({c["key"]: c for c in json.loads(f.read_text(encoding="utf-8"))})
    templates.env.globals["images"] = images
    # Learn articles mark sources as [n]; turn each into a link to the numbered source list (input already escaped).
    cite_re = re.compile(r"\[(\d+)\]")
    templates.env.filters["cites"] = lambda text: Markup(cite_re.sub(
        r'<sup><a href="#src-\1" aria-label="Source \1">[\1]</a></sup>', str(text)))

    # ------------------------------------------------------------------ helpers
    def csrf(request: Request) -> str:
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(24)
        return request.session["csrf"]

    def check_csrf(request: Request, token: str) -> None:
        if not token or token != request.session.get("csrf"):
            raise HTTPException(403, "Form check failed. Reload the page and try again.")

    def check_token(token: str) -> None:
        if not hmac.compare_digest(token, settings.callback_token):
            raise HTTPException(404)

    def officer_or_none(request: Request, s) -> Officer | None:
        oid = request.session.get("officer_id")
        return s.get(Officer, oid) if oid else None

    def flash(request: Request, kind: str, text: str) -> None:
        request.session["flash"] = [kind, text]       # never personal data

    def render(request: Request, name: str, officer: Officer | None = None, status: int = 200, **kw):
        return templates.TemplateResponse(request, name, {
            "officer": officer, "csrf": csrf(request), "cfg": cfg, "dev_keys": settings.dev_keys,
            "mpesa_env": state["mpesa"].env, "sms_mode": settings.sms.mode, "consent_pending": not wording["reviewed"],
            "dev_mode": settings.dev_keys,
            "flash": request.session.pop("flash", None), **kw}, status_code=status)

    def require(request: Request, s, role: str | None = None) -> Officer:
        off = officer_or_none(request, s)
        if off is None or not off.active:
            raise HTTPException(303, headers={"Location": "/login"})
        if off.role == "underwriter" and role != "underwriter":
            raise HTTPException(303, headers={"Location": "/uw"})     # SACCO pages are not for the insurer
        if role and off.role != role:
            raise HTTPException(403, "Only the insurer's underwriters can see this." if role == "underwriter"
                                else "Only a SACCO manager can do this.")
        return off

    def get_or_404(s, model, key):
        obj = s.get(model, key)
        if obj is None:
            raise HTTPException(404)
        return obj

    def own_policy(s, off: Officer, policy_id: str) -> Policy:
        pol = s.get(Policy, policy_id)
        if pol is None or pol.sacco_id != off.sacco_id:
            raise HTTPException(404, "No such policy in your SACCO.")
        return pol

    def enrol_input(form: dict) -> sv.EnrolmentInput:
        layers = [x for x in ("A", "B") if form.get(f"layer_{x}")] or ["B"]
        return sv.EnrolmentInput(
            member_no=form.get("member_no", ""), full_name=form.get("full_name", ""), phone=form.get("phone", ""),
            national_id=form.get("national_id", ""), gender=form.get("gender", "undisclosed"),
            ward_id=form.get("ward_id", ""), acreage=_float(form.get("acreage")) or 0.0,
            lat=_float(form.get("lat")), lon=_float(form.get("lon")), layers=layers,
            sum_insured_kes_per_acre=_float(form.get("sum_insured_kes_per_acre")),
            payment_route=form.get("payment_route", "sacco_deduction"), loan_linked=bool(form.get("loan_linked")),
            loan_ref=form.get("loan_ref") or None, consent_data_processing=bool(form.get("consent_data_processing")),
            consent_sms=bool(form.get("consent_sms")), consent_loan_linked_payout=bool(form.get("consent_loan_linked_payout")),
            resilience={p.id: True for p in cfg.product.resilience.points if form.get(f"res_{p.id}")},
            language=form.get("language", "en"))

    # ------------------------------------------------------------------ public site
    # Path -> template under templates/public/. A page whose template is not written yet shows a short
    # "being written" page instead of a 404, so the navbar never leads nowhere.
    PUBLIC_PAGES = {"/": "home.html", "/crops": "crops.html", "/livestock": "livestock.html",
                    "/how-it-works": "how-it-works.html", "/insurers": "insurers.html", "/saccos": "saccos.html",
                    "/learn": "learn.html", "/faq": "faq.html", "/credits": "credits.html", "/demo": "demo.html"}

    def public_page(request: Request, name: str, status: int = 200, **kw):
        from .. import content
        with transaction(factory) as s:
            off = officer_or_none(request, s)
        tpl = f"public/{name}"
        if not (HERE / "templates" / tpl).exists():
            tpl = "public/_writing.html"
        kw.setdefault("articles", content.ARTICLES)
        kw.setdefault("sent", request.session.pop("enquiry_sent", None))      # reference shown after a form is stored
        return render(request, tpl, off, status=status, enq=enq, **kw)

    def _public_route(path: str, name: str):
        def view(request: Request):
            return public_page(request, name)
        view.__name__ = "public_" + (name.split(".")[0].replace("-", "_") or "home")
        app.get(path, response_class=HTMLResponse)(view)

    for _path, _name in PUBLIC_PAGES.items():
        _public_route(_path, _name)

    def enquiry_post(request: Request, kind: str, page: str, form: dict):
        """Store a public form locally (no email is sent). Post, redirect, get: the reference comes back via the session."""
        check_csrf(request, form.get("csrf_token", ""))
        if form.get("website"):                                    # hidden field people never fill in
            raise HTTPException(400, "Form check failed.")
        last = request.session.get("enquiry_at", 0)
        if time.time() - last < 20:
            raise HTTPException(429, "Please wait a few seconds before sending another form.")
        try:
            with transaction(factory) as s:
                e = enq.record(s, vault, kind, form)
                ref = e.ref
        except enq.EnquiryError as err:
            return public_page(request, page, status=422, form_error=str(err), form=form)
        request.session["enquiry_at"] = time.time()
        request.session["enquiry_sent"] = ref
        path = "/demo" if kind == "demo" else "/livestock"
        return RedirectResponse(f"{path}#form", status_code=303)

    @app.post("/demo")
    async def demo_post(request: Request):
        return enquiry_post(request, "demo", "demo.html", dict(await request.form()))

    @app.post("/livestock")
    async def livestock_post(request: Request):
        return enquiry_post(request, "livestock_interest", "livestock.html", dict(await request.form()))

    @app.get("/learn/{slug}", response_class=HTMLResponse)
    def learn_article(request: Request, slug: str):
        from .. import content
        art = content.article(slug)
        if art is None:
            raise HTTPException(404, "No such article.")
        return public_page(request, "article.html", art=art)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = s.scalar(select(Officer).where(Officer.username == username.strip()))
            if off is None or not off.active or not verify_password(password, off.password_hash):
                audit(s, username.strip()[:60] or "?", "login.failed", "officer")
                return render(request, "login.html", error="Wrong username or password.", status=401)
            request.session.clear()
            request.session["officer_id"] = off.id
            audit(s, off.username, "login", "officer", str(off.id))
            home = "/uw" if off.role == "underwriter" else "/dashboard"
        return RedirectResponse(home, status_code=303)

    @app.post("/logout")
    def logout(request: Request, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # ------------------------------------------------------------------ officer Home and manager Reports
    def plain_price(q: dict) -> dict:
        """The numbers behind the one-sentence price answer."""
        due = math.ceil(q["farmer_pays_kes"] - 1e-9)
        return {"farmer_pays": due, "acres": q["acres"], "per_acre": due / q["acres"],
                "gov_kes": q["subsidy"]["government_share_kes"], "subsidised": q["subsidy"]["government_share_kes"] > 0,
                "eligibility": q["subsidy"]["eligibility"], "discount_kes": q["resilience"]["discount_kes"],
                "cover_total": q["total_sum_insured_kes"], "cover_per_acre": q["sum_insured_kes_per_acre"],
                "voucher_per_acre": cfg.product.layer_b.germination_dry_spell.replant_cost_kes_per_acre}

    def sales_summary(c: sv.Context) -> dict:
        st = [sv.sales_status(c, w, "LR") for w in cfg.pilot.wards]
        opened = [x["closes"] for x in st if x["open"]]
        upcoming = [x["next_opens"] for x in st if not x["open"] and x.get("next_opens")]
        return {"closes": min(opened) if opened else None, "next_opens": min(upcoming) if upcoming else None}

    @app.get("/dashboard", response_class=HTMLResponse)
    def home(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            c = ctx()
            owe = sv.owing(s, off.sacco)
            wards = sorted({f.ward_id for f in s.scalars(select(Farmer).where(Farmer.sacco_id == off.sacco_id))}) \
                or list(cfg.pilot.wards)
            members = s.scalar(select(func.count()).select_from(Farmer).where(Farmer.sacco_id == off.sacco_id))
            return render(request, "home.html", off, owe=owe, owe_total=sum(p.balance_kes for p in owe), members=members,
                          sales=sales_summary(c), wards=wards, today=c.date(), alerts=mon.alerts_for(s, off.sacco_id),
                          weather=wx.visible_items(s, c.date())[:2])

    @app.post("/policies/{policy_id}/remind")
    def policy_remind(request: Request, background: BackgroundTasks, policy_id: str, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s)
            pol = own_policy(s, off, policy_id)
            res = sv.send_reminder(ctx(), s, pol, off.username)
            name = pol.farmer.full_name
        if res == "queued":
            background.add_task(flush_sms)
            flash(request, "ok", f"Reminder sent to {name}.")
        elif res == "already_sent":
            flash(request, "warn", f"A reminder was already sent to {name} today.")
        else:
            flash(request, "warn", f"{name} did not agree to SMS. Please call them instead.")
        return RedirectResponse(request.headers.get("referer") or "/dashboard", status_code=303)

    def ward_levels(s, sacco_id: int) -> dict:
        """Latest monitoring result per ward, for the newest season this SACCO has cover in."""
        out = {}
        for w, season, y in mon.sacco_seasons(s, sacco_id):
            if w not in out:
                st = mon.latest(s, w, season, y)
                if st:
                    out[w] = st
        return out

    @app.get("/reports", response_class=HTMLResponse)
    def reports(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            pf = sv.portfolio(ctx(), s, off.sacco)
            recent = s.scalars(select(Policy).where(Policy.sacco_id == off.sacco_id)
                               .order_by(Policy.created_at.desc()).limit(8)).all()
            wards = [cfg.ward(w) for w in cfg.pilot.wards]
            return render(request, "reports.html", off, pf=pf, recent=recent, wards=wards,
                          map=ward_map(wards, {w["ward_id"]: w["policies"] for w in pf["by_ward"]}),
                          levels=ward_levels(s, off.sacco_id))

    # ------------------------------------------------------------------ premium settlement (SACCO side)
    def csv_response(data: bytes, name: str):
        from fastapi.responses import Response
        return Response(data, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})

    def settlement_csv(st: dict) -> bytes:
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["record", "sacco", "remitted_on", "method", "reference", "period", "amount_kes", "status", "recorded_by",
                    "reviewed_by", "reviewed_at", "review_note"])
        for e in st["ledger"]:
            w.writerow([e.ref, st["saccos"][e.sacco_id].code, e.remitted_on.isoformat(), e.method, e.reference, e.period or "",
                        f"{e.amount_kes:.2f}", e.status, e.recorded_by, e.reviewed_by or "",
                        e.reviewed_at.isoformat() if e.reviewed_at else "", e.review_note or ""])
        w.writerow([])
        w.writerow(["sacco", "collected_kes", "remitted_kes", "confirmed_kes", "outstanding_kes", "credit_kes"])
        for r in st["rows"]:
            w.writerow([r["sacco"].code] + [f"{r[k]:.2f}" for k in ("collected_kes", "remitted_kes", "confirmed_kes",
                                                                    "outstanding_kes", "credit_kes")])
        return buf.getvalue().encode("utf-8")

    def settlement_page(request: Request, s, off, status: int = 200, **kw):
        insurer_id = off.sacco.insurer_id
        st = stl.summary(s, insurer_id, off.sacco_id) if insurer_id else {"rows": [], "ledger": [], "total": {}, "saccos": {}}
        return render(request, "settlement.html", off, status=status, st=st, methods=stl.METHODS, today=ctx().date(), **kw)

    @app.get("/reports/premium", response_class=HTMLResponse)
    def settlement_view(request: Request):
        with transaction(factory) as s:
            return settlement_page(request, s, require(request, s, role="manager"))

    @app.post("/reports/premium")
    async def settlement_record(request: Request):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf_token", ""))
        try:
            with transaction(factory) as s:
                off = require(request, s, role="manager")
                r = stl.record(s, off, form.get("amount", ""), form.get("remitted_on", ""), form.get("method", ""),
                               form.get("reference", ""), form.get("note", ""), form.get("period", ""), today=ctx().date())
                flash(request, "ok", f"Saved {r.ref}: KES {r.amount_kes:,.0f} sent on {r.remitted_on:%d %b %Y}. "
                                     "The insurer will confirm it.")
        except stl.SettlementError as e:
            with transaction(factory) as s:
                return settlement_page(request, s, require(request, s, role="manager"), status=422, error=str(e), form=form)
        return RedirectResponse("/reports/premium", status_code=303)

    @app.get("/reports/premium.csv")
    def settlement_export(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            if not off.sacco.insurer_id:
                raise HTTPException(404)
            data = settlement_csv(stl.summary(s, off.sacco.insurer_id, off.sacco_id))
            code = off.sacco.code
            audit(s, off.username, "remittance.exported", "premium_remittance", code)
        return csv_response(data, f"premium-sent-{code}.csv")

    # ------------------------------------------------------------------ quick price
    @app.get("/quote", response_class=HTMLResponse)
    def quote_form(request: Request):
        with transaction(factory) as s:
            return render(request, "quote.html", require(request, s), form={}, q=None)

    @app.post("/quote", response_class=HTMLResponse)
    async def quote_post(request: Request):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf_token", ""))
        with transaction(factory) as s:
            off = require(request, s)
            try:
                q = quote(cfg, ctx().book, ward_id=form.get("ward_id", ""), acres=_float(form.get("acreage")) or 0,
                          layers=[x for x in ("A", "B") if form.get(f"layer_{x}")] or ["B"],
                          sum_insured_kes_per_acre=_float(form.get("sum_insured_kes_per_acre")),
                          resilience={p.id: True for p in cfg.product.resilience.points if form.get(f"res_{p.id}")})
                return render(request, "quote.html", off, form=form, q=q, price=plain_price(q))
            except (QuoteError, ValueError) as e:
                return render(request, "quote.html", off, form=form, q=None, error=str(e), status=422)

    # ------------------------------------------------------------------ enrolment wizard
    # One step per screen; the draft is held server-side under a random token, so the
    # national ID and phone are typed once and never written back into a page.
    STEP_FIELDS = {1: ["member_no", "full_name", "national_id", "phone", "gender", "language"],
                   2: ["ward_id", "acreage", "lat", "lon", "res_certified_seed_verified"],
                   3: ["consent_data_processing", "consent_sms"],
                   4: ["sum_insured_kes_per_acre", "payment_route", "loan_linked", "loan_ref",
                       "consent_loan_linked_payout"]}
    CHECKBOXES = {"consent_data_processing", "consent_sms", "loan_linked", "consent_loan_linked_payout",
                  "res_certified_seed_verified"}
    ERROR_STEP = {"member_no": 1, "full_name": 1, "national_id": 1, "phone": 1, "gender": 1, "language": 1,
                  "ward_id": 2, "acreage": 2, "lat": 2, "consent_data_processing": 3, "consent": 3}

    def take(draft: dict, form: dict, step: int) -> None:
        for k in STEP_FIELDS.get(step, []):
            v = form.get(k)
            if k in ("national_id", "phone"):
                if v and v.strip():
                    draft[k] = v
            elif k in CHECKBOXES:
                draft[k] = "1" if v else ""
            elif v is not None:
                draft[k] = v

    def step_errors(errors: dict, upto: int) -> dict:
        return {k: v for k, v in errors.items() if ERROR_STEP.get(k, 4) <= upto}

    def render_step(request, s, off, step: int, token: str, draft: dict, errors: dict | None = None, status: int = 200):
        kw = {}
        if step == 4:
            pv = sv.preview(ctx(), s, dataclasses.replace(enrol_input(draft), loan_linked=False), off.sacco)
            kw = {"pv": pv, "price": plain_price(pv["quote"]) if pv["quote"] else None}
        c = ctx()
        return render(request, "enrol_step.html", off, step=step, token=token, d=draft, errors=errors or {},
                      wording=wording, gate=sv.consent_gate(c, off.sacco),
                      sales={w: sv.sales_status(c, w, "LR") for w in cfg.pilot.wards},
                      masked_id=_masked(draft.get("national_id", ""), normalise_national_id, mask_national_id)
                      if draft.get("national_id") else None,
                      masked_phone=_masked(draft.get("phone", ""), normalise_phone, mask_phone) if draft.get("phone") else None,
                      status=status, **kw)

    def first_problem(request, s, off, token, draft, errors, upto=4):
        errs = step_errors(errors, upto)
        if not errs:
            return None
        n = min(ERROR_STEP.get(k, 4) for k in errs)
        return render_step(request, s, off, n, token, draft, {k: v for k, v in errs.items() if ERROR_STEP.get(k, 4) == n},
                           status=422)

    @app.get("/enrol", response_class=HTMLResponse)
    def enrol_start(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            draft = {"sum_insured_kes_per_acre": str(int(cfg.product.sum_insured.default_kes_per_acre)),
                     "ward_id": cfg.pilot.default_ward, "language": "en", "payment_route": "sacco_deduction"}
            return render_step(request, s, off, 1, pending.put(off.id, draft), draft)

    @app.post("/enrol/step", response_class=HTMLResponse)
    async def enrol_step(request: Request):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf_token", ""))
        with transaction(factory) as s:
            off = require(request, s)
            token = form.get("token", "")
            draft = pending.get(token, off.id)
            step = max(1, min(4, int(form.get("step") or 1)))
            nav = form.get("nav", "next")
            take(draft, form, step)
            if nav == "back":
                return render_step(request, s, off, max(1, step - 1), token, draft)
            if nav == "reprice":
                return render_step(request, s, off, 4, token, draft)
            pv = sv.preview(ctx(), s, enrol_input(draft), off.sacco)
            return first_problem(request, s, off, token, draft, pv["errors"], upto=step) \
                or render_step(request, s, off, min(4, step + 1), token, draft)

    @app.post("/enrol/review", response_class=HTMLResponse)
    async def enrol_review(request: Request):
        """All answers at once (power users and tests): straight to the price step, or the first problem."""
        form = dict(await request.form())
        check_csrf(request, form.get("csrf_token", ""))
        with transaction(factory) as s:
            off = require(request, s)
            draft = {k: v for k, v in form.items() if k != "csrf_token"}
            draft.setdefault("sum_insured_kes_per_acre", str(int(cfg.product.sum_insured.default_kes_per_acre)))
            token = pending.put(off.id, draft)
            pv = sv.preview(ctx(), s, enrol_input(draft), off.sacco)
            return first_problem(request, s, off, token, draft, pv["errors"], upto=3) \
                or render_step(request, s, off, 4, token, draft)

    @app.post("/enrol/confirm", response_class=HTMLResponse)
    async def enrol_confirm(request: Request, background: BackgroundTasks):
        form = dict(await request.form())
        check_csrf(request, form.get("csrf_token", ""))
        with transaction(factory) as s:
            off = require(request, s)
            token = form.get("token", "")
            draft = pending.get(token, off.id)
            take(draft, form, 4)
            try:
                pol = sv.enrol(ctx(), s, off.sacco, off, enrol_input(draft))
            except sv.EnrolmentError as e:
                return first_problem(request, s, off, token, draft, e.errors) \
                    or render_step(request, s, off, 4, token, draft, e.errors, status=422)
            pending.pop(token, off.id)
            background.add_task(flush_sms)
            q = pol.quote_snapshot
            return render(request, "enrol_done.html", off, pol=pol, farmer=pol.farmer, price=plain_price(q),
                          sms_queued=smsmod.sms_consent(s, pol.farmer))

    # ------------------------------------------------------------------ members and payments
    @app.get("/members", response_class=HTMLResponse)
    def members(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            rows = s.scalars(select(Farmer).where(Farmer.sacco_id == off.sacco_id).order_by(Farmer.member_no)).all()
            return render(request, "members.html", off, rows=rows, query="")

    @app.post("/members", response_class=HTMLResponse)
    async def members_search(request: Request):
        form = dict(await request.form())   # searched by POST so member numbers never sit in URLs
        check_csrf(request, form.get("csrf_token", ""))
        q = (form.get("q") or "").strip()
        with transaction(factory) as s:
            off = require(request, s)
            stmt = select(Farmer).where(Farmer.sacco_id == off.sacco_id)
            if q:
                stmt = stmt.where((Farmer.member_no.contains(q)) | (Farmer.full_name.contains(q)))
            return render(request, "members.html", off, rows=s.scalars(stmt.order_by(Farmer.member_no)).all(), query=q)

    @app.get("/members/{farmer_id}", response_class=HTMLResponse)
    def member(request: Request, farmer_id: str):
        with transaction(factory) as s:
            off = require(request, s)
            f = s.get(Farmer, farmer_id)
            if f is None or f.sacco_id != off.sacco_id:
                raise HTTPException(404, "No such member in your SACCO.")
            consents = s.scalars(select(Consent).where(Consent.farmer_id == f.id).order_by(Consent.captured_at)).all()
            reqs = s.scalars(select(MpesaRequest).join(Policy).where(Policy.farmer_id == f.id)
                             .order_by(MpesaRequest.created_at.desc())).all()
            msgs = s.scalars(select(SmsMessage).where(SmsMessage.farmer_id == f.id)
                             .order_by(SmsMessage.created_at.desc())).all()
            pays = s.scalars(select(Payout).join(Policy).where(Policy.farmer_id == f.id).order_by(Payout.id)).all()
            missed = s.scalars(select(MissedPayoutReport).where(MissedPayoutReport.farmer_id == f.id)
                               .order_by(MissedPayoutReport.created_at.desc())).all()
            return render(request, "member.html", off, f=f, consents=consents, policies=f.policies, mpesa_requests=reqs,
                          messages=msgs, today=ctx().date(), min_instalment=sv.MIN_INSTALMENT_KES, payouts=pays,
                          missed=missed)

    @app.post("/policies/{policy_id}/stk")
    def policy_stk(request: Request, policy_id: str, amount: str = Form(""), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s)
            pol = own_policy(s, off, policy_id)
            try:
                mp.request_premium(ctx(), s, pol, int(amount) if amount.strip().isdigit() else -1, off.username)
                flash(request, "ok", f"M-Pesa request for KES {int(amount):,} sent to the farmer's phone.")
            except (sv.PaymentError, mp.MpesaError) as e:
                flash(request, "crit", str(e))
            return RedirectResponse(f"/members/{pol.farmer_id}", status_code=303)

    @app.post("/policies/{policy_id}/deduction")
    def policy_deduction(request: Request, background: BackgroundTasks, policy_id: str, amount: str = Form(""),
                         reference: str = Form(""), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s)
            pol = own_policy(s, off, policy_id)
            try:
                sv.record_payment(ctx(), s, pol, _float(amount) or 0, "sacco_deduction", reference, off.username)
                flash(request, "ok", f"SACCO deduction of KES {float(amount):,.0f} recorded.")
                background.add_task(flush_sms)
            except (sv.PaymentError, ValueError) as e:
                flash(request, "crit", str(e))
            return RedirectResponse(f"/members/{pol.farmer_id}", status_code=303)

    @app.post("/policies/{policy_id}/insurer-number")
    def policy_insurer_number(request: Request, policy_id: str, insurer_policy_number: str = Form(""),
                              csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            pol = own_policy(s, off, policy_id)
            pol.insurer_policy_number = insurer_policy_number.strip()[:60] or None
            audit(s, off.username, "policy.insurer_number_set", "policy", pol.id, policy_no=pol.policy_no)
            flash(request, "ok", "Insurer policy number saved.")
            return RedirectResponse(f"/members/{pol.farmer_id}", status_code=303)

    # ------------------------------------------------------------------ bulk
    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request):
        with transaction(factory) as s:
            return render(request, "import.html", require(request, s, role="manager"), report=None, result=None)

    @app.get("/bulk", response_class=HTMLResponse)
    def bulk(request: Request):
        with transaction(factory) as s:
            return render(request, "import.html", require(request, s), report=None, result=None)

    @app.get("/bulk/template.csv")
    def bulk_template(request: Request):
        with transaction(factory) as s:
            require(request, s)
        return PlainTextResponse(sv.bulk_template(), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=agroshield-bulk-template.csv"})

    @app.post("/bulk/check", response_class=HTMLResponse)
    async def bulk_check(request: Request, file: UploadFile, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        text = (await file.read()).decode("utf-8-sig", errors="replace")
        with transaction(factory) as s:
            off = require(request, s)
            report = sv.bulk_check(ctx(), s, text, off.sacco)
            token = pending.put(off.id, text) if report["ok"] else None
            return render(request, "import.html", off, report=report, token=token, result=None)

    @app.post("/bulk/commit", response_class=HTMLResponse)
    async def bulk_commit(request: Request, background: BackgroundTasks, token: str = Form(...),
                          csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s)
            text = pending.pop(token, off.id)
            try:
                pols = sv.bulk_commit(ctx(), s, off.sacco, off, text)
            except sv.EnrolmentError as e:
                s.rollback()   # all-or-nothing: no row from this file is kept
                return render(request, "import.html", off, report=None, result=None, error=str(e), status=422)
            background.add_task(flush_sms)
            return render(request, "import.html", off, report=None, result=None, committed=pols)

    # ------------------------------------------------------------------ KIAMIS
    @app.get("/kiamis", response_class=HTMLResponse)
    def kiamis(request: Request):
        with transaction(factory) as s:
            return render(request, "import.html", require(request, s, role="manager"), result=None, report=None)

    @app.post("/kiamis", response_class=HTMLResponse)
    async def kiamis_import(request: Request, file: UploadFile, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        text = (await file.read()).decode("utf-8-sig", errors="replace")
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            try:
                result = CsvKiamis(vault).import_csv(s, text)
            except ValueError as e:
                return render(request, "import.html", off, result=None, report=None, kiamis_error=str(e), status=422)
            audit(s, off.username, "kiamis.imported", "kiamis", None, added=result["added"], updated=result["updated"],
                  errors=len(result["errors"]), source_sha256=result["source_sha256"])
            return render(request, "import.html", off, result=result, report=None)

    # ------------------------------------------------------------------ SMS outbox
    @app.get("/sms", response_class=HTMLResponse)
    def sms_outbox(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            msgs = s.scalars(select(SmsMessage).join(Farmer).where(Farmer.sacco_id == off.sacco_id)
                             .order_by(SmsMessage.created_at.desc()).limit(200)).all()
            return render(request, "sms.html", off, messages=msgs)

    @app.post("/sms/send")
    def sms_send(request: Request, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            counts = smsmod.send_pending(s, state["sms"], vault)
            audit(s, off.username, "sms.sent", "sacco", str(off.sacco_id), **counts)
        flash(request, "ok", "Outbox processed: " + (", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing queued"))
        return RedirectResponse("/sms", status_code=303)

    # ------------------------------------------------------------------ M-Pesa simulator (development)
    @app.get("/dev/mpesa", response_class=HTMLResponse)
    def dev_mpesa(request: Request):
        if state["mpesa"].env != "simulated":
            raise HTTPException(404)
        with transaction(factory) as s:
            off = require(request, s)
            reqs = s.scalars(select(MpesaRequest).join(Policy).where(Policy.sacco_id == off.sacco_id)
                             .order_by(MpesaRequest.created_at.desc()).limit(50)).all()
            return render(request, "dev_mpesa.html", off, requests=reqs)

    @app.post("/dev/mpesa/{request_id}/{outcome}")
    def dev_mpesa_complete(request: Request, background: BackgroundTasks, request_id: int, outcome: str,
                           csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        if state["mpesa"].env != "simulated" or outcome not in ("success", "cancel"):
            raise HTTPException(404)
        with transaction(factory) as s:
            off = require(request, s)
            req = s.get(MpesaRequest, request_id)
            if req is None or req.policy.sacco_id != off.sacco_id:
                raise HTTPException(404)
            res = mp.handle_callback(ctx(), s, state["mpesa"].simulate_callback(req, outcome == "success"))
        background.add_task(flush_sms)
        flash(request, "ok" if res["outcome"] == "paid" else "warn", f"Simulated callback: {res['outcome']}.")
        return RedirectResponse("/dev/mpesa", status_code=303)

    # ------------------------------------------------------------------ callbacks
    @app.post("/ussd/{token}", response_class=PlainTextResponse)
    def ussd(token: str, background: BackgroundTasks, sessionId: str = Form(""), serviceCode: str = Form(""),
             phoneNumber: str = Form(""), text: str = Form("")):
        check_token(token)
        with transaction(factory) as s:
            reply = ussdmod.handle(ctx(), s, phoneNumber, text)
        background.add_task(flush_sms)
        return PlainTextResponse(reply)

    @app.post("/mpesa/callback/{token}")
    async def mpesa_callback(token: str, request: Request, background: BackgroundTasks):
        check_token(token)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        with transaction(factory) as s:
            res = mp.handle_callback(ctx(), s, body)
            audit(s, "mpesa", "mpesa.callback", "mpesa", None, outcome=res["outcome"])
        background.add_task(flush_sms)
        return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})

    # ------------------------------------------------------------------ Payout Tracker
    @app.get("/payouts", response_class=HTMLResponse)
    def payouts(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            c = ctx()
            cards = []
            for w, season, y in mon.sacco_seasons(s, off.sacco_id):
                st = mon.latest(s, w, season, y)
                rows = s.scalars(select(Payout).join(Policy).where(Policy.sacco_id == off.sacco_id, Policy.ward_id == w,
                                                                   Policy.season == season, Policy.year == y)
                                 .order_by(Payout.due_by, Payout.id)).all()
                n_active = len(s.scalars(select(Policy).where(Policy.sacco_id == off.sacco_id, Policy.ward_id == w,
                                                              Policy.season == season, Policy.year == y,
                                                              Policy.status == "active")).all())
                cards.append({"ward_id": w, "season": season, "year": y, "st": st, "payouts": rows, "active": n_active})
            reports = s.scalars(select(MissedPayoutReport).join(Farmer).where(Farmer.sacco_id == off.sacco_id)
                                .order_by(MissedPayoutReport.created_at.desc()).limit(100)).all()
            return render(request, "payouts.html", off, cards=cards, reports=reports, today=c.date(),
                          overdue=mon.overdue, outcomes=mon.REVIEW_OUTCOMES)

    @app.post("/payouts/{payout_id}/pay")
    def payout_pay(request: Request, background: BackgroundTasks, payout_id: int, reference: str = Form(""),
                   csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            p = s.get(Payout, payout_id)
            if p is None or p.policy.sacco_id != off.sacco_id:
                raise HTTPException(404)
            try:
                mon.pay(ctx(), s, p, off.username, reference)
                msg = (f"Voucher {p.voucher_code} marked used." if p.method == "voucher"
                       else f"Payout of KES {p.amount_kes:,.0f} to {p.policy.farmer.full_name} recorded as paid.")
                flash(request, "ok", msg)
                background.add_task(flush_sms)
            except (mon.PayoutError, mp.MpesaError) as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/payouts", status_code=303)

    @app.post("/members/{farmer_id}/missed")
    def missed_report(request: Request, farmer_id: str, category: str = Form(""), note: str = Form(""),
                      csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s)
            f = s.get(Farmer, farmer_id)
            if f is None or f.sacco_id != off.sacco_id:
                raise HTTPException(404)
            try:
                r = mon.report_missed(ctx(), s, f, category, "portal", off.username, note)
                flash(request, "ok", f"Recorded as {r.ref}. It will be reviewed; it does not change a payout.")
            except ValueError as e:
                flash(request, "crit", str(e))
        return RedirectResponse(f"/members/{farmer_id}", status_code=303)

    @app.post("/missed/{report_id}/review")
    def missed_review(request: Request, report_id: int, outcome: str = Form(""), note: str = Form(""),
                      csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            r = s.get(MissedPayoutReport, report_id)
            if r is None or r.farmer.sacco_id != off.sacco_id:
                raise HTTPException(404)
            try:
                mon.review_missed(s, r, outcome, note, off.username)
                flash(request, "ok", f"{r.ref} reviewed.")
            except ValueError as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/payouts#reports", status_code=303)

    # ------------------------------------------------------------------ weather (display only)
    @app.get("/weather", response_class=HTMLResponse)
    def weather(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            items = s.scalars(select(WeatherItem).order_by(WeatherItem.created_at.desc()).limit(50)).all()
            from ..models import WeatherFetch
            fetches = s.scalars(select(WeatherFetch).order_by(WeatherFetch.at.desc()).limit(15)).all()
            return render(request, "weather.html", off, items=items, fetches=fetches, sources=weather_sources,
                          sms_blocked=lambda i: wx.sms_blocked(i, weather_sources))

    @app.post("/weather/fetch")
    def weather_fetch(request: Request, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            res = wx.fetch(s, settings.config_dir, Path(cfg.root).parent)
            audit(s, off.username, "weather.fetch_requested", "weather", None, **res)
        flash(request, "ok", "Checked sources: " + ", ".join(f"{k} {v}" for k, v in res.items()))
        return RedirectResponse("/weather", status_code=303)

    @app.post("/weather/upload")
    async def weather_upload(request: Request, file: UploadFile, title: str = Form(""), valid_from: str = Form(""),
                             valid_to: str = Form(""), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        data = await file.read()
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            from datetime import date as _d
            try:
                item = wx.store_pdf(s, Path(cfg.root).parent / weather_raw["store_dir"], weather_sources["kmd_nakuru"],
                                    data, title.strip() or file.filename, None, "uploaded",
                                    _d.fromisoformat(valid_from) if valid_from else None,
                                    _d.fromisoformat(valid_to) if valid_to else None)
                flash(request, "ok" if item else "warn", "Uploaded. Write and approve a summary before it shows."
                      if item else "That document is already here.")
            except (wx.WeatherError, ValueError) as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/weather", status_code=303)

    @app.post("/weather/{item_id}/approve")
    def weather_approve(request: Request, item_id: int, summary_en: str = Form(""), summary_sw: str = Form(""),
                        csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            item = get_or_404(s, WeatherItem, item_id)
            try:
                wx.approve(s, item, summary_en, summary_sw, off.username)
                flash(request, "ok", "Approved. It now shows on Home for officers.")
            except wx.WeatherError as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/weather", status_code=303)

    @app.post("/weather/{item_id}/withdraw")
    def weather_withdraw(request: Request, item_id: int, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            item = get_or_404(s, WeatherItem, item_id)
            item.status = "withdrawn"
            audit(s, off.username, "weather.withdrawn", "weather_item", str(item.id))
        return RedirectResponse("/weather", status_code=303)

    @app.post("/weather/{item_id}/sms")
    def weather_sms(request: Request, item_id: int, csrf_token: str = Form("")):
        """There is no automatic send. Even this manual one refuses until written permission is on file."""
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            item = get_or_404(s, WeatherItem, item_id)
            reason = wx.sms_blocked(item, weather_sources)
            audit(s, off.username, "weather.sms_refused" if reason else "weather.sms_requested", "weather_item", str(item.id))
        flash(request, "warn", reason or "SMS of weather content is not built yet.")
        return RedirectResponse("/weather", status_code=303)

    @app.get("/weather/{item_id}/pdf")
    def weather_pdf(request: Request, item_id: int):
        from fastapi.responses import FileResponse
        with transaction(factory) as s:
            require(request, s)
            item = s.get(WeatherItem, item_id)
            if item is None or not item.pdf_path or not Path(item.pdf_path).exists():
                raise HTTPException(404)
            return FileResponse(item.pdf_path, media_type="application/pdf")

    # ------------------------------------------------------------------ underwriter workspace
    def engine_tables() -> dict:
        if state["tables"] is None:
            from agroshield_pricing.engine import price_ward
            from agroshield_pricing.pet import make_pet_source
            from agroshield_pricing.rainfall import make_source
            rs, ps = make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False)
            state["tables"] = {w: price_ward(cfg, w, rs, ps).seasons["LR"].table for w in cfg.pilot.wards}
        return state["tables"]

    def uw_payout(s, off: Officer, payout_id: int) -> Payout:
        p = s.get(Payout, payout_id)
        if p is None or p.policy.insurer_id != off.insurer_id:
            raise HTTPException(404)
        return p

    def uw_filters(request: Request, s, off) -> dict:
        """Season and SACCO filters from the query string (codes only, never personal data)."""
        saccos = list(s.scalars(select(Sacco).where(Sacco.insurer_id == off.insurer_id).order_by(Sacco.name)))
        sacco = next((x for x in saccos if x.code == request.query_params.get("sacco")), None)
        season = request.query_params.get("season") or None
        seasons = sorted({(p.season, p.year) for p in uw.policies(s, off.insurer_id)}, key=lambda x: (-x[1], x[0]))
        if season not in {f"{a}-{b}" for a, b in seasons}:
            season = None
        return {"saccos": saccos, "sacco": sacco, "season": season, "seasons": seasons}

    def uw_filtered(request: Request, s, off):
        f = uw_filters(request, s, off)
        return f, uw.filter_policies(uw.policies(s, off.insurer_id), f["season"], f["sacco"].id if f["sacco"] else None)

    @app.get("/uw", response_class=HTMLResponse)
    def uw_portfolio(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            c = ctx()
            f, pols = uw_filtered(request, s, off)
            return render(request, "uw_portfolio.html", off, pf=uw.portfolio(c, s, off.insurer, pols=pols),
                          ch=uw.charts(c, s, pols), f=f)

    @app.get("/uw/portfolio.csv")
    def uw_portfolio_csv(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            f, pols = uw_filtered(request, s, off)
            data = uw.portfolio_csv(uw.portfolio(ctx(), s, off.insurer, pols=pols))
            code = off.insurer.code
            audit(s, off.username, "portfolio.exported", "insurer", code, season=f["season"] or "all",
                  sacco=f["sacco"].code if f["sacco"] else "all")
        return csv_response(data, f"portfolio-{code}.csv")

    @app.get("/uw/triggers", response_class=HTMLResponse)
    def uw_triggers(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            c = ctx()
            return render(request, "uw_triggers.html", off, tr=uw.triggers(c, s, off.insurer, c.date()))

    @app.post("/uw/payouts/{payout_id}/approve")
    def uw_approve(request: Request, background: BackgroundTasks, payout_id: int, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            p = uw_payout(s, off, payout_id)
            try:
                mon.approve(ctx(), s, p, off.username)
                flash(request, "ok", f"Approved {p.policy.policy_no} {payout_kind_text(p.kind)} KES {p.amount_kes:,.0f}.")
                background.add_task(flush_sms)
            except mon.PayoutError as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/uw/triggers", status_code=303)

    @app.post("/uw/payouts/approve-event/{status_id}")
    def uw_approve_event(request: Request, background: BackgroundTasks, status_id: int, csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            ids = {p.id for p in uw.policies(s, off.insurer_id)}
            pays = s.scalars(select(Payout).where(Payout.ward_status_id == status_id, Payout.status == "calculated")).all()
            n = 0
            for p in pays:
                if p.policy_id in ids:
                    mon.approve(ctx(), s, p, off.username)
                    n += 1
        background.add_task(flush_sms)
        flash(request, "ok", f"Approved {n} payout{'s' if n != 1 else ''}.")
        return RedirectResponse("/uw/triggers", status_code=303)

    @app.post("/uw/payouts/{payout_id}/hold")
    def uw_hold(request: Request, payout_id: int, reason: str = Form(""), csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            p = uw_payout(s, off, payout_id)
            try:
                mon.hold(s, p, reason, off.username)
                flash(request, "warn", f"Held {p.policy.policy_no}: {p.hold_reason}")
            except mon.PayoutError as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/uw/triggers", status_code=303)

    @app.get("/uw/money", response_class=HTMLResponse)
    def uw_money(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            return render(request, "uw_money.html", off, m=uw.money(s, off.insurer), st=stl.summary(s, off.insurer_id),
                          methods=stl.METHODS)

    @app.post("/uw/settlement/{ref}")
    def uw_settlement_review(request: Request, ref: str, decision: str = Form(""), note: str = Form(""),
                             csrf_token: str = Form("")):
        check_csrf(request, csrf_token)
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            try:
                r = stl.review(s, off, ref, decision, note)
                flash(request, "ok" if r.status == "confirmed" else "warn",
                      f"{r.ref} {'confirmed' if r.status == 'confirmed' else 'queried'}: KES {r.amount_kes:,.0f}.")
            except stl.SettlementError as e:
                flash(request, "crit", str(e))
        return RedirectResponse("/uw/money#settlement", status_code=303)

    @app.get("/uw/settlement.csv")
    def uw_settlement_csv(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            data = settlement_csv(stl.summary(s, off.insurer_id))
            code = off.insurer.code
            audit(s, off.username, "remittance.exported", "premium_remittance", code)
        return csv_response(data, f"premium-settlement-{code}.csv")

    @app.get("/uw/bordereaux", response_class=HTMLResponse)
    def uw_bordereaux(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            months = uw.months_with_activity(s, off.insurer)
            manifests = [uw.bordereaux(s, off.insurer, mth, dict(cfg.file_hashes))[1] for mth in months[:12]]
            return render(request, "uw_bordereaux.html", off, manifests=manifests)

    @app.get("/uw/bordereaux/{month}.zip")
    def uw_bordereaux_zip(request: Request, month: str):
        import re as _re
        from fastapi.responses import Response
        if not _re.fullmatch(r"\d{4}-\d{2}", month):
            raise HTTPException(404)
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            data, manifest = uw.bordereaux(s, off.insurer, month, dict(cfg.file_hashes))
            audit(s, off.username, "bordereaux.exported", "insurer", str(off.insurer_id), month=month,
                  file_sha256=hashlib.sha256(data).hexdigest())
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": f"attachment; filename=bordereaux-{off.insurer.code}-{month}.zip"})

    @app.get("/uw/pricing", response_class=HTMLResponse)
    def uw_pricing(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            repo = Path(cfg.root).parent
            return render(request, "uw_pricing.html", off, runs=uw.pricing_runs(repo), log=uw.run_log(repo),
                          events=uw.audit_events(s, off.insurer), current=dict(cfg.file_hashes))

    @app.get("/uw/runs/{run_id}/report.html", response_class=HTMLResponse)
    def uw_run_report(request: Request, run_id: str):
        import re as _re
        from fastapi.responses import FileResponse
        if not _re.fullmatch(r"[0-9TZ]+_[a-z0-9-]+_[0-9a-f]+", run_id):
            raise HTTPException(404)
        with transaction(factory) as s:
            require(request, s, role="underwriter")
        f = Path(cfg.root).parent / "runs" / run_id / "report.html"
        if not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="text/html")

    @app.get("/uw/weather", response_class=HTMLResponse)
    def uw_weather(request: Request):
        """Read-only for the insurer: approved advisories only, with their source labels (display only)."""
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            return render(request, "uw_weather.html", off, items=wx.visible_items(s, ctx().date()), sources=weather_sources)

    @app.get("/uw/reinsurer", response_class=HTMLResponse)
    def uw_reinsurer(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="underwriter")
            c = ctx()
            pf = uw.portfolio(c, s, off.insurer)
            tables = engine_tables()
            books = [uw.as_if_losses(c, s, off.insurer, tables, season, y) for season, y in pf["seasons"]]
            return render(request, "uw_reinsurer.html", off, pf=pf, books=[b for b in books if b["sum_insured_kes"]],
                          esg=uw.esg(s, off.insurer, cfg.monitoring.payout_within_days), today=c.date(),
                          burn={w: price_burn(w) for w in cfg.pilot.wards})

    def price_burn(w: str) -> dict:
        t = engine_tables()[w]
        sh = t["payout_share"]
        return {"expected_loss": float(sh.mean()), "loss_1_in_10": float(sh.quantile(0.9)),
                "loss_1_in_20": float(sh.quantile(0.95)), "frequency": float((sh > 0).mean()),
                "years": [int(t.index.min()), int(t.index.max())]}

    def payout_kind_text(k: str) -> str:
        return {"wrsi": "drought payout", "failed_onset": "failed-onset payout", "replant_voucher": "seed voucher"}.get(k, k)

    # ------------------------------------------------------------------ export
    @app.get("/export/policies.csv")
    def export(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            audit(s, off.username, "export.policies", "sacco", str(off.sacco_id))
            body = sv.export_policies_csv(s, off.sacco)
        return PlainTextResponse(body, media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=agroshield-policies.csv"})

    # ------------------------------------------------------------------ friendly error pages (browsers only)
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    def wants_html(request: Request) -> bool:
        return "text/html" in request.headers.get("accept", "") and not request.url.path.startswith(("/ussd/", "/mpesa/"))

    @app.exception_handler(StarletteHTTPException)
    async def html_http_errors(request: Request, exc: StarletteHTTPException):
        if exc.status_code < 400 or not wants_html(request):
            return await http_exception_handler(request, exc)      # redirects, callbacks and API clients unchanged
        with transaction(factory) as s:
            off = officer_or_none(request, s)
        return render(request, "error.html", off, status=exc.status_code, code=exc.status_code, message=exc.detail)

    @app.exception_handler(Exception)
    async def html_server_errors(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        if not wants_html(request):
            return PlainTextResponse("Internal Server Error", status_code=500)
        return templates.TemplateResponse(request, "error.html", {
            "officer": None, "csrf": "", "cfg": cfg, "dev_keys": settings.dev_keys, "mpesa_env": state["mpesa"].env,
            "sms_mode": settings.sms.mode, "dev_mode": settings.dev_keys, "flash": None, "code": 500,
            "message": "Something went wrong on our side. It has been logged."}, status_code=500)

    app.state.factory = factory
    app.state.vault = vault
    app.state.flush_sms = flush_sms
    app.state.state = state
    return app
