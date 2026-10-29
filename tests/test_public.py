"""Public site (overnight brief, Phase C): pages, honesty rules, licensed images, and the two local-only forms."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agroshield_platform import content
from agroshield_platform.db import transaction
from agroshield_platform.models import AuditEvent, PublicEnquiry

from test_platform import app, book, csrf_of, settings, vault  # noqa: F401

PAGES = ["/", "/crops", "/livestock", "/how-it-works", "/insurers", "/saccos", "/learn", "/faq", "/credits", "/demo"]
STATIC = Path(__file__).resolve().parents[1] / "src" / "agroshield_platform" / "web" / "static"
HTML = {"accept": "text/html"}


@pytest.fixture
def c(app):  # noqa: F811
    return TestClient(app)


def text_of(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


@pytest.mark.parametrize("path", PAGES + [f"/learn/{a['slug']}" for a in content.ARTICLES])
def test_public_page_renders_with_one_h1_and_honest_copy(c, path):
    r = c.get(path, headers=HTML)
    assert r.status_code == 200
    html = r.text
    assert html.count("<h1") == 1
    body = text_of(html)
    assert "—" not in body                                          # no em dashes in user-facing copy
    for banned in ("Swiss Re", "70,000 livestock", "partnered with", "in partnership with"):
        assert banned not in body, banned
    # every [n] citation points at a numbered source on the same page, and every source has a real link
    cites = set(re.findall(r'href="#src-(\d+)"', html))
    ids = set(re.findall(r'id="src-(\d+)"', html))
    assert cites <= ids, (path, cites - ids)
    for href in re.findall(r'<li id="src-\d+"><a href="([^"]+)"', html):
        assert href.startswith(("https://", "/how-it-works")), href
    # images are self-hosted only (no hot-linked or partner logos) and always have alt text
    for tag in re.findall(r"<img [^>]+>", html):
        src = re.search(r'src="([^"]+)"', tag).group(1)
        assert src.startswith("/static/img/"), src
        assert " alt=" in tag


def test_insurer_is_never_named_and_livestock_is_not_offered(c):
    for path in PAGES:
        body = text_of(c.get(path, headers=HTML).text)
        assert "logo" not in body.lower() or path == "/credits"
    assert "Partner insurer (to be named)".lower() in text_of(c.get("/", headers=HTML).text).lower() or \
           "partner insurer (to be named)" in text_of(c.get("/", headers=HTML).text)
    lv = text_of(c.get("/livestock", headers=HTML).text)
    assert "In development, not yet available" in lv and "cannot be quoted or bought" in lv


def test_articles_cite_only_their_own_sources():
    assert len(content.ARTICLES) == 8
    slugs = {a["slug"] for a in content.ARTICLES}
    assert {"index-insurance", "basis-risk", "crop-index", "kaip-subsidy", "livestock-insurance", "replanting-cover",
            "index-insurance-regulations", "glossary"} == slugs
    for a in content.ARTICLES:
        ns = [s["n"] for s in a["sources"]]
        assert sorted(ns) == list(range(1, len(ns) + 1)), a["slug"]
        used = {int(n) for n in re.findall(r"\[(\d+)\]", json.dumps(a["sections"]) + json.dumps(a.get("glossary") or []))}
        assert used and used <= set(ns), a["slug"]
    reg = text_of(json.dumps(content.article("index-insurance-regulations")))
    assert "draft" in reg.lower()                                          # the 10-day rule is stated as a draft
    gl = content.article("glossary")
    assert all(g["term_sw"] and g["definition_sw"] for g in gl["glossary"])
    assert "pending review by a native speaker" in json.dumps(gl)


def test_learn_hub_lists_every_article_and_unknown_article_is_404(c):
    hub = c.get("/learn", headers=HTML).text
    for a in content.ARTICLES:
        assert f'href="/learn/{a["slug"]}"' in hub
    assert c.get("/learn/no-such-article", headers=HTML).status_code == 404


def test_every_photo_is_licensed_self_hosted_and_credited(c):
    credits = json.loads((STATIC / "img" / "credits.json").read_text(encoding="utf-8"))
    assert credits
    page = c.get("/credits", headers=HTML).text
    for im in credits:
        assert im["license"] in {"CC0", "Public domain", "CC BY 2.0", "CC BY 3.0", "CC BY-SA 2.0", "CC BY-SA 3.0", "CC BY-SA 4.0"}
        assert im["file_page"].startswith("https://commons.wikimedia.org/wiki/File:")
        assert im["author"] and im["alt"]
        for s in im["sizes"]:
            for ext in ("webp", "jpg"):
                assert (STATIC / "img" / f"{im['key']}-{s['w']}.{ext}").exists()
        used = any(f"'{im['key']}'" in (STATIC.parent / "templates" / "public" / f).read_text(encoding="utf-8")
                   for f in ("home.html", "crops.html", "livestock.html", "how-it-works.html", "insurers.html", "saccos.html",
                             "learn.html", "demo.html"))
        assert (im["file_page"] in page) == used, im["key"]                    # every photo on a page is credited there
    doc = (STATIC.parents[3] / "docs" / "design" / "IMAGE_CREDITS.md").read_text(encoding="utf-8")
    assert all(im["file_page"] in doc for im in credits)


def form(tok, **kw):
    base = {"csrf_token": tok, "name": "Test Person (fictional)", "email": "test.person@example.org",
            "org_type": "insurer", "organisation": "Example Re (fictional)", "consent": "yes"}
    return {**base, **kw}


def test_demo_request_is_stored_locally_encrypted_and_audited(c, app, vault):  # noqa: F811
    tok = csrf_of(c.get("/demo", headers=HTML).text)
    r = c.post("/demo", data=form(tok, phone="0712 345 678", message="Call me on 0712345678 please"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/demo#form"
    assert "?" not in r.headers["location"]                                # nothing personal in the URL
    page = c.get("/demo", headers=HTML).text
    with transaction(app.state.factory) as s:
        e = s.scalar(select(PublicEnquiry))
        assert e.kind == "demo" and e.ref in page and "Your details are saved" in page
        assert "test.person@example.org" not in (e.email_enc + e.name_enc)
        assert vault.decrypt(e.email_enc, "enquiry.email") == "test.person@example.org"
        assert e.email_masked == "t***@example.org" and e.phone_masked.endswith("678") and "345" not in e.phone_masked
        assert "0712345678" not in e.message                               # free text scrubbed
        assert e.consent_text.startswith("I agree")
        ev = s.scalar(select(AuditEvent).where(AuditEvent.action == "enquiry.demo"))
        assert ev is not None and "example.org" not in json.dumps(ev.details)
    assert "Your details are saved" not in c.get("/demo", headers=HTML).text   # the thank-you shows once


@pytest.mark.parametrize("bad, message", [
    ({"consent": ""}, "tick the box"),
    ({"email": "not-an-email"}, "email address"),
    ({"name": ""}, "your name"),
    ({"org_type": "bank"}, "who you are"),
    ({"phone": "12345"}, "phone number"),
])
def test_demo_request_rejects_bad_input_and_stores_nothing(c, app, bad, message):
    tok = csrf_of(c.get("/demo", headers=HTML).text)
    r = c.post("/demo", data=form(tok, **bad))
    assert r.status_code == 422 and message in r.text
    assert 'value="Example Re (fictional)"' in r.text                       # what was typed is kept
    with transaction(app.state.factory) as s:
        assert s.scalar(select(PublicEnquiry)) is None


def test_public_forms_reject_bots_double_posts_and_missing_csrf(c, app):
    tok = csrf_of(c.get("/demo", headers=HTML).text)
    assert c.post("/demo", data=form("wrong")).status_code == 403
    assert c.post("/demo", data=form(tok, website="http://spam.example")).status_code == 400
    assert c.post("/demo", data=form(tok), follow_redirects=False).status_code == 303
    assert c.post("/demo", data=form(tok), follow_redirects=False).status_code == 429   # second post straight away
    with transaction(app.state.factory) as s:
        assert len(list(s.scalars(select(PublicEnquiry)))) == 1


def test_livestock_register_interest(c, app):
    page = c.get("/livestock", headers=HTML).text
    assert 'action="/livestock#form"' in page and "No email is sent" in page
    r = c.post("/livestock", data=form(csrf_of(page), org_type="herder", county="Marsabit"), follow_redirects=False)
    assert r.status_code == 303
    with transaction(app.state.factory) as s:
        e = s.scalar(select(PublicEnquiry))
        assert e.kind == "livestock_interest" and e.county == "Marsabit" and e.org_type == "herder"
