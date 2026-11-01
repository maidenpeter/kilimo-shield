"""Navbar behaviour in a real browser (Chrome). Brief section 3: every role, five widths, keyboard and touch.

Skipped when Playwright or Chrome is not installed.
"""
import socket
import threading
import time
from datetime import date

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from agroshield_platform.crypto import hash_password  # noqa: E402
from agroshield_platform.db import transaction  # noqa: E402
from agroshield_platform.models import Insurer, Officer, Sacco  # noqa: E402
from agroshield_platform.web.app import create_app  # noqa: E402

from test_platform import PASSWORD, book, settings  # noqa: E402,F401

WIDTHS = [1440, 1280, 1024, 768, 375]
ROLES = {"public": (None, "/", ["Crops", "Livestock", "How it works", "For insurers", "For SACCOs", "Learn"]),
         "officer": ("officer", "/dashboard", ["Home", "Enrol a farmer", "Members"]),
         "manager": ("manager", "/dashboard", ["Home", "Enrol a farmer", "Members", "Reports", "Import", "Weather"]),
         "underwriter": ("underwriter", "/uw", ["Portfolio", "Triggers and payouts", "Money", "Bordereaux", "Pricing",
                                                 "Photos", "Reinsurer", "Weather"])}

NAV_STATE = """() => {
  const header = document.querySelector('header.site'), nav = header.querySelector('nav.primary');
  const menu = header.querySelector('.menu-btn');
  const shown = el => el && getComputedStyle(el).display !== 'none' && el.offsetParent !== null;
  const links = shown(nav) ? [...nav.querySelectorAll('a')] : [];
  const tops = links.map(a => a.getBoundingClientRect().top);
  return {navShown: shown(nav), menuShown: shown(menu), bar: Math.round(header.querySelector('.bar').getBoundingClientRect().height),
          rows: tops.length ? Math.round(Math.max(...tops) - Math.min(...tops)) : 0, labels: links.map(a => a.textContent.trim()),
          overflow: shown(nav) && nav.scrollWidth > nav.clientWidth + 1, pageScroll: document.documentElement.scrollWidth > innerWidth};
}"""


@pytest.fixture(scope="module")
def server(tmp_path_factory, cfg):
    import base64
    import secrets
    import uvicorn
    from agroshield_platform.settings import Settings
    from agroshield_pricing.quote import RateBook, WardRates
    from conftest import REPO
    db = tmp_path_factory.mktemp("nav") / "nav.db"
    settings = Settings(database_url=f"sqlite:///{db.as_posix()}", encryption_key=secrets.token_bytes(32),
                        lookup_key=secrets.token_bytes(32), session_secret=base64.b64encode(secrets.token_bytes(32)).decode(),
                        config_dir=REPO / "config", dev_keys=False)
    book = RateBook(rates={("ward-a", "LR"): WardRates("ward-a", "Ward A", "LR", {5000.0: 1000.0, 10000.0: 2000.0, 15000.0: 3000.0},
                                                       None, None, {"layer_b": "B-test"}, ["ILLUSTRATIVE"]),
                           ("ward-b", "LR"): WardRates("ward-b", "Ward B", "LR", {5000.0: 500.0, 10000.0: 800.0, 15000.0: 900.0},
                                                       None, None, {"layer_b": "B-test"}, ["ILLUSTRATIVE"])},
                    config_sha256=cfg.file_hashes, built_at="test")
    app = create_app(settings, book, today=date(2026, 12, 15))
    with transaction(app.state.factory) as s:
        ins = Insurer(code="NAV", name="Partner insurer (to be named)", is_demo=True)
        s.add(ins)
        s.flush()
        sacco = Sacco(code="NAV01", name="Navbar Test SACCO with a long name", is_demo=True, insurer_id=ins.id)
        s.add(sacco)
        s.flush()
        for role in ("officer", "manager"):
            s.add(Officer(sacco_id=sacco.id, username=role, display_name=f"Test {role.title()} Wanjiru",
                          role=role, password_hash=hash_password(PASSWORD)))
        s.add(Officer(insurer_id=ins.id, username="underwriter", display_name="Test Underwriter Achieng",
                      role="underwriter", password_hash=hash_password(PASSWORD)))
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    th.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome")
        except Exception as e:
            pytest.skip(f"Chrome not available: {e}")
        yield b
        b.close()


def _page(browser, server, user, width):
    ctx = browser.new_context(viewport={"width": width, "height": 800}, has_touch=width < 500)
    page = ctx.new_page()
    if user:
        page.goto(server + "/login")
        page.fill("#username", user)
        page.fill("#password", PASSWORD)
        page.click("form.stack button[type=submit]")
        page.wait_for_load_state("networkidle")
    return ctx, page


@pytest.mark.parametrize("role", list(ROLES))
def test_never_wraps_and_collapses_in_time(browser, server, role):
    user, path, labels = ROLES[role]
    ctx, page = _page(browser, server, user, 1440)
    try:
        for width in WIDTHS:
            page.set_viewport_size({"width": width, "height": 800})
            page.goto(server + path)
            st = page.evaluate(NAV_STATE)
            assert st["navShown"] != st["menuShown"], (role, width, st)          # exactly one of the two
            if st["navShown"]:
                assert st["rows"] <= 2 and not st["overflow"], (role, width, st)  # one row, nothing cut off
                assert st["labels"] == labels, (role, width, st["labels"])
            assert st["bar"] == 64, (role, width, st)                            # fixed height, no layout jump
            assert not st["pageScroll"], (role, width)
    finally:
        ctx.close()


@pytest.mark.parametrize("role", ["public", "manager"])
def test_sticky_shadow_and_current_page(browser, server, role):
    user, path, _ = ROLES[role]
    ctx, page = _page(browser, server, user, 1280)
    try:
        page.goto(server + (path if role == "public" else "/members"))
        h0 = page.evaluate("document.querySelector('header.site').getBoundingClientRect().height")
        assert not page.evaluate("document.querySelector('header.site').classList.contains('scrolled')")
        page.evaluate("document.body.style.minHeight = '3000px'; window.scrollTo(0, 600)")
        page.wait_for_function("document.querySelector('header.site').classList.contains('scrolled')")
        box = page.evaluate("(() => { const r = document.querySelector('header.site').getBoundingClientRect(); return [r.top, r.height]; })()")
        assert box == [0, h0]                                                     # stuck to the top, same height
        assert page.evaluate("getComputedStyle(document.querySelector('header.site')).boxShadow") != "none"
        if role == "manager":
            cur = page.locator("nav.primary a[aria-current='page']")
            assert cur.count() == 1 and cur.inner_text() == "Members"
    finally:
        ctx.close()


def test_keyboard_skip_link_focus_ring_and_account_dropdown(browser, server):
    ctx, page = _page(browser, server, "underwriter", 1440)
    try:
        page.goto(server + "/uw/money")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.className") == "skip-link"
        assert page.locator(".skip-link").is_visible()
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.id") == "main"
        page.goto(server + "/uw/money")
        for _ in range(3):
            page.keyboard.press("Tab")
        focused = page.evaluate("(() => { const e = document.activeElement, s = getComputedStyle(e); return [e.tagName, s.outlineStyle, s.outlineWidth]; })()")
        assert focused[0] == "A" and focused[1] != "none" and focused[2] != "0px"   # visible focus ring
        btn = page.locator(".acct-btn")
        assert page.locator("#account-menu").is_hidden()
        btn.hover()
        assert page.locator("#account-menu").is_hidden()                          # not hover-only
        btn.click()
        assert page.locator("#account-menu").is_visible() and btn.get_attribute("aria-expanded") == "true"
        text = page.inner_text("#account-menu")
        assert "Test Underwriter Achieng" in text and "Partner insurer (to be named)" in text and "Sign out" in text
        page.keyboard.press("Escape")
        assert page.locator("#account-menu").is_hidden()
        assert page.evaluate("document.activeElement.classList.contains('acct-btn')")
        btn.click()
        page.mouse.click(700, 500)                                                # outside closes
        assert page.locator("#account-menu").is_hidden()
    finally:
        ctx.close()


@pytest.mark.parametrize("role", ["public", "officer", "underwriter"])
def test_mobile_sheet(browser, server, role):
    user, path, labels = ROLES[role]
    ctx, page = _page(browser, server, user, 375)
    try:
        page.goto(server + path)
        menu = page.locator(".menu-btn")
        assert menu.is_visible() and menu.get_attribute("aria-expanded") == "false"
        menu.click()
        sheet = page.locator("#sheet")
        assert sheet.is_visible() and menu.get_attribute("aria-expanded") == "true"
        assert sheet.bounding_box()["width"] == 375                               # full-width sheet
        sizes = page.evaluate("[...document.querySelectorAll('#sheet a, #sheet button')].filter(e => e.offsetParent).map(e => e.getBoundingClientRect().height)")
        assert sizes and min(sizes) >= 44                                         # large targets
        assert page.evaluate("[...document.querySelectorAll('#sheet nav a')].map(a => a.textContent.trim())") == labels
        assert page.evaluate("document.getElementById('sheet').contains(document.activeElement)")
        for _ in range(25):                                                       # focus stays trapped inside
            page.keyboard.press("Tab")
            assert page.evaluate("document.getElementById('sheet').contains(document.activeElement)")
        page.keyboard.press("Escape")
        assert sheet.is_hidden() and page.evaluate("document.activeElement.classList.contains('menu-btn')")
        menu.click()
        box = sheet.bounding_box()
        assert box["y"] + box["height"] < 760, box                                 # some page stays visible to tap
        page.mouse.click(10, box["y"] + box["height"] + 20)                        # outside tap on the backdrop
        assert sheet.is_hidden()
        menu.click()
        page.locator("#sheet nav a").nth(1).click()                               # navigation closes it
        page.wait_for_load_state("networkidle")
        assert page.locator("#sheet").is_hidden()
    finally:
        ctx.close()


def test_theme_toggle_follows_system_until_chosen(browser, server):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    page = ctx.new_page()
    try:
        page.goto(server + "/")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None   # follows the system
        assert page.evaluate("localStorage.getItem('agroshield-theme')") is None
        page.click("header.site [data-theme-toggle]")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
        page.goto(server + "/login")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"  # remembered
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert bg == "rgb(246, 243, 236)"
    finally:
        ctx.close()
