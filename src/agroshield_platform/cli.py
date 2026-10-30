"""agroshield-portal: set up SACCOs and officers, run the SACCO portal and its daily job.

    agroshield-portal add-insurer --code UW01 --name "Example Insurer"
    agroshield-portal add-sacco --code NKR01 --name "Example SACCO" --insurer UW01
    agroshield-portal add-officer --sacco NKR01 --username jane --name "Jane W." --role manager
    agroshield-portal add-officer --insurer UW01 --username amina --name "Amina K." --role underwriter
    agroshield-portal add-officer --username ops1 --name "Ops One" --role ops   # AgroShield operations
    agroshield-portal set-paybill --insurer UW01 --paybill "Paybill 123456, account AGROSHIELD"
    agroshield-portal demo          # fictional demo SACCO, manager and members (development keys only)
    agroshield-portal serve --port 8780
    agroshield-portal daily         # M-Pesa re-check, sales close and reminders, ward monitoring, KMD check, send SMS
    agroshield-portal mpesa-recheck # status check of M-Pesa payments without a final answer (run every 5 minutes)
    agroshield-portal monitor [--as-of 2027-05-20] [--download]   # ward rainfall status and payouts
    agroshield-portal monitor --replay-year 2008 --as-of 2008-09-01  # replay a past season (labelled)
    agroshield-portal weather-fetch # polite KMD check (at most once per page every 6 hours)
    agroshield-portal send-sms      # send queued SMS now
    agroshield-portal enquiries     # demo requests and livestock interest from the public site (masked)
    agroshield-portal enquiries --delete AB12CD34   # delete one on request (audited)

Passwords are read from AGROSHIELD_OFFICER_PASSWORD or prompted for; never passed as arguments.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from sqlalchemy import select

from .crypto import ScrubFilter, Vault, hash_password
from .db import audit, init_db, make_engine, transaction
from .models import Insurer, Officer, Sacco
from .settings import REPO, load_settings

DEMO_PASSWORD = "demo-only-change-me"
# Fictional smallholders (0.5 to 5 acres, so nobody owes more than a few thousand shillings).
# Ward B's long-rains sales window opens on 1 December, so the demo enrols at Ward A only.
DEMO_CSV = """member_no,full_name,phone,national_id,gender,ward_id,acreage,lat,lon,layers,sum_insured_kes_per_acre,payment_route,loan_linked,loan_ref,consent_data_processing,consent_sms,consent_loan_linked_payout,resilience,language
D-0001,Wanjiku Kamau (fictional),0712 000 001,90000001,female,ward-a,2,,,B,10000,sacco_deduction,no,,yes,yes,no,certified_seed_verified;sacco_good_standing,sw
D-0002,Kiprono Langat (fictional),0712 000 002,90000002,male,ward-a,3.5,,,B,10000,mpesa,yes,LN-0042,yes,yes,yes,practices_verified,en
D-0003,Akinyi Otieno (fictional),0712 000 003,90000003,female,ward-a,1.5,,,B,5000,mpesa,no,,yes,no,no,,en
D-0004,Mwangi Njoroge (fictional),0712 000 004,90000004,male,ward-a,4.5,,,B,10000,sacco_deduction,yes,LN-0107,yes,yes,yes,irrigation_partial;sacco_good_standing,sw
D-0005,Chebet Rotich (fictional),0712 000 005,90000005,female,ward-a,0.5,,,B,10000,mpesa,no,,yes,yes,no,,sw
D-0006,Otieno Ouma (fictional),0712 000 006,90000006,male,ward-a,5,,,B,10000,sacco_deduction,no,,yes,yes,no,certified_seed_verified,en
"""


DEMO2_CSV = """member_no,full_name,phone,national_id,gender,ward_id,acreage,lat,lon,layers,sum_insured_kes_per_acre,payment_route,loan_linked,loan_ref,consent_data_processing,consent_sms,consent_loan_linked_payout,resilience,language
M-0001,Nafula Wekesa (fictional),0712 000 011,90000011,female,ward-a,3,,,B,10000,mpesa,no,,yes,yes,no,certified_seed_verified,sw
M-0002,Kamau Gitau (fictional),0712 000 012,90000012,male,ward-a,2.5,,,B,15000,sacco_deduction,no,,yes,yes,no,,en
"""


def _password() -> str:
    pw = os.environ.get("AGROSHIELD_OFFICER_PASSWORD") or getpass.getpass("Password for the officer: ")
    if len(pw) < 10:
        sys.exit("password must be at least 10 characters")
    return pw


def _context(settings):
    from agroshield_pricing.config import load_config
    from agroshield_pricing.pet import make_pet_source
    from agroshield_pricing.quote import RateBook
    from agroshield_pricing.rainfall import make_source

    from . import mpesa, services
    from .kiamis import CsvKiamis
    cfg = load_config(settings.config_dir)
    vault = Vault(settings.encryption_key, settings.lookup_key)
    book = RateBook.build(cfg, make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False))
    cb = f"{settings.mpesa.callback_base_url.rstrip('/')}/mpesa/callback/{settings.callback_token}"
    return services.Context(cfg, book, vault, CsvKiamis(vault), mpesa=mpesa.make_client(settings.mpesa, cb),
                            ussd_code=settings.ussd_code)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(ScrubFilter())
    ap = argparse.ArgumentParser(prog="agroshield-portal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("add-insurer")
    i.add_argument("--code", required=True)
    i.add_argument("--name", required=True)
    a = sub.add_parser("add-sacco")
    a.add_argument("--code", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--county", default="Nakuru")
    a.add_argument("--insurer", help="insurer code that underwrites this SACCO's cover")
    o = sub.add_parser("add-officer")
    o.add_argument("--sacco", help="SACCO code (officers and managers)")
    o.add_argument("--insurer", help="insurer code (underwriters)")
    o.add_argument("--username", required=True)
    o.add_argument("--name", required=True)
    o.add_argument("--role", choices=["officer", "manager", "underwriter", "ops"], default="officer")
    pb = sub.add_parser("set-paybill", help="where SACCOs send premium for an insurer (shown on the remittance screen)")
    pb.add_argument("--insurer", required=True)
    pb.add_argument("--paybill", required=True, help='e.g. "Paybill 123456, account AGROSHIELD" or bank details')
    sub.add_parser("mpesa-recheck", help="status-check M-Pesa payments still waiting for an answer")
    sub.add_parser("demo", help="create a fictional demo SACCO, a demo officer and manager, and fictional members")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8780)
    dl = sub.add_parser("daily", help="sales close and reminders, ward monitoring, KMD check, send SMS")
    dl.add_argument("--download", action="store_true", help="fetch the latest CHIRPS for monitoring")
    mo = sub.add_parser("monitor", help="ward rainfall status; confirmed triggers create payouts")
    mo.add_argument("--as-of", type=lambda v: __import__("datetime").date.fromisoformat(v))
    mo.add_argument("--replay-year", type=int, help="replay a past season from the committed history (labelled replay)")
    mo.add_argument("--download", action="store_true", help="fetch the latest CHIRPS (live mode)")
    sub.add_parser("weather-fetch", help="check enabled weather sources politely")
    sub.add_parser("send-sms", help="send queued SMS")
    en = sub.add_parser("enquiries", help="list public-site demo requests and livestock interest (contact details masked)")
    en.add_argument("--delete", metavar="REF", help="delete one enquiry, for example when the person asks")
    args = ap.parse_args(argv)

    settings = load_settings()
    factory = init_db(make_engine(settings.database_url))

    def insurer(code):
        ins = s.scalar(select(Insurer).where(Insurer.code == code.upper()))
        if ins is None:
            sys.exit(f"no insurer with code {code}")
        return ins

    if args.cmd == "add-insurer":
        with transaction(factory) as s:
            s.add(Insurer(code=args.code.upper(), name=args.name))
            audit(s, "cli", "insurer.created", "insurer", args.code.upper())
        print(f"insurer {args.code.upper()} added")
    elif args.cmd == "add-sacco":
        with transaction(factory) as s:
            ins = insurer(args.insurer) if args.insurer else None
            s.add(Sacco(code=args.code.upper(), name=args.name, county=args.county, is_demo=False,
                        insurer_id=ins.id if ins else None))
            audit(s, "cli", "sacco.created", "sacco", args.code.upper())
        print(f"SACCO {args.code.upper()} added")
    elif args.cmd == "add-officer":
        with transaction(factory) as s:
            if args.role == "ops":
                if args.insurer or args.sacco:
                    sys.exit("AgroShield operations staff belong to neither a SACCO nor an insurer")
                org = "AgroShield operations"
                s.add(Officer(username=args.username, display_name=args.name,
                              password_hash=hash_password(_password()), role="ops"))
            elif args.role == "underwriter":
                if not args.insurer or args.sacco:
                    sys.exit("an underwriter belongs to an insurer (--insurer), not a SACCO")
                where = insurer(args.insurer)
                org = where.code
                s.add(Officer(insurer_id=where.id, username=args.username, display_name=args.name,
                              password_hash=hash_password(_password()), role="underwriter"))
            else:
                where = s.scalar(select(Sacco).where(Sacco.code == (args.sacco or "").upper()))
                if where is None:
                    sys.exit(f"no SACCO with code {args.sacco}")
                org = where.code
                s.add(Officer(sacco_id=where.id, username=args.username, display_name=args.name,
                              password_hash=hash_password(_password()), role=args.role))
            audit(s, "cli", "officer.created", "officer", args.username, role=args.role)
        print(f"{args.role} {args.username} added to {org}")
    elif args.cmd == "set-paybill":
        paybill = " ".join(args.paybill.split())[:60]
        if len(paybill) < 4:
            sys.exit("give the paybill or bank details")
        with transaction(factory) as s:
            ins = insurer(args.insurer)
            old, ins.premium_paybill = ins.premium_paybill, paybill
            audit(s, "cli", "insurer.paybill_set", "insurer", ins.code, old=old or "", new=paybill)
        print(f"premium paybill for {ins.code} set")
    elif args.cmd == "mpesa-recheck":
        from . import mpesa
        ctx = _context(settings)
        with transaction(factory) as s:
            print("mpesa:", mpesa.recheck(ctx, s))
    elif args.cmd == "demo":
        return _demo(settings, factory)
    elif args.cmd == "serve":
        import uvicorn
        from .web.app import create_app
        if settings.dev_keys:
            logging.getLogger("agroshield").warning("running with development keys; do not use with real farmer data")
        if settings.mpesa_recheck_seconds > 0:
            _start_recheck(settings, factory)
        uvicorn.run(create_app(settings), host=args.host, port=args.port, log_config=_uvicorn_log_config())
    elif args.cmd == "monitor":
        from . import monitoring
        ctx = _context(settings)
        with transaction(factory) as s:
            for st in monitoring.run_monitoring(ctx, s, as_of=args.as_of, year=args.replay_year,
                                                mode="replay" if args.replay_year else "live",
                                                allow_download=args.download):
                print(f"{st.ward_id} {st.season} {st.year} as of {st.as_of}: {st.phase} / {st.level}"
                      f" (data to {st.data_through}, projected WRSI {st.projected_wrsi})")
        with transaction(factory) as s:
            from . import sms
            sms.send_pending(s, sms.make_sender(settings.sms), ctx.vault)
    elif args.cmd == "enquiries":
        from .enquiries import delete, listing
        if args.delete:
            with transaction(factory) as s:
                print("deleted" if delete(s, args.delete, "cli") else f"no enquiry {args.delete}")
            return 0
        with transaction(factory) as s:
            rows = listing(s)
            for e in rows:
                print(f"{e.created_at:%Y-%m-%d %H:%M}  {e.ref}  {e.kind:<18} {e.org_type:<9} {e.email_masked:<28} "
                      f"{e.organisation or '':<30} {e.status}")
            print(f"{len(rows)} enquiries. Stored locally only; nothing was emailed.")
    elif args.cmd == "weather-fetch":
        from . import weather
        with transaction(factory) as s:
            print(weather.fetch(s, settings.config_dir, REPO))
    elif args.cmd in ("daily", "send-sms"):
        from . import monitoring, services, sms, weather
        ctx = _context(settings)
        with transaction(factory) as s:
            if args.cmd == "daily":
                from . import mpesa
                print("mpesa:", mpesa.recheck(ctx, s))          # before the lapse, so confirmed payments count
                print(services.close_sales_windows(ctx, s))
                for st in monitoring.run_monitoring(ctx, s, allow_download=args.download):
                    print(f"{st.ward_id} {st.season} {st.year}: {st.phase} / {st.level}")
        if args.cmd == "daily":
            try:
                with transaction(factory) as s:
                    print("weather:", weather.fetch(s, settings.config_dir, REPO))
            except Exception as e:                  # weather is display only; never blocks the daily job
                print("weather check failed:", type(e).__name__)
        with transaction(factory) as s:
            print("sms:", sms.send_pending(s, sms.make_sender(settings.sms), ctx.vault) or "nothing queued")
    return 0


def _start_recheck(settings, factory) -> None:
    """While the portal runs, re-check unconfirmed M-Pesa payments every MPESA_RECHECK_SECONDS (a daemon thread;
    each round is its own transaction, and an error in one round never stops the next)."""
    import threading

    from . import mpesa
    log = logging.getLogger("agroshield.mpesa")

    def loop():
        ctx = _context(settings)
        while not stop.wait(settings.mpesa_recheck_seconds):
            try:
                with transaction(factory) as s:
                    res = mpesa.recheck(ctx, s)
                if res["checked"]:
                    log.info("M-Pesa re-check: %s", res)
            except Exception:
                log.exception("M-Pesa re-check failed; will try again")
    stop = threading.Event()
    threading.Thread(target=loop, name="mpesa-recheck", daemon=True).start()


def _uvicorn_log_config() -> dict:
    """uvicorn's own logging, plus filters: the callback token in /ussd/<token> and /mpesa/callback/<token> is
    redacted from access lines, and IDs and phone numbers are masked in every uvicorn line."""
    import copy

    from uvicorn.config import LOGGING_CONFIG
    cfg = copy.deepcopy(LOGGING_CONFIG)
    cfg["filters"] = {"scrub": {"()": "agroshield_platform.crypto.ScrubFilter"},
                      "token": {"()": "agroshield_platform.crypto.CallbackTokenFilter"}}
    for h in cfg["handlers"].values():
        h["filters"] = ["token", "scrub"]
    return cfg


def _demo(settings, factory) -> int:
    from . import mpesa, services, sms

    if not settings.dev_keys:
        sys.exit("demo data is only for development databases (no real keys set)")
    ctx = _context(settings)
    with transaction(factory) as s:
        if s.scalar(select(Sacco).where(Sacco.code == "DEMO")):
            print("demo already set up: sign in as demo-officer or demo-manager")
            return 0
        ins = Insurer(code="DEMOUW", name="Demo Insurer (fictional)", is_demo=True)
        s.add(ins)
        s.flush()
        sacco = Sacco(code="DEMO", name="Demo SACCO (fictional)", is_demo=True, insurer_id=ins.id)
        s.add(sacco)
        s.flush()
        s.add(Officer(insurer_id=ins.id, username="demo-underwriter", display_name="Demo Underwriter",
                      password_hash=hash_password(DEMO_PASSWORD), role="underwriter"))
        officer = Officer(sacco_id=sacco.id, username="demo-manager", display_name="Demo Manager",
                          password_hash=hash_password(DEMO_PASSWORD), role="manager")
        s.add_all([officer, Officer(sacco_id=sacco.id, username="demo-officer", display_name="Grace (demo officer)",
                                    password_hash=hash_password(DEMO_PASSWORD), role="officer")])
        s.flush()
        pols = services.bulk_commit(ctx, s, sacco, officer, DEMO_CSV)
        # Payments, so every state shows: paid in full, part paid by M-Pesa, nothing yet, part by deduction.
        services.record_payment(ctx, s, pols[0], pols[0].amount_due_kes, "sacco_deduction", "DEMO-DED-0001", officer.username)
        if ctx.mpesa.env == "simulated":
            req = mpesa.request_premium(ctx, s, pols[1], max(50, pols[1].amount_due_kes // 2), officer.username)
            mpesa.handle_callback(ctx, s, ctx.mpesa.simulate_callback(req, success=True))
            mpesa.request_premium(ctx, s, pols[2], pols[2].amount_due_kes, officer.username)   # left pending
        services.record_payment(ctx, s, pols[3], 1000, "sacco_deduction", "DEMO-DED-0004", officer.username)
        _demo_replay(ctx, s, sacco, officer)
        # A second distributor for the same insurer, so the underwriter sees more than one SACCO.
        second = Sacco(code="DEMO2", name="Demo Molo SACCO (fictional)", is_demo=True, insurer_id=ins.id)
        s.add(second)
        s.flush()
        services.bulk_commit(ctx, s, second, officer, DEMO2_CSV)
        # One fictional remittance of part of the collected premium, waiting for the underwriter to confirm.
        from . import settlement
        settlement.record(s, officer, "5000", ctx.date().isoformat(), "bank_transfer", "DEMO-BANK-0001",
                          "fictional demo remittance", period=f"{ctx.date().year + 1}-LR", today=ctx.date())
    with transaction(factory) as s:
        sms.send_pending(s, sms.make_sender(settings.sms), ctx.vault)
    print(f"demo SACCOs with fictional members; sign in as demo-officer, demo-manager or demo-underwriter / {DEMO_PASSWORD}")
    return 0


def _demo_replay(ctx, s, sacco, officer) -> None:
    """REPLAY of the 2008 long rains at Ward A (a real drought season in the committed CHIRPS record), so the
    Payout Tracker has something to show. Labelled "replay" everywhere; the farmers are the same fictional ones."""
    import dataclasses
    from datetime import date, datetime

    from . import monitoring, services
    past = dataclasses.replace(ctx, today=date(2007, 12, 15))          # inside the LR 2008 sales window
    pols = services.bulk_commit(past, s, sacco, officer, "\n".join(DEMO_CSV.strip().splitlines()[:5]) + "\n")
    for i, pol in enumerate(pols[:3]):                                  # three paid in time; one never paid
        services.record_payment(past, s, pol, pol.amount_due_kes, "sacco_deduction", f"DEMO-2008-{i}", officer.username,
                                received_at=datetime(2008, 1, 20, 10, 0, tzinfo=services.NAIROBI))
    services.close_sales_windows(dataclasses.replace(ctx, today=date(2008, 2, 15)), s)   # the unpaid one lapses
    for as_of in (date(2008, 4, 20), date(2008, 6, 1), date(2008, 9, 1)):
        monitoring.run_monitoring(dataclasses.replace(ctx, today=as_of), s, as_of=as_of, mode="replay", year=2008,
                                  wards=["ward-a"])
    # The underwriter approves two payouts (the SACCO pays one of them); the third waits for a decision.
    from .models import Payout
    pays = s.scalars(select(Payout).order_by(Payout.id)).all()
    for p in pays[:2]:
        monitoring.approve(ctx, s, p, "demo-underwriter")
    if pays:
        monitoring.pay(ctx, s, pays[0], officer.username, "DEMO-SACCO-CR-1" if pays[0].method == "sacco_loan" else None)


if __name__ == "__main__":
    raise SystemExit(main())
