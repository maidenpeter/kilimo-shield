"""agroshield-portal: set up SACCOs and officers, and run the SACCO portal.

    agroshield-portal add-sacco --code NKR01 --name "Example SACCO"
    agroshield-portal add-officer --sacco NKR01 --username jane --name "Jane W." --role manager
    agroshield-portal demo          # fictional SACCO, officer and members for a local look
    agroshield-portal serve --port 8780

Passwords are read from AGROSHIELD_OFFICER_PASSWORD or prompted for; never passed as arguments.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from sqlalchemy import select

from .crypto import ScrubFilter, hash_password
from .db import audit, init_db, make_engine, transaction
from .models import Officer, Sacco
from .settings import load_settings

DEMO_PASSWORD = "demo-only-change-me"
DEMO_CSV = """member_no,full_name,phone,national_id,gender,ward_id,acreage,lat,lon,layers,sum_insured_kes_per_acre,payment_route,loan_linked,loan_ref,consent_data_processing,consent_sms,consent_loan_linked_payout,resilience
D-0001,Wanjiku Kamau (fictional),0712 000 001,90000001,female,ward-a,2,,,B,10000,sacco_deduction,no,,yes,yes,no,certified_seed_verified;sacco_good_standing
D-0002,Kiprono Langat (fictional),0712 000 002,90000002,male,ward-a,3.5,,,"A,B",10000,mpesa,yes,LN-0042,yes,yes,yes,practices_verified
D-0003,Akinyi Otieno (fictional),0712 000 003,90000003,female,ward-b,1.5,,,B,5000,sacco_deduction,no,,yes,no,no,
D-0004,Mwangi Njoroge (fictional),0712 000 004,90000004,male,ward-b,25,,,B,15000,sacco_deduction,yes,LN-0107,yes,yes,yes,irrigation_partial;sacco_good_standing
"""


def _password() -> str:
    pw = os.environ.get("AGROSHIELD_OFFICER_PASSWORD") or getpass.getpass("Password for the officer: ")
    if len(pw) < 10:
        sys.exit("password must be at least 10 characters")
    return pw


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(ScrubFilter())
    ap = argparse.ArgumentParser(prog="agroshield-portal")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-sacco")
    a.add_argument("--code", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--county", default="Nakuru")
    o = sub.add_parser("add-officer")
    o.add_argument("--sacco", required=True, help="SACCO code")
    o.add_argument("--username", required=True)
    o.add_argument("--name", required=True)
    o.add_argument("--role", choices=["officer", "manager"], default="officer")
    sub.add_parser("demo", help="create a fictional SACCO, a demo manager and four fictional members")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8780)
    args = ap.parse_args(argv)

    settings = load_settings()
    factory = init_db(make_engine(settings.database_url))

    if args.cmd == "add-sacco":
        with transaction(factory) as s:
            s.add(Sacco(code=args.code.upper(), name=args.name, county=args.county))
            audit(s, "cli", "sacco.created", "sacco", args.code.upper())
        print(f"SACCO {args.code.upper()} added")
    elif args.cmd == "add-officer":
        with transaction(factory) as s:
            sacco = s.scalar(select(Sacco).where(Sacco.code == args.sacco.upper()))
            if sacco is None:
                sys.exit(f"no SACCO with code {args.sacco}")
            s.add(Officer(sacco_id=sacco.id, username=args.username, display_name=args.name,
                          password_hash=hash_password(_password()), role=args.role))
            audit(s, "cli", "officer.created", "officer", args.username, role=args.role)
        print(f"officer {args.username} added to {sacco.code}")
    elif args.cmd == "demo":
        return _demo(settings, factory)
    elif args.cmd == "serve":
        import uvicorn
        from .web.app import create_app
        if settings.dev_keys:
            logging.getLogger("agroshield").warning("running with development keys; do not use with real farmer data")
        uvicorn.run(create_app(settings), host=args.host, port=args.port)
    return 0


def _demo(settings, factory) -> int:
    from agroshield_pricing.config import load_config
    from agroshield_pricing.pet import make_pet_source
    from agroshield_pricing.quote import RateBook
    from agroshield_pricing.rainfall import make_source

    from . import services
    from .crypto import Vault
    from .kiamis import CsvKiamis

    if not settings.dev_keys:
        sys.exit("demo data is only for development databases (no real keys set)")
    with transaction(factory) as s:
        if s.scalar(select(Sacco).where(Sacco.code == "DEMO")):
            print("demo already set up: sign in as demo-manager")
            return 0
        sacco = Sacco(code="DEMO", name="Demo SACCO (fictional)")
        s.add(sacco)
        s.flush()
        officer = Officer(sacco_id=sacco.id, username="demo-manager", display_name="Demo Manager",
                          password_hash=hash_password(DEMO_PASSWORD), role="manager")
        s.add(officer)
        s.flush()
        cfg = load_config(settings.config_dir)
        vault = Vault(settings.encryption_key, settings.lookup_key)
        book = RateBook.build(cfg, make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False))
        pols = services.bulk_commit(services.Context(cfg, book, vault, CsvKiamis(vault)), s, sacco, officer, DEMO_CSV)
    print(f"demo SACCO with {len(pols)} fictional members; sign in as demo-manager / {DEMO_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
