"""Phase 5 (milestone 10): the IRA documentation pack and the simulated 2008 season at Ward A.

The pack (docs/ira) must be marked DRAFT and ILLUSTRATIVE on every page and in every file, its manifest must hold the
SHA-256 of every file, and its numbers must be the engine's. The simulated season must run end to end on the real
services, cover every step in order, and pay within the 10-day window. Farmers are fictional.
"""
import csv
import datetime as dt
import hashlib
import importlib.util
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from pypdf import PdfReader

from agroshield_platform import simulate
from conftest import REPO

IRA = REPO / "docs" / "ira"
SEASON = REPO / "docs" / "remaining" / "season-2008"
MARKS = ("DRAFT", "ILLUSTRATIVE")
CLEAR_PII = ("0712 100 00", "0712100", "+254712100", "254712100", "9100000")    # the fictional phones and IDs


def _build_pack_module():
    spec = importlib.util.spec_from_file_location("build_pack", REPO / "tools" / "ira" / "build_pack.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_pack(folder: Path) -> dict:
    """Every file is listed with the right SHA-256 and size, and every page and file carries both marks."""
    man = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert all(m in man["marking"] for m in MARKS) and "to be named" in man["insurer"]
    on_disk = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}
    assert {f["path"] for f in man["files"]} == on_disk
    for f in man["files"]:
        p = folder / f["path"]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"], f["path"]
        assert p.stat().st_size == f["bytes"]
        if p.suffix == ".pdf":
            for i, page in enumerate(PdfReader(p).pages):
                text = page.extract_text() or ""
                assert all(m in text for m in MARKS), f"page {i + 1} is not marked"
                assert "\u2014" not in text
        else:
            text = p.read_text(encoding="utf-8")
            assert all(m in text for m in MARKS), f["path"]
            assert "\u2014" not in text, f"em dash in {f['path']}"
    return man


# ------------------------------------------------------------------ the committed pack
def test_committed_pack_is_marked_and_its_hashes_match():
    man = check_pack(IRA)
    pdfs = [f for f in man["files"] if f["path"].endswith(".pdf")]
    assert len(pdfs) == 1 and len(PdfReader(IRA / pdfs[0]["path"]).pages) > 10
    names = {f["path"] for f in man["files"]}
    assert {"pack.html", "disclosure.html", "data/figures.json", "data/pricing_summary.csv",
            "data/data_sources.csv"} <= names


def test_pack_covers_every_section_honestly():
    html = (IRA / "pack.html").read_text(encoding="utf-8")
    for heading in ("Policy wording (placeholder)", "Pricing methodology", "Index development",
                    "Data sources and provenance", "Backtest results", "Basis risk statement", "Payout timeline",
                    "Consumer disclosure", "Data protection summary"):
        assert heading in html
    assert "Partner insurer (to be named)" in html and "PLACEHOLDER" in html
    assert "pending native-speaker review" in html and 'lang="sw"' in html
    assert "<img" not in html                                       # no IRA (or any) logo
    assert "not submitted" in html.lower() and "approved" in html
    assert "mrnwanngari" not in html                                # weather user-agent contact left out
    assert "within <b>10 days</b>" in html                         # monitoring.payout_within_days


def test_pack_numbers_are_the_engines():
    from agroshield_pricing.report import write_json
    figs = json.loads((IRA / "data" / "figures.json").read_text(encoding="utf-8"))
    html = (IRA / "pack.html").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO((IRA / "data" / "pricing_summary.csv").read_text(encoding="utf-8")
                                           .split("\n", 1)[1])))
    for wid, f in figs["wards"].items():
        eng = json.loads((IRA / "data" / f"engine_{wid}.json").read_text(encoding="utf-8"))
        assert eng["results_sha256"] == eng["manifest"]["results_sha256"] == f["run"]["results_sha256"]
        assert eng["manifest"]["command"] == "agroshield-price run --all --offline --out var/ira-engine-run"
        # The embedded results, written exactly as the engine writes them, give the engine's own SHA-256.
        buf = REPO / "var" / f"test-ira-{wid}.json"
        buf.parent.mkdir(exist_ok=True)
        write_json(buf, eng["results"])
        assert hashlib.sha256(buf.read_bytes()).hexdigest() == eng["results_sha256"]
        buf.unlink()
        L = eng["results"]["seasons"]["LR"]
        assert f["burn_cost"] == L["burn_cost"] and f["premium"] == L["premium"]
        for o in L["premium"]["per_acre"]:
            assert f"KES {o['gross_premium_kes']:,.2f}" in html
            row = next(r for r in rows if r["ward_id"] == wid and float(r["sum_insured_kes_per_acre"]) == o["sum_insured_kes_per_acre"])
            assert float(row["gross_premium_kes_per_acre"]) == o["gross_premium_kes"]
        backtest = (IRA / "data" / f"backtest_{wid}.csv").read_text(encoding="utf-8").splitlines()
        assert backtest[0].startswith("# DRAFT / ILLUSTRATIVE") and len(backtest) == 2 + len(L["history"])


def test_pack_data_sources_checksums_still_match():
    rows = list(csv.DictReader(io.StringIO((IRA / "data" / "data_sources.csv").read_text(encoding="utf-8")
                                           .split("\n", 1)[1])))
    priced = [r for r in rows if r["file"].startswith(("data/raw/chirps/", "data/raw/nasapower/"))]
    assert len(priced) == 4 and all(r["status"] == "matches" and r["retrieved_at"] for r in priced)
    recorded = {}
    for meta in (REPO / "data" / "raw").glob("*/*.meta.json"):
        name = meta.name.removesuffix(".meta.json")
        data = meta.parent / (name if "." in name else name + ".csv")
        recorded[data.relative_to(REPO).as_posix()] = json.loads(meta.read_text(encoding="utf-8"))
    assert {r["file"] for r in rows} == set(recorded)
    for r in rows:
        assert recorded[r["file"]]["sha256"] == r["sha256_recorded"]
        assert recorded[r["file"]].get("retrieved_at", "") == r["retrieved_at"]
        assert r["status"] != "DIFFERS"


def test_pack_builds_from_scratch(tmp_path):
    bp = _build_pack_module()
    out = tmp_path / "ira"
    try:
        man = bp.build(out, pdf=True)
    except RuntimeError as e:                    # no Chromium on this machine: everything else still builds
        man = bp.build(out, pdf=False)
        check_pack(out)
        pytest.skip(f"PDF not printed: {e}")
    assert man["pdf_printed_by"]
    check_pack(out)
    assert sum(f["path"].endswith(".pdf") for f in man["files"]) == 1


# ------------------------------------------------------------------ the simulated season
@pytest.fixture(scope="module")
def season(tmp_path_factory):
    out = tmp_path_factory.mktemp("season-2008")
    return simulate.run_season(2008, "ward-a", out_dir=out, progress=lambda *_: None), out


def test_simulation_covers_every_step_in_order(season):
    res, _ = season
    S = res["steps"]
    assert tuple(S) == simulate.STEP_ORDER
    days = [date.fromisoformat(S[k]["date"][:10]) for k in simulate.STEP_ORDER]
    assert days == sorted(days)
    assert res["checks"]["all_steps_present"] and res["checks"]["in_order"]
    opens, closes = (date.fromisoformat(x) for x in res["sales_window"])
    assert opens <= days[0] and date.fromisoformat(S["premium"]["end"]) <= closes
    assert res["ward"]["display_name"] == "Rongai West" and res["label"] == "SIMULATION / REPLAY"
    # premium: an STK push with its callback, a cancelled push, SACCO deductions and instalments
    ev = S["premium"]["events"]
    assert any(e["callback"] == "paid" and e["pushed_at"] for e in ev if "pushed_at" in e)
    assert any(e["callback"] == "failed" for e in ev)
    assert any(e["channel"] == "SACCO deduction" for e in ev)
    assert any(e["instalment"] == 2 for e in ev)
    # settlement recorded by the SACCO and confirmed by the underwriter before the close
    assert S["settlement"]["confirmed"]["status"] == "confirmed"
    assert S["settlement"]["confirmed"]["summary"]["outstanding_kes"] == 0
    # sales close: reminders, one cover not started, its refund recorded
    assert sum(e.get("reminders", 0) for e in S["sales_close"]["events"]) == 2
    assert [no for no, p in S["sales_close"]["status"].items() if p["status"] != "active"] == ["SIM-006"]
    assert any(e.get("refund") for e in S["sales_close"]["events"])
    # daily monitoring every day, in replay mode
    mon = S["monitoring"]
    span = (date.fromisoformat(mon["end"]) - date.fromisoformat(mon["date"])).days + 1
    assert mon["runs"] == span and mon["mode"] == "replay" and mon["audited"] == span
    assert [t["level"] for t in mon["transitions"]][-1] == "payout"
    # the missed-payout report was reviewed and changed nothing
    assert S["missed_payout"]["review"]["payouts_unchanged"] and S["missed_payout"]["report"]["channel"] == "ussd"
    # bordereaux and reinsurer summary
    assert {f["month"] for f in S["bordereaux"]["files"]} == {"2007-10", "2008-08"}
    assert S["reinsurer"]["as_if"]["seasons"] == 45 and S["reinsurer"]["esg"]["payouts_paid"] == 5


def test_trigger_and_payouts_come_from_the_engine_and_land_within_ten_days(season, cfg):
    from agroshield_pricing.engine import price_ward
    from agroshield_pricing.pet import make_pet_source
    from agroshield_pricing.rainfall import make_source
    res, _ = season
    S = res["steps"]
    table = price_ward(cfg, "ward-a", make_source(cfg, allow_download=False),
                       make_pet_source(cfg, allow_download=False)).seasons["LR"].table
    tr = S["trigger"]
    assert tr["final_wrsi"] == pytest.approx(table.loc[2008, "wrsi"])
    assert tr["share"] == pytest.approx(table.loc[2008, "wrsi_share"], abs=1e-6)
    assert tr["confirmed"] == ["wrsi_final"] and tr["no_payout_for"] == ["SIM-006"]
    enrolled = {e["member_no"]: e for e in S["enrolment"]["events"]}
    window = cfg.monitoring.payout_within_days
    assert res["payout_within_days"] == window == 10
    paid = S["payout"]["events"]
    assert len(paid) == 5
    for p in paid:
        assert p["amount_kes"] == pytest.approx(round(tr["share"] * enrolled[p["member_no"]]["sum_insured_kes"], 2))
        confirmed, on = date.fromisoformat(p["confirmed_on"]), date.fromisoformat(p["paid_on"])
        assert confirmed == date.fromisoformat(tr["date"])
        assert 0 <= (on - confirmed).days <= window and on <= date.fromisoformat(p["due_by"])
        assert date.fromisoformat(p["due_by"]) == confirmed + timedelta(days=window)
        assert p["within_window"] and p["status"] == "paid"
    assert {p["method"] for p in paid} == {"mpesa", "sacco_loan"}
    approvals = {a["member_no"]: a for a in S["approval"]["events"]}
    assert all(approvals[p["member_no"]]["date"] < p["date"] for p in paid)
    assert res["checks"]["all_within_window"] and res["checks"]["max_days_to_pay"] <= window


def test_a_late_payout_fails_the_check(season):
    res, _ = season
    late = json.loads(json.dumps(res, default=str))
    late["steps"]["payout"]["events"][0].update(days_after_confirmation=11, within_window=False)
    with pytest.raises(simulate.SimulationError, match="outside the 10-day window"):
        simulate.check(late, 10)


def test_check_accepts_a_season_with_no_trigger_or_an_early_last_sms(season):
    res, _ = season
    # A year with no trigger (for example --year 2010) has nothing to approve or pay.
    quiet = json.loads(json.dumps(res, default=str))
    S = quiet["steps"]
    del S["approval"], S["payout"]
    S["trigger"] = {"date": S["trigger"]["date"], "none": True, "final_wrsi": 95.0, "index_version": "B-1.2.0"}
    ck = simulate.check(quiet, 10)
    assert ck["payouts"] == 0 and ck["max_days_to_pay"] is None
    assert "no trigger, so no payout" in simulate.render_html(quiet)
    # The SMS log runs all season: its last message may come before the last payout (a voucher-only year, 2007).
    early = json.loads(json.dumps(res, default=str))
    early["steps"]["sms"]["date"] = early["steps"]["approval"]["date"]
    simulate.check(early, 10)
    # A step really out of order still fails.
    bad = json.loads(json.dumps(res, default=str))
    bad["steps"]["approval"]["date"] = bad["steps"]["enrolment"]["date"]
    with pytest.raises(simulate.SimulationError, match="out of order"):
        simulate.check(bad, 10)


def test_pack_build_will_not_replace_an_unrelated_folder(tmp_path):
    bp = _build_pack_module()
    (tmp_path / "keep.txt").write_text("not a pack", encoding="utf-8")
    with pytest.raises(SystemExit, match="no earlier IRA pack"):
        bp.build(tmp_path, pdf=False, runs={})
    assert (tmp_path / "keep.txt").exists()


def test_sms_are_logged_never_sent_and_only_with_consent(season):
    res, _ = season
    sms = res["steps"]["sms"]
    assert sms["sender"] == "log" and sms["statuses"] == ["logged"]
    assert sms["no_consent"] == ["SIM-004"] and not [m for m in sms["messages"] if m["member_no"] == "SIM-004"]
    templates = {m["template"] for m in sms["messages"]}
    assert {"enrolled", "cover_active", "payment_received", "reminder", "lapsed", "payout_calculated", "payout_paid",
            "payout_paid_loan"} <= templates
    assert all(m["sent"] >= m["queued"] for m in sms["messages"])            # on the replayed calendar
    assert all(m["queued"][:4] in ("2007", "2008") for m in sms["messages"])
    assert {m["language"] for m in sms["messages"]} == {"en", "sw"}


def test_outputs_are_labelled_fictional_and_masked(season):
    res, out = season
    html = (out / "index.html").read_text(encoding="utf-8")
    js = (out / "season.json").read_text(encoding="utf-8")
    assert "SIMULATION / REPLAY" in html and "(fictional)" in html and "ILLUSTRATIVE" in html
    assert "\u2014" not in html
    for text in (html, js):
        assert not any(x in text for x in CLEAR_PII)
    for f in res["steps"]["bordereaux"]["files"]:
        data = (out / f["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == f["sha256"]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            man = json.loads(z.read("manifest.json"))
            for name in ("premium.csv", "payouts.csv"):
                body = z.read(name)
                assert hashlib.sha256(body).hexdigest() == man["files"][name]["sha256"]
                assert not any(x.encode() in body for x in CLEAR_PII)
    assert json.loads(js)["checks"] == res["checks"]


def test_the_clock_is_put_back():
    from agroshield_platform import models, monitoring, sms
    for m in (models, monitoring, sms):
        assert m.datetime is dt.datetime


def test_committed_season_report():
    js = json.loads((SEASON / "season.json").read_text(encoding="utf-8"))
    assert js["label"] == "SIMULATION / REPLAY" and js["fictional"] and js["year"] == 2008
    assert js["checks"]["all_within_window"] and js["checks"]["max_days_to_pay"] <= js["payout_within_days"]
    html = (SEASON / "index.html").read_text(encoding="utf-8")
    assert "SIMULATION / REPLAY" in html and not any(x in html for x in CLEAR_PII)
    for f in js["steps"]["bordereaux"]["files"]:
        assert hashlib.sha256((SEASON / f["file"]).read_bytes()).hexdigest() == f["sha256"]
