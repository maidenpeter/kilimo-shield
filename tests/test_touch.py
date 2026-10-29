"""Touch behaviour in a real browser engine (Chrome, Android Pixel 5 emulation, touch taps).

Guards against the "first tap does nothing" reports: nothing may cover a submit button,
one tap must submit (including acres typed as 2.25 or with a decimal comma), a second
quick tap must not submit twice, and tap targets are at least 44 px. Skipped when
Playwright or Chrome is not installed.
"""
import socket
import threading
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from agroshield_platform.crypto import hash_password  # noqa: E402
from agroshield_platform.db import transaction  # noqa: E402
from agroshield_platform.models import Officer, Sacco  # noqa: E402
from agroshield_platform.web.app import create_app  # noqa: E402

from test_platform import PASSWORD, TODAY, book, settings  # noqa: E402,F401

UNDER = """(sel) => { const b = document.querySelector(sel); const r = b.getBoundingClientRect();
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {h: r.height, covered: !(el === b || b.contains(el))}; }"""
SMALL = """() => [...document.querySelectorAll('header a, header summary, header button, main a.btn, main button, main summary, .choice label')]
  .filter(e => e.offsetParent !== null).map(e => [e.tagName + ' ' + (e.textContent || '').trim().slice(0, 20),
  Math.round(e.getBoundingClientRect().height)]).filter(x => x[1] < 44)"""


@pytest.fixture
def server(settings, book):
    import uvicorn
    app = create_app(settings, book, today=TODAY)
    with transaction(app.state.factory) as s:
        sacco = Sacco(code="TCH01", name="Touch SACCO", is_demo=True)
        s.add(sacco)
        s.flush()
        s.add(Officer(sacco_id=sacco.id, username="officer", display_name="Officer", role="officer",
                      password_hash=hash_password(PASSWORD)))
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


@pytest.fixture
def phone():
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")
        except Exception as e:                     # no Chrome on this machine
            pytest.skip(f"Chrome not available: {e}")
        ctx = browser.new_context(**p.devices["Pixel 5"])
        yield ctx.new_page()
        browser.close()


def test_one_tap_signs_in_and_prices(server, phone):
    page = phone
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(server + "/login")
    page.fill("#username", "officer")
    page.fill("#password", PASSWORD)
    assert page.evaluate(UNDER, "form.stack button[type=submit]") == {"h": pytest.approx(46.8, abs=4), "covered": False}
    page.tap("form.stack button[type=submit]")
    page.wait_for_url("**/dashboard", timeout=5000)
    assert page.evaluate(SMALL) == []
    for acres, lead in (("2.25", "for 2.25 acres"), ("2,5", "for 2.5 acres")):
        page.goto(server + "/quote")
        page.fill("#acreage", acres)
        assert page.evaluate(UNDER, "form.stack button[type=submit]")["covered"] is False
        page.tap("form.stack button[type=submit]")
        page.wait_for_selector(".price-answer", timeout=5000)
        assert lead in page.inner_text(".price-answer .lead")
    assert page.evaluate(SMALL) == []
    page.tap(".menu-btn")                              # the Menu sheet closes on a tap outside it
    assert page.is_visible("#sheet")
    box = page.locator("#sheet").bounding_box()
    page.touchscreen.tap(196, min(720, box["y"] + box["height"] + 40))   # on the backdrop, below the sheet
    assert page.is_hidden("#sheet")
    assert page.evaluate("document.activeElement.classList.contains('menu-btn')")   # focus returns to Menu
    page.locator("form.stack button[type=submit]").scroll_into_view_if_needed()
    assert page.evaluate(UNDER, "form.stack button[type=submit]")["covered"] is False


def test_a_quick_second_tap_does_not_submit_twice(server, phone):
    page = phone
    page.goto(server + "/login")
    page.fill("#username", "officer")
    page.fill("#password", PASSWORD)
    page.tap("form.stack button[type=submit]")
    page.wait_for_url("**/dashboard")
    page.goto(server + "/quote")
    page.fill("#acreage", "2")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.evaluate("""() => { const b = document.querySelector('form.stack button[type=submit]');
                             b.click(); b.click(); }""")
    page.wait_for_selector(".price-answer", timeout=5000)
    assert len([u for u in posts if u.endswith("/quote")]) == 1
