"""SIMULATION / REPLAY: one whole season, end to end, on the real platform services.

    python -m agroshield_platform.simulate --year 2008        (or: python tools/sim/season.py --year 2008)
    -> docs/remaining/season-2008/index.html, season.json and bordereaux/*.zip

The long rains of a past year at one pilot ward (default: 2008 at Ward A, shown by its display name from
config/wards.yaml) are replayed day by day in a THROWAWAY SQLite database (a temporary folder, deleted afterwards),
with a fictional SACCO, fictional officers and fictional members. 2008 is a real drought in the committed CHIRPS
record. Every step calls the same service the portal, USSD and the daily job call; nothing about prices, triggers
or payouts is re-implemented here:

    enrolment            services.enrol (the officer's enrolment wizard rules: sales window, consent, quote)
    premium              mpesa.request_premium + SimulatedDaraja callback + mpesa.handle_callback (STK push),
                         services.record_payment (SACCO deduction), instalments
    settlement           settlement.record (SACCO manager) and settlement.review (the underwriter confirms)
    sales close          services.close_sales_windows every day (reminders, lapse), settlement.record_refund
    daily monitoring     monitoring.run_monitoring(mode="replay") every day of the season
    trigger confirmed    monitoring.apply_confirmed (inside run_monitoring): payouts for active cover only
    approval             monitoring.approve (the underwriter)
    payout               monitoring.pay (simulated M-Pesa B2C, or credit to the SACCO loan)
    SMS log              sms.send_pending with the log-only sender: recorded, never sent
    missed payout        monitoring.report_missed (USSD) and monitoring.review_missed (the SACCO manager)
    bordereaux           underwriting.bordereaux (masked CSVs and a manifest of checksums)
    reinsurer summary    underwriting.portfolio, underwriting.as_if_losses, underwriting.esg

The clock: the services read the time with datetime.now(). For the replay a simulated clock is installed in the
platform modules for the duration of the run (SimClock), so stored timestamps, approvals, payouts and SMS fall on
the replayed calendar. No network: M-Pesa is SimulatedDaraja and SMS is LogOnlySender, whatever the environment says.

The scripted calendar (enrolment and payment days) is set for Ward A's sales window (15 September to 14 February).
"""
from __future__ import annotations

import argparse
import calendar
import dataclasses
import hashlib
import importlib
import json
import secrets
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from . import locale as L
from . import monitoring, mpesa, services, settlement, sms
from . import underwriting as uw
from .crypto import Vault, hash_password
from .db import audit, init_db, make_engine
from .kiamis import NotConnected
from .models import AuditEvent, Insurer, MissedPayoutReport, Officer, Payout, Policy, Sacco, SmsMessage, WardStatus
from .services import NAIROBI, EnrolmentInput

REPO = Path(__file__).resolve().parents[2]
LABEL = "SIMULATION / REPLAY"
STEP_ORDER = ("enrolment", "premium", "settlement", "sales_close", "monitoring", "trigger", "approval", "payout",
              "sms", "missed_payout", "bordereaux", "reinsurer")
CLOCK_MODULES = ("models", "monitoring", "settlement", "sms", "mpesa", "services", "underwriting")

# Fictional members (names marked "(fictional)"; national IDs and phones are made up and stored encrypted).
# plan: how the member pays the farmer share during the sales window.
MEMBERS = [
    {"member_no": "SIM-001", "full_name": "Njeri Wambui (fictional)", "phone": "0712 100 001", "national_id": "91000001",
     "gender": "female", "acreage": 2.0, "sum_insured": 10000, "route": "mpesa", "language": "sw", "sms": True,
     "resilience": {"certified_seed_verified": True}, "plan": "mpesa_full"},
    {"member_no": "SIM-002", "full_name": "Kibet Cheruiyot (fictional)", "phone": "0712 100 002", "national_id": "91000002",
     "gender": "male", "acreage": 3.0, "sum_insured": 10000, "route": "mpesa", "language": "en", "sms": True,
     "resilience": {}, "plan": "mpesa_instalments"},
    {"member_no": "SIM-003", "full_name": "Atieno Achieng (fictional)", "phone": "0712 100 003", "national_id": "91000003",
     "gender": "female", "acreage": 1.5, "sum_insured": 15000, "route": "sacco_deduction", "language": "sw", "sms": True,
     "resilience": {"sacco_good_standing": True}, "plan": "deduction_instalments", "loan_ref": "LN-SIM-0003"},
    {"member_no": "SIM-004", "full_name": "Mutua Kioko (fictional)", "phone": "0712 100 004", "national_id": "91000004",
     "gender": "male", "acreage": 4.0, "sum_insured": 10000, "route": "sacco_deduction", "language": "en", "sms": False,
     "resilience": {"practices_verified": True}, "plan": "deduction_full"},
    {"member_no": "SIM-005", "full_name": "Wairimu Ndungu (fictional)", "phone": "0712 100 005", "national_id": "91000005",
     "gender": "female", "acreage": 1.0, "sum_insured": 5000, "route": "mpesa", "language": "en", "sms": True,
     "resilience": {}, "plan": "mpesa_retry"},
    {"member_no": "SIM-006", "full_name": "Barasa Wafula (fictional)", "phone": "0712 100 006", "national_id": "91000006",
     "gender": "male", "acreage": 2.5, "sum_insured": 10000, "route": "mpesa", "language": "sw", "sms": True,
     "resilience": {}, "plan": "never_finishes"},
]


class SimulationError(AssertionError):
    """A check on the simulated season failed (for example a payout outside the 10-day window)."""


# ------------------------------------------------------------------ the simulated clock
class SimClock:
    """Stands in for datetime.now() in the platform modules while installed."""

    def __init__(self, start: datetime):
        self.current = start

    def at(self, d: date, hh: int = 9, mm: int = 0) -> datetime:
        self.current = datetime.combine(d, time(hh, mm), tzinfo=NAIROBI)
        return self.current

    def advance(self, **kw) -> datetime:
        self.current += timedelta(**kw)
        return self.current

    @contextmanager
    def installed(self):
        clock = self

        class SimDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.current.astimezone(tz) if tz is not None else clock.current.replace(tzinfo=None)

            @classmethod
            def utcnow(cls):
                return clock.current.astimezone(timezone.utc).replace(tzinfo=None)

        mods = [importlib.import_module(f"agroshield_platform.{m}") for m in CLOCK_MODULES]
        saved = [(m, m.datetime) for m in mods]
        try:
            for m in mods:
                m.datetime = SimDatetime
            yield self
        finally:
            for m, d in saved:
                m.datetime = d


def _nairobi(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(NAIROBI)


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return _nairobi(dt).strftime("%Y-%m-%d %H:%M")
    return dt.isoformat()


# ------------------------------------------------------------------ set-up
def _engine_inputs(cfg, ward_id: str):
    from agroshield_pricing.engine import price_ward
    from agroshield_pricing.pet import make_pet_source
    from agroshield_pricing.quote import RateBook
    from agroshield_pricing.rainfall import make_source
    rs, ps = make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False)
    return RateBook.build(cfg, rs, ps), {ward_id: price_ward(cfg, ward_id, rs, ps).seasons["LR"].table}


def _people(s):
    ins = Insurer(code="SIMUW", name="Partner insurer (to be named) (simulation)", is_demo=True,
                  premium_paybill="Simulation only: no money moves")
    s.add(ins)
    s.flush()
    sacco = Sacco(code="SIM", name="Simulation SACCO (fictional)", is_demo=True, insurer_id=ins.id)
    s.add(sacco)
    s.flush()

    def person(username, name, role, **where):
        o = Officer(username=username, display_name=name, role=role,
                    password_hash=hash_password(secrets.token_urlsafe(18)), **where)   # nobody signs in
        s.add(o)
        return o
    officer = person("sim-officer", "Grace (fictional officer)", "officer", sacco_id=sacco.id)
    manager = person("sim-manager", "Daniel (fictional SACCO manager)", "manager", sacco_id=sacco.id)
    under = person("sim-underwriter", "Amina (fictional underwriter)", "underwriter", insurer_id=ins.id)
    s.flush()
    return ins, sacco, officer, manager, under


def _schedule(opens: date, closes: date) -> dict:
    """Scripted days, set for Ward A's window (opens 15 Sep, closes 14 Feb)."""
    o = opens
    days = {
        "enrol": [o + timedelta(days=30 + i) for i in range(len(MEMBERS))],
        "SIM-001": [("mpesa", o + timedelta(days=48), 1.0)],
        "SIM-005": [("mpesa_cancelled", o + timedelta(days=51), 1.0), ("mpesa", o + timedelta(days=52), 1.0)],
        "SIM-002": [("mpesa", o + timedelta(days=66), 0.5), ("mpesa", closes - timedelta(days=20), 1.0)],
        "SIM-003": [("sacco_deduction", o + timedelta(days=76), 0.5), ("sacco_deduction", o + timedelta(days=107), 1.0)],
        "SIM-004": [("sacco_deduction", o + timedelta(days=107), 1.0)],
        "SIM-006": [("mpesa", o + timedelta(days=86), 0.5)],
        "remit": closes - timedelta(days=14),
        "confirm_remit": closes - timedelta(days=10),
        "refund": closes + timedelta(days=6),
    }
    every = [d for k, v in days.items() if k.startswith("SIM-") for _, d, _ in v] + days["enrol"]
    if max(every + [days["confirm_remit"]]) > closes or min(every) < opens:
        raise SimulationError("the scripted calendar does not fit this ward's sales window (it is set for Ward A)")
    return days


# ------------------------------------------------------------------ the season
def run_season(year: int = 2008, ward_id: str = "ward-a", cfg=None, book=None, tables=None,
               out_dir: Path | None = None, progress=print) -> dict:
    """Replay one season end to end. Returns the result (also written to out_dir if given)."""
    from agroshield_pricing.config import load_config
    cfg = cfg or load_config(REPO / "config")
    if book is None or tables is None:
        progress("pricing the wards with the engine (rate book and season tables)")
        book, tables = _engine_inputs(cfg, ward_id)
    cal = cfg.calendar(ward_id, "LR")
    opens, closes = cal.sales_window_for(year)
    plan = _schedule(opens, closes)
    within = cfg.monitoring.payout_within_days
    window_start = date(year, *(int(x) for x in cal.planting_window.start.split("-")))

    tmp = tempfile.TemporaryDirectory(prefix="agroshield-sim-", ignore_cleanup_errors=True)
    engine = make_engine(f"sqlite:///{(Path(tmp.name) / 'season.db').as_posix()}")
    clock = SimClock(datetime.combine(opens, time(8, 0), tzinfo=NAIROBI))
    try:
        with clock.installed():
            factory = init_db(engine)
            s = factory()
            try:
                result = _replay(cfg, book, tables, s, clock, year, ward_id, opens, closes, plan, within, window_start,
                                 out_dir, progress)
                s.commit()
            finally:
                s.close()
    finally:
        engine.dispose()
        tmp.cleanup()
    result["checks"] = check(result, within)
    if out_dir is not None:
        write(result, out_dir)
    return result


def _replay(cfg, book, tables, s, clock, year, ward_id, opens, closes, plan, within, window_start, out_dir,
            progress) -> dict:
    vault = Vault(secrets.token_bytes(32), secrets.token_bytes(32))        # throwaway keys for a throwaway database
    base_ctx = services.Context(cfg, book, vault, NotConnected(), today=opens, mpesa=mpesa.SimulatedDaraja())
    sender = sms.LogOnlySender()                                             # recorded, never sent
    ins, sacco, officer, manager, under = _people(s)
    s.commit()
    ward = cfg.ward(ward_id)
    steps: dict[str, dict] = {}
    pols: dict[str, Policy] = {}

    def ctx_on(d: date):
        return dataclasses.replace(base_ctx, today=d)

    def member_row(p: Policy) -> dict:
        return {"member_no": p.farmer.member_no, "name": p.farmer.full_name, "phone": p.farmer.phone_masked,
                "national_id": p.farmer.national_id_masked, "language": p.farmer.language}

    # ---------------------------------------------------------------- enrolment (inside the day loop, at 10:00)
    enrol_events = []
    enrol_on = {d: m for m, d in zip(MEMBERS, plan["enrol"])}

    def enrol(m: dict, d: date) -> None:
        clock.at(d, 10, 0)
        inp = EnrolmentInput(member_no=m["member_no"], full_name=m["full_name"], phone=m["phone"],
                             national_id=m["national_id"], gender=m["gender"], ward_id=ward_id, acreage=m["acreage"],
                             layers=["B"], sum_insured_kes_per_acre=m["sum_insured"], payment_route=m["route"],
                             loan_linked=bool(m.get("loan_ref")), loan_ref=m.get("loan_ref"),
                             consent_data_processing=True, consent_sms=m["sms"],
                             consent_loan_linked_payout=bool(m.get("loan_ref")), resilience=m["resilience"],
                             season="LR", year=year, language=m["language"])
        p = services.enrol(ctx_on(d), s, sacco, officer, inp)
        pols[m["member_no"]] = p
        s.commit()
        enrol_events.append({"date": _iso(clock.current), **member_row(p), "policy_no": p.policy_no,
                             "acres": p.acres, "sum_insured_kes": (p.sum_insured_per_acre or 0) * p.acres,
                             "gross_kes": p.gross_kes, "government_share_kes": p.government_share_kes,
                             "discount_kes": p.discount_kes, "farmer_pays_kes": p.amount_due_kes,
                             "route": p.payment_route, "loan_linked": p.loan_linked, "sms_consent": m["sms"],
                             "sales_closes_on": p.sales_closes_on.isoformat(), "subsidy_status": p.subsidy_status,
                             "index_version": p.quote_snapshot["basis"]["index_versions"].get("layer_b")})

    # ---------------------------------------------------------------- the day loop
    pay_events, close_events, mon_runs, transitions, series = [], [], [], [], []
    money_steps: dict = {}
    day_actions: dict[date, list] = {}
    for no, items in plan.items():
        if no.startswith("SIM-"):
            for i, (how, d, upto) in enumerate(items):
                day_actions.setdefault(d, []).append((no, how, upto, i + 1))
    confirm_dates: list[date] = []
    approvals, payouts_paid, missed = [], [], {}
    complete_on: date | None = None
    end: date | None = None
    deduction_no = 0
    d = plan["enrol"][0]
    prev_key = None
    hard_stop = date(year, 12, 31)
    while d <= hard_stop and (end is None or d <= end):
        c = ctx_on(d)
        # 06:00 the daily job: sales close and reminders, then ward monitoring
        clock.at(d, 6, 0)
        if d <= closes + timedelta(days=1):
            res = services.close_sales_windows(c, s)
            if res["lapsed"] or res["reminders"] or res["lapse_deferred"]:
                close_events.append({"date": d.isoformat(), **res})
        if d >= window_start - timedelta(days=1):
            for st in monitoring.run_monitoring(c, s, as_of=d, mode="replay", year=year, wards=[ward_id]):
                mon_runs.append(st.id)
                key = (st.phase, st.level, tuple(st.result.get("confirmed", [])))
                if st.projected_wrsi is not None and st.phase != "before_season":
                    series.append((d.isoformat(), st.projected_wrsi))
                if key != prev_key:
                    transitions.append({"date": d.isoformat(), "phase": st.phase, "level": st.level,
                                        "projected_wrsi": st.projected_wrsi, "data_through": _iso(st.data_through),
                                        "rain_pct_of_normal": st.result.get("rain_pct_of_normal"),
                                        "confirmed": list(st.result.get("confirmed", [])),
                                        "says": L.t("en", f"ward.{monitoring.ward_key(st)}")})
                    prev_key = key
                if st.phase == "complete" and complete_on is None:
                    complete_on = d
        s.commit()
        new_confirm = sorted({p.confirmed_on for p in s.scalars(select(Payout))} - set(confirm_dates))
        confirm_dates += new_confirm

        # 10:00 onwards: what people do that day
        if d in enrol_on:
            enrol(enrol_on[d], d)
        for no, how, upto, n in day_actions.get(d, []):
            p = pols[no]
            clock.at(d, 11, 0)
            target = p.amount_due_kes if upto >= 1.0 else int(p.amount_due_kes * upto)
            amount = int(round(target - p.paid_kes))
            ev = {"date": _iso(clock.current), "member_no": no, "policy_no": p.policy_no, "instalment": n}
            if how.startswith("mpesa"):
                req = mpesa.request_premium(c, s, p, amount, officer.username)
                ev.update(channel="M-Pesa STK push (simulated)", amount_kes=amount, phone=req.phone_masked,
                          pushed_at=_iso(clock.current))
                clock.advance(minutes=1)
                out = mpesa.handle_callback(c, s, c.mpesa.simulate_callback(req, success=how == "mpesa"))
                s.refresh(req)
                ev.update(callback_at=_iso(clock.current), callback=out["outcome"], request_status=req.status,
                          receipt=req.receipt)
            else:
                deduction_no += 1
                ref = f"SIM-DED-{deduction_no:04d}"
                services.record_payment(c, s, p, amount, "sacco_deduction", ref, manager.username)
                ev.update(channel="SACCO deduction", amount_kes=amount, callback="recorded", receipt=ref)
            ev.update(paid_kes=p.paid_kes, balance_kes=p.balance_kes, status=p.status)
            pay_events.append(ev)
            s.commit()

        if d == plan["remit"]:
            clock.at(d, 15, 0)
            before = settlement.summary(s, ins.id)
            amt = before["rows"][0]["outstanding_kes"]
            r = settlement.record(s, manager, f"{amt:.2f}", d.isoformat(), "bank_transfer", "SIM-BANK-0001",
                                  "Simulation: premium collected to date, sent gross", period=f"{year}-LR", today=d)
            money_steps["remitted"] = {"date": _iso(clock.current), "ref": r.ref, "amount_kes": r.amount_kes,
                                       "by": manager.username, "method": r.method, "reference": r.reference,
                                       "collected_before_kes": before["rows"][0]["collected_kes"],
                                       "paybill": before["paybill"]}
            s.commit()
        if d == plan["confirm_remit"]:
            clock.at(d, 10, 30)
            r = settlement.review(s, under, money_steps["remitted"]["ref"], "confirmed", "Simulation: received in full")
            after = settlement.summary(s, ins.id)
            money_steps["confirmed"] = {"date": _iso(clock.current), "by": under.username, "status": r.status,
                                        "summary": {k: after["total"][k] for k in
                                                    ("collected_kes", "remitted_kes", "confirmed_kes", "outstanding_kes")}}
            m = uw.money(s, ins)
            money_steps["underwriter_money"] = {"farmer_premium_kes": m["total"]["farmer_kes"],
                                                "mpesa_kes": m["total"]["mpesa_kes"],
                                                "sacco_deduction_kes": m["total"]["sacco_deduction_kes"],
                                                "outstanding_kes": m["total"]["due_kes"],
                                                "kaip_receivable_kes": m["total"]["subsidy_kes"],
                                                "gross_kes": m["total"]["gross_kes"]}
            s.commit()
        if d == plan["refund"]:
            clock.at(d, 12, 0)
            for p in pols.values():
                owed = services.refund_outstanding(s, p)
                if p.status == "lapsed_unpaid" and owed > 0:
                    rf = settlement.record_refund(s, manager, p, f"{owed:.2f}", d.isoformat(), "sacco_account",
                                                  f"SIM-RF-{p.farmer.member_no}", "Simulation: cover did not start",
                                                  today=d)
                    close_events.append({"date": _iso(clock.current), "refund": rf.ref, "member_no": p.farmer.member_no,
                                         "amount_kes": rf.amount_kes, "method": rf.method})
            s.commit()

        # Underwriter approval the day after a trigger confirms; the SACCO manager pays two days later.
        for p in s.scalars(select(Payout).where(Payout.status == "calculated").order_by(Payout.id)).all():
            if d >= p.confirmed_on + timedelta(days=1):
                clock.at(d, 9, 30)
                monitoring.approve(c, s, p, under.username)
                approvals.append({"date": _iso(clock.current), "payout_id": p.id, "member_no": p.policy.farmer.member_no,
                                  "kind": p.kind, "amount_kes": p.amount_kes, "status": p.status, "by": under.username,
                                  "confirmed_on": p.confirmed_on.isoformat(), "due_by": p.due_by.isoformat(),
                                  "days_left": (p.due_by - d).days})
        s.commit()
        for p in s.scalars(select(Payout).where(Payout.status.in_(("approved", "issued"))).order_by(Payout.id)).all():
            if d >= p.confirmed_on + timedelta(days=3):
                clock.at(d, 14, 0)
                ref = (f"SIM-LOAN-CR-{p.policy.farmer.member_no}" if p.method == "sacco_loan"
                       else f"SIM-AGRO-{p.policy.farmer.member_no}" if p.method == "voucher" else None)
                monitoring.pay(c, s, p, manager.username, ref)
                paid_on = _nairobi(p.paid_at).date()
                payouts_paid.append({"date": _iso(p.paid_at), "payout_id": p.id, "member_no": p.policy.farmer.member_no,
                                     "name": p.policy.farmer.full_name, "policy_no": p.policy.policy_no, "kind": p.kind,
                                     "share": p.share, "amount_kes": p.amount_kes, "method": p.method,
                                     "reference": p.reference, "status": p.status, "by": manager.username,
                                     "confirmed_on": p.confirmed_on.isoformat(), "due_by": p.due_by.isoformat(),
                                     "paid_on": paid_on.isoformat(), "days_after_confirmation": (paid_on - p.confirmed_on).days,
                                     "within_window": (paid_on - p.confirmed_on).days <= within and paid_on <= p.due_by})
        s.commit()

        # Basis-risk channel: a farmer says the payout was too small (or that none came), over USSD.
        cash = [x for x in payouts_paid if x["kind"] != "replant_voucher"]
        report_day = (date.fromisoformat(cash[0]["paid_on"]) + timedelta(days=2) if cash
                      else complete_on + timedelta(days=5) if complete_on else None)
        if report_day and d == report_day and "report" not in missed:
            clock.at(d, 8, 15)
            who = pols["SIM-002"]
            before = [(x.id, x.amount_kes, x.status) for x in s.scalars(select(Payout).order_by(Payout.id))]
            r = monitoring.report_missed(c, s, who.farmer, "payout_too_small" if cash else "failed_no_payout", "ussd", "ussd")
            missed["report"] = {"date": _iso(clock.current), "ref": r.ref, "member_no": who.farmer.member_no,
                                "category": r.category, "channel": r.channel, "snapshot": r.index_snapshot}
            missed["_before"] = before
            s.commit()
        if "report" in missed and "review" not in missed and d == date.fromisoformat(missed["report"]["date"][:10]) + timedelta(days=6):
            clock.at(d, 16, 0)
            r = s.scalar(select(MissedPayoutReport).where(MissedPayoutReport.ref == missed["report"]["ref"]))
            monitoring.review_missed(s, r, "basis_risk_recorded",
                                     "Simulated field visit: the loss on this farm looks worse than the ward index "
                                     "shows. Recorded for the index review. The payout does not change.", manager.username)
            after = [(x.id, x.amount_kes, x.status) for x in s.scalars(select(Payout).order_by(Payout.id))]
            missed["review"] = {"date": _iso(clock.current), "outcome": r.outcome, "note": r.review_note,
                                "by": manager.username, "payouts_unchanged": missed.pop("_before") == after}
            s.commit()

        # 18:00 the SMS outbox is sent with the log-only sender (SMS_MODE=log: recorded, not sent)
        clock.at(d, 18, 0)
        sms.send_pending(s, sender, vault)
        s.commit()

        if complete_on and end is None:
            last = max(confirm_dates) if confirm_dates else complete_on
            end = max(last + timedelta(days=within + 1), complete_on + timedelta(days=12))
        d += timedelta(days=1)
    if complete_on is None:
        raise SimulationError(f"the {year} season did not complete by {hard_stop}")
    progress(f"replayed {len(mon_runs)} daily monitoring runs; season complete on {complete_on}")

    steps["enrolment"] = {"date": plan["enrol"][0].isoformat(), "end": plan["enrol"][-1].isoformat(),
                          "events": enrol_events}

    steps["premium"] = {"date": pay_events[0]["date"][:10], "end": pay_events[-1]["date"][:10], "events": pay_events}
    steps["settlement"] = {"date": money_steps["remitted"]["date"][:10], "end": money_steps["confirmed"]["date"][:10],
                           **money_steps}
    lapse_day = next((e["date"] for e in close_events if e.get("lapsed")), (closes + timedelta(days=1)).isoformat())
    steps["sales_close"] = {"date": lapse_day[:10], "closes": closes.isoformat(), "events": close_events,
                            "status": {no: {"status": p.status, "paid_kes": p.paid_kes, "refund_due_kes": p.refund_due_kes,
                                            "cover_active_from": _iso(p.cover_active_from)} for no, p in pols.items()}}
    first_mon = s.get(WardStatus, mon_runs[0])
    steps["monitoring"] = {"date": first_mon.as_of.isoformat(), "end": s.get(WardStatus, mon_runs[-1]).as_of.isoformat(),
                           "runs": len(mon_runs), "mode": "replay", "transitions": transitions, "series": series,
                           "complete_on": complete_on.isoformat(),
                           "audited": len(s.scalars(select(AuditEvent.id).where(AuditEvent.action == "trigger.calculated")).all())}

    # ---------------------------------------------------------------- trigger confirmation
    payouts = list(s.scalars(select(Payout).order_by(Payout.confirmed_on, Payout.id)))
    if payouts:
        st = payouts[-1].ward_status
        steps["trigger"] = {"date": payouts[0].confirmed_on.isoformat(), "dates": [x.isoformat() for x in confirm_dates],
                            "ward_status_id": st.id, "as_of": st.as_of.isoformat(), "data_through": _iso(st.data_through),
                            "phase": st.phase, "level": st.level, "confirmed": st.result.get("confirmed"),
                            "events": st.result.get("events"), "final_wrsi": st.projected_wrsi,
                            "share": st.projected_share, "trigger_wrsi": st.result.get("trigger_wrsi"),
                            "exit_wrsi": st.result.get("exit_wrsi"), "index_version": st.index_version,
                            "inputs_sha256": st.inputs_sha256, "sos": st.result.get("sos"),
                            "season_end": st.result.get("season_end"),
                            "config_sha256": st.result.get("config_sha256", {}).get("product.yaml"),
                            "payouts": [{"member_no": x.policy.farmer.member_no, "kind": x.kind, "share": x.share,
                                         "amount_kes": x.amount_kes, "method": x.method, "due_by": x.due_by.isoformat(),
                                         "policy_status": x.policy.status} for x in payouts],
                            "no_payout_for": [no for no, p in pols.items() if p.status != "active"]}
        steps["approval"] = {"date": approvals[0]["date"][:10], "events": approvals}
        steps["payout"] = {"date": payouts_paid[0]["date"][:10], "end": payouts_paid[-1]["date"][:10],
                           "within_days": within, "events": payouts_paid}
    else:
        final = s.get(WardStatus, mon_runs[-1])
        steps["trigger"] = {"date": complete_on.isoformat(), "none": True, "final_wrsi": final.projected_wrsi,
                            "index_version": final.index_version}

    msgs = list(s.scalars(select(SmsMessage).order_by(SmsMessage.created_at, SmsMessage.id)))
    by_farmer = {p.farmer_id: p.farmer for p in pols.values()}
    steps["sms"] = {"date": _iso(max(m.sent_at for m in msgs))[:10] if msgs else None,
                    "sender": sender.name, "count": len(msgs),
                    "statuses": sorted({m.status for m in msgs}),
                    "messages": [{"queued": _iso(m.created_at), "sent": _iso(m.sent_at), "status": m.status,
                                  "member_no": by_farmer[m.farmer_id].member_no, "phone": by_farmer[m.farmer_id].phone_masked,
                                  "language": m.language, "template": m.template, "body": m.body} for m in msgs],
                    "no_consent": [p.farmer.member_no for p in pols.values() if not sms.sms_consent(s, p.farmer)]}
    steps["missed_payout"] = {"date": missed["report"]["date"][:10], **missed}

    # ---------------------------------------------------------------- month-end: bordereaux and reinsurer summary
    last_day = (end or complete_on)
    month_end = date(last_day.year, last_day.month, calendar.monthrange(last_day.year, last_day.month)[1])
    clock.at(month_end, 17, 0)
    c = ctx_on(month_end)
    files = []
    for month in sorted(uw.months_with_activity(s, ins)):
        data, manifest = uw.bordereaux(s, ins, month, dict(cfg.file_hashes))
        name = f"bordereaux-{ins.code}-{month}.zip"
        sha = hashlib.sha256(data).hexdigest()
        audit(s, under.username, "bordereaux.exported", "insurer", str(ins.id), month=month, file_sha256=sha)
        files.append({"month": month, "file": f"bordereaux/{name}", "sha256": sha, "data": data,
                      "premium_rows": manifest["files"]["premium.csv"]["rows"],
                      "payout_rows": manifest["files"]["payouts.csv"]["rows"], "manifest": manifest})
    steps["bordereaux"] = {"date": month_end.isoformat(), "files": files}

    pf = uw.portfolio(c, s, ins)
    asif = uw.as_if_losses(c, s, ins, tables, "LR", year)
    esg = uw.esg(s, ins, within)
    mon = uw.money(s, ins)
    steps["reinsurer"] = {"date": month_end.isoformat(),
                          "portfolio": {"policies": pf["policies"], "active": pf["active"], "acres": pf["acres"],
                                        "sum_insured_kes": pf["sum_insured_kes"],
                                        "in_force_sum_insured_kes": pf["in_force_sum_insured_kes"],
                                        "gross_kes": pf["gross_kes"],
                                        "exposure": [{k: e[k] for k in ("ward", "label", "max_loss_kes", "policies")}
                                                     for e in pf["exposure"]]},
                          "as_if": {k: asif[k] for k in ("label", "sum_insured_kes", "seasons", "years", "expected_loss_kes",
                                                         "loss_1_in_10_kes", "loss_1_in_20_kes", "max_kes", "worst_years",
                                                         "gross_premium_kes")},
                          "esg": {k: esg[k] for k in ("farmers", "women_share", "payouts_paid", "paid_to_farmers_kes",
                                                      "replay_excluded", "target_days", "missed_reports")},
                          "payouts_by_status": mon["payouts"]}
    s.commit()

    total_payout = sum(x["amount_kes"] for x in payouts_paid)
    return {"label": LABEL, "fictional": True, "year": year, "season": "LR",
            "ward": {"id": ward_id, "display_name": ward.label, "config_name": ward.name, "illustrative": ward.illustrative},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "index_version": cfg.product.layer_b.version, "config_sha256": dict(cfg.file_hashes),
            "rainfall": {"source": "CHIRPS v2.0 daily (committed record)", "file": f"data/raw/chirps/{ward_id}.csv",
                         "sha256": _sha_file(REPO / "data" / "raw" / "chirps" / f"{ward_id}.csv")},
            "sales_window": [opens.isoformat(), closes.isoformat()], "payout_within_days": within,
            "insurer": ins.name, "sacco": sacco.name, "members": len(pols), "payout_total_kes": total_payout,
            "steps": {k: steps[k] for k in STEP_ORDER if k in steps}}


def _sha_file(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# ------------------------------------------------------------------ checks
def check(result: dict, within: int) -> dict:
    """Every step is there, dated and in order; every payout landed inside the window. Raises SimulationError."""
    steps = result["steps"]
    # A season with no trigger has nothing to approve or pay.
    no_trigger = bool(steps.get("trigger", {}).get("none"))
    required = [k for k in STEP_ORDER if not (no_trigger and k in ("approval", "payout"))]
    missing = [k for k in required if k not in steps or not steps[k].get("date")]
    if missing:
        raise SimulationError(f"steps missing or undated: {', '.join(missing)}")
    # The SMS log runs all season (its date is the last message), so it is not placed in the order.
    ordered = [k for k in required if k != "sms"]
    dates = [date.fromisoformat(steps[k]["date"][:10]) for k in ordered]
    out_of_order = [f"{a} after {b}" for (a, da), (b, db) in zip(zip(ordered[1:], dates[1:]), zip(ordered, dates))
                    if da < db]
    if out_of_order:
        raise SimulationError("steps out of order: " + "; ".join(out_of_order))
    paid = steps.get("payout", {}).get("events", [])
    late = [p for p in paid if not p["within_window"] or p["days_after_confirmation"] > within]
    if late:
        raise SimulationError(f"{len(late)} payouts landed outside the {within}-day window")
    if steps["trigger"].get("none") is None and not paid:
        raise SimulationError("a trigger confirmed but nothing was paid")
    if any(st != "logged" for st in steps["sms"]["statuses"]):
        raise SimulationError("an SMS was not log-only")
    review = steps["missed_payout"].get("review")
    if not review or not review.get("payouts_unchanged"):
        raise SimulationError("the missed-payout report was not reviewed, or it changed a payout")
    return {"all_steps_present": True, "in_order": True, "payouts": len(paid),
            "max_days_to_pay": max((p["days_after_confirmation"] for p in paid), default=None),
            "all_within_window": True, "window_days": within, "sms_log_only": True,
            "missed_report_reviewed_without_changing_payouts": True}


# ------------------------------------------------------------------ output
def _chart(series: list[tuple[str, float]], trig: float, exit_: float, width: int = 900, height: int = 260) -> dict:
    """Inline SVG geometry: projected WRSI by day, with the trigger and exit lines."""
    if not series:
        return {}
    pad_l, pad_r, pad_t, pad_b = 44, 16, 14, 30
    lo, hi = min(40.0, min(v for _, v in series) - 5), 100.0
    d0 = date.fromisoformat(series[0][0])
    span = max(1, (date.fromisoformat(series[-1][0]) - d0).days)

    def x(ds): return round(pad_l + (width - pad_l - pad_r) * (date.fromisoformat(ds) - d0).days / span, 1)

    def y(v): return round(pad_t + (height - pad_t - pad_b) * (hi - v) / (hi - lo), 1)
    months = []
    m = date(d0.year, d0.month, 1)
    while m <= date.fromisoformat(series[-1][0]):
        if m >= d0:
            months.append({"x": x(m.isoformat()), "label": m.strftime("%b")})
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return {"w": width, "h": height, "points": " ".join(f"{x(ds)},{y(v)}" for ds, v in series),
            "trig_y": y(trig), "exit_y": y(exit_), "x0": pad_l, "x1": width - pad_r, "base": height - pad_b,
            "ticks": [{"y": y(v), "v": v} for v in (100, 80, 60, 40) if lo <= v <= hi], "months": months,
            "last": {"x": x(series[-1][0]), "y": y(series[-1][1]), "v": series[-1][1]}}


def render_html(result: dict) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    from .docstyle import css
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "web" / "templates"),
                      autoescape=select_autoescape(["html"]))
    env.filters["kes"] = lambda v: "KES " + (f"{v:,.2f}" if v is not None and round(v % 1, 2) else f"{(v or 0):,.0f}")
    env.filters["pct"] = lambda v: "" if v is None else f"{v:.0%}"
    env.filters["day"] = lambda v: date.fromisoformat(v[:10]).strftime("%a %d %b %Y") if v else ""
    tr = result["steps"]["trigger"]
    chart = _chart(result["steps"]["monitoring"]["series"], tr.get("trigger_wrsi") or 80, tr.get("exit_wrsi") or 50)
    clock = []
    if "payout" in result["steps"]:
        c0 = date.fromisoformat(tr["date"])
        appr = {date.fromisoformat(a["date"][:10]) for a in result["steps"]["approval"]["events"]}
        paid = {date.fromisoformat(p["paid_on"]) for p in result["steps"]["payout"]["events"]}
        for i in range(result["payout_within_days"] + 1):
            dd = c0 + timedelta(days=i)
            what = (["Trigger confirmed"] if i == 0 else []) + (["Underwriter approved"] if dd in appr else []) + \
                   (["Paid"] if dd in paid else []) + (["Deadline"] if i == result["payout_within_days"] else [])
            clock.append({"n": i, "date": dd.strftime("%d %b"), "what": what,
                          "hit": any(w != "Deadline" for w in what), "due": i == result["payout_within_days"]})
    return env.get_template("season_report.html").render(r=result, css=css(), chart=chart, clock=clock,
                                                          order=STEP_ORDER)


def write(result: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    (out_dir / "bordereaux").mkdir(parents=True, exist_ok=True)
    for old in (out_dir / "bordereaux").glob("*.zip"):
        old.unlink()
    for f in result["steps"]["bordereaux"]["files"]:
        (out_dir / f["file"]).write_bytes(f["data"])
    clean = json.loads(json.dumps(result, default=lambda o: None if isinstance(o, bytes) else str(o)))
    for f in clean["steps"]["bordereaux"]["files"]:
        f.pop("data", None)
    (out_dir / "season.json").write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                         newline="\n")
    (out_dir / "index.html").write_text(render_html(result), encoding="utf-8", newline="\n")
    return out_dir / "index.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="simulate-season", description="SIMULATION / REPLAY of one season, end to end, "
                                 "in a throwaway database with fictional members")
    ap.add_argument("--year", type=int, default=2008, help="planting year of the long rains to replay (default 2008)")
    ap.add_argument("--ward", default="ward-a", help="pilot ward (the scripted calendar fits Ward A)")
    ap.add_argument("--out", help="output folder (default docs/remaining/season-<year>)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else REPO / "docs" / "remaining" / f"season-{a.year}"
    res = run_season(a.year, a.ward, out_dir=out)
    ck = res["checks"]
    print(f"{LABEL}: {res['ward']['display_name']} long rains {a.year}, {res['members']} fictional members")
    if ck["payouts"]:
        print(f"  {ck['payouts']} payouts, KES {res['payout_total_kes']:,.2f}; slowest paid {ck['max_days_to_pay']} days "
              f"after the trigger confirmed (limit {ck['window_days']})")
    else:
        print(f"  no trigger this season (final index {res['steps']['trigger'].get('final_wrsi')}): no payouts")
    print(f"  report: {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
