"""SACCO-to-insurer premium settlement and the underwriter workspace polish (overnight brief, Phase D).

Reuses the two-insurer world from test_uw: each insurer has one SACCO whose members paid in January 2008.
"""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, Payment, Policy, PremiumRemittance, Sacco

from test_platform import assert_no_pii, book, login, settings  # noqa: F401
from test_uw import PEOPLE, world  # noqa: F401


def no_member_data(text):
    for people in PEOPLE.values():
        for _, nid, phone in people:
            assert_no_pii(text, nid, phone)


def collected(app, code):
    with transaction(app.state.factory) as s:
        sacco = s.scalar(select(Sacco).where(Sacco.code == code))
        return sum(pm.amount_kes for pm in s.scalars(select(Payment).join(Policy).where(Policy.sacco_id == sacco.id)))


def remit(c, tok, **kw):
    data = {"csrf_token": tok, "amount": "1000", "remitted_on": "2008-02-01", "method": "bank_transfer",
            "reference": "BANK-001", "period": "2008-LR", "note": ""}
    return c.post("/reports/premium", data={**data, **kw}, follow_redirects=False)


def test_manager_records_remittance_and_sees_outstanding(world):  # noqa: F811
    c = TestClient(world)
    tok = login(c, "man-UW1")
    total = collected(world, "SUW1")
    assert total > 1000
    page = c.get("/reports/premium").text
    assert "No money sent yet" in page and f"KES {total:,.0f}" in page
    assert remit(c, tok).status_code == 303
    page = c.get("/reports/premium").text
    assert "BANK-001" in page and "waiting" in page
    assert f"KES {total - 1000:,.0f}" in page                            # still to send = collected minus sent
    with transaction(world.state.factory) as s:
        r = s.scalar(select(PremiumRemittance))
        assert r.amount_kes == 1000 and r.recorded_by == "man-UW1" and r.status == "recorded"
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "remittance.recorded"))
        assert ev.entity_id == r.ref and ev.details["amount_kes"] == 1000
    assert "Premium sent to the insurer" in c.get("/reports").text


@pytest.mark.parametrize("bad, message", [
    ({"amount": "abc"}, "amount in shillings"),
    ({"amount": "0"}, "above zero"),
    ({"remitted_on": "2099-01-01"}, "future"),
    ({"remitted_on": ""}, "date the money was sent"),
    ({"method": "cash-in-envelope"}, "how the money was sent"),
    ({"reference": "x"}, "reference"),
])
def test_remittance_validation(world, bad, message):  # noqa: F811
    c = TestClient(world)
    tok = login(c, "man-UW1")
    r = remit(c, tok, **bad)
    assert r.status_code == 422 and message in r.text
    with transaction(world.state.factory) as s:
        assert s.scalar(select(PremiumRemittance)) is None


def test_duplicate_is_refused_and_a_correction_is_a_negative_entry(world):  # noqa: F811
    c = TestClient(world)
    tok = login(c, "man-UW1")
    assert remit(c, tok, amount="1,500").status_code == 303
    assert remit(c, tok, amount="1500").status_code == 422               # same reference and amount
    assert remit(c, tok, amount="-1500", note="entered twice by mistake").status_code == 303
    with transaction(world.state.factory) as s:
        assert sorted(r.amount_kes for r in s.scalars(select(PremiumRemittance))) == [-1500, 1500]
    assert "Still to send" in c.get("/reports/premium").text


def test_only_managers_record_and_officers_cannot_see_it(world):  # noqa: F811
    c = TestClient(world)
    tok = login(c, "off-UW1")
    assert c.get("/reports/premium").status_code == 403
    assert remit(c, tok).status_code == 403
    u = TestClient(world)
    utok = login(u, "uw-UW1")
    assert remit(u, utok).status_code in (303, 403) and remit(u, utok).headers.get("location") != "/reports/premium"
    with transaction(world.state.factory) as s:
        assert s.scalar(select(PremiumRemittance)) is None


def test_underwriter_confirms_or_queries_only_its_own_saccos(world):  # noqa: F811
    m1, m2 = TestClient(world), TestClient(world)
    remit(m1, login(m1, "man-UW1"), reference="UW1-REF")
    remit(m2, login(m2, "man-UW2"), reference="UW2-REF")
    with transaction(world.state.factory) as s:
        refs = {r.reference: r.ref for r in s.scalars(select(PremiumRemittance))}
    u = TestClient(world)
    tok = login(u, "uw-UW1")
    money = u.get("/uw/money").text
    assert "UW1-REF" in money and "UW2-REF" not in money and "SACCO of UW2" not in money
    no_member_data(money)
    # cannot touch the other insurer's entry
    r = u.post(f"/uw/settlement/{refs['UW2-REF']}", data={"csrf_token": tok, "decision": "confirmed"}, follow_redirects=True)
    assert "No such remittance" in r.text
    # a query needs a reason
    r = u.post(f"/uw/settlement/{refs['UW1-REF']}", data={"csrf_token": tok, "decision": "queried", "note": ""}, follow_redirects=True)
    assert "Say what is wrong" in r.text
    u.post(f"/uw/settlement/{refs['UW1-REF']}", data={"csrf_token": tok, "decision": "queried", "note": "Not on our statement yet"})
    assert "Not on our statement yet" in m1.get("/reports/premium").text      # the SACCO sees the query
    u.post(f"/uw/settlement/{refs['UW1-REF']}", data={"csrf_token": tok, "decision": "confirmed"})
    r = u.post(f"/uw/settlement/{refs['UW1-REF']}", data={"csrf_token": tok, "decision": "queried", "note": "x"}, follow_redirects=True)
    assert "already confirmed" in r.text
    with transaction(world.state.factory) as s:
        r = s.scalar(select(PremiumRemittance).where(PremiumRemittance.reference == "UW1-REF"))
        assert r.status == "confirmed" and r.reviewed_by == "uw-UW1"
        other = s.scalar(select(PremiumRemittance).where(PremiumRemittance.reference == "UW2-REF"))
        assert other.status == "recorded"
        acts = [e.action for e in s.scalars(select(AuditEvent).where(AuditEvent.entity == "premium_remittance"))]
        assert acts.count("remittance.recorded") == 2 and "remittance.queried" in acts and "remittance.confirmed" in acts
    assert "confirmed" in m1.get("/reports/premium").text


def test_settlement_csv_exports_are_scoped_and_audited(world):  # noqa: F811
    m = TestClient(world)
    remit(m, login(m, "man-UW1"), reference="CSV-1", amount="2500")
    r = m.get("/reports/premium.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "record" and rows[1][4] == "CSV-1" and rows[1][6] == "2500.00"
    u = TestClient(world)
    login(u, "uw-UW1")
    body = u.get("/uw/settlement.csv").text
    assert "CSV-1" in body and "SUW2" not in body
    no_member_data(body)
    with transaction(world.state.factory) as s:
        assert len(list(s.scalars(select(AuditEvent).where(AuditEvent.action == "remittance.exported")))) == 2


def test_portfolio_filters_charts_and_csv(world):  # noqa: F811
    u = TestClient(world)
    login(u, "uw-UW1")
    page = u.get("/uw").text
    assert 'class="kpi-strip tiles"' in page and "Exposure by ward" in page and "Premium written by month" in page
    assert "Payout events" in page and 'role="img"' in page
    assert 'value="LR-2008"' in page and 'value="SUW1"' in page and "SUW2" not in page
    assert "Policies written</div><div class=\"v\">2<" in u.get("/uw?season=LR-2008&sacco=SUW1").text
    assert "No policies match these filters" in u.get("/uw?season=LR-1999").text or \
           "Policies written</div><div class=\"v\">2<" in u.get("/uw?season=LR-1999").text   # unknown season is ignored
    assert "Policies written</div><div class=\"v\">2<" in u.get("/uw?sacco=SUW2").text     # another insurer's SACCO is ignored
    r = u.get("/uw/portfolio.csv?season=LR-2008")
    assert r.status_code == 200 and r.text.startswith("group,name,policies")
    assert "SACCO of UW1" in r.text and "SACCO of UW2" not in r.text
    no_member_data(r.text)


def test_first_run_home_for_a_new_sacco(settings, book):  # noqa: F811
    from agroshield_platform.crypto import hash_password
    from agroshield_platform.models import Officer
    from agroshield_platform.web.app import create_app
    from test_platform import PASSWORD
    app = create_app(settings, book)
    with transaction(app.state.factory) as s:
        sacco = Sacco(code="NEW01", name="New SACCO (fictional)", is_demo=True)
        s.add(sacco)
        s.flush()
        s.add(Officer(sacco_id=sacco.id, username="new-man", display_name="New Manager", role="manager",
                      password_hash=hash_password(PASSWORD)))
    c = TestClient(app)
    login(c, "new-man")
    home = c.get("/dashboard").text
    assert "No farmers are enrolled yet" in home and "Enrol your first farmer" in home and 'href="/import"' in home
    assert "Everyone you enrolled has paid" not in home
    assert "No members yet" in c.get("/members").text
    assert "not linked to an insurer" in c.get("/reports/premium").text or "No money sent yet" in c.get("/reports/premium").text
