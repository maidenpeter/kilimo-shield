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
  /sms, /dev/mpesa     Developer menu (development mode only): SMS log, M-Pesa simulator

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
import hmac
import logging
import math
import secrets
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from agroshield_pricing.config import load_config
from agroshield_pricing.quote import QuoteError, RateBook, quote

from .. import mpesa as mp
from .. import services as sv
from .. import sms as smsmod
from .. import ussd as ussdmod
from ..crypto import PIIError, Vault, mask_national_id, mask_phone, normalise_national_id, normalise_phone, verify_password
from ..db import audit, init_db, make_engine, transaction
from ..kiamis import CsvKiamis
from ..models import Consent, Farmer, MpesaRequest, Officer, Policy, SmsMessage
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
    v = (v or "").strip()
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
    state = {"book": book, "today": today,
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
    templates.env.filters["kes"] = lambda v: "n/a" if v is None else f"KES {v:,.0f}"
    templates.env.filters["pct"] = lambda v, d=0: "n/a" if v is None else f"{v * 100:.{d}f}%"
    templates.env.filters["num"] = lambda v, d=0: "n/a" if v is None else f"{v:,.{d}f}"
    templates.env.filters["day"] = lambda d: "" if d is None else d.strftime("%d %b %Y")
    templates.env.filters["mask_id"] = lambda v: _masked(v, normalise_national_id, mask_national_id)
    templates.env.filters["mask_phone"] = lambda v: _masked(v, normalise_phone, mask_phone)
    templates.env.filters["label"] = lambda v: (v or "").replace("_", " ")
    templates.env.filters["short_day"] = lambda d: "" if d is None else f"{d.day} {d:%b}"
    templates.env.globals["season_label"] = sv.season_label
    templates.env.globals["ward_label"] = lambda wid: cfg.ward(wid).label if wid in cfg.wards else wid

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
        if role and off.role != role:
            raise HTTPException(403, "Only a SACCO manager can do this.")
        return off

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

    # ------------------------------------------------------------------ public
    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        with transaction(factory) as s:
            return render(request, "landing.html", officer_or_none(request, s))

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
        return RedirectResponse("/dashboard", status_code=303)

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
            return render(request, "home.html", off, owe=owe, owe_total=sum(p.balance_kes for p in owe),
                          sales=sales_summary(c), wards=wards, today=c.date())

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

    @app.get("/reports", response_class=HTMLResponse)
    def reports(request: Request):
        with transaction(factory) as s:
            off = require(request, s, role="manager")
            pf = sv.portfolio(ctx(), s, off.sacco)
            recent = s.scalars(select(Policy).where(Policy.sacco_id == off.sacco_id)
                               .order_by(Policy.created_at.desc()).limit(8)).all()
            wards = [cfg.ward(w) for w in cfg.pilot.wards]
            return render(request, "reports.html", off, pf=pf, recent=recent, wards=wards,
                          map=ward_map(wards, {w["ward_id"]: w["policies"] for w in pf["by_ward"]}))

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
            return render(request, "member.html", off, f=f, consents=consents, policies=f.policies, mpesa_requests=reqs,
                          messages=msgs, today=ctx().date(), min_instalment=sv.MIN_INSTALMENT_KES)

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

    # ------------------------------------------------------------------ export
    @app.get("/export/policies.csv")
    def export(request: Request):
        with transaction(factory) as s:
            off = require(request, s)
            audit(s, off.username, "export.policies", "sacco", str(off.sacco_id))
            body = sv.export_policies_csv(s, off.sacco)
        return PlainTextResponse(body, media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=agroshield-policies.csv"})

    app.state.factory = factory
    app.state.vault = vault
    app.state.flush_sms = flush_sms
    app.state.state = state
    return app
