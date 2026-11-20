"""Run the whole Streamlit app headless and press every button."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def _button(at, label_start):
    return next(b for b in at.button if b.label.startswith(label_start))


def test_app_renders_all_three_tabs(app):
    assert len(app.tabs) == 3
    labels = [t.label for t in app.tabs]
    assert labels[0].startswith("Reinsurer") and labels[1].startswith("SACCO") and labels[2].startswith("WhatsApp")
    text = " ".join(m.value for m in app.markdown)
    assert "Partner insurer (to be named)" in text
    assert "10-year average burn cost" in text
    assert not any("—" in m.value for m in app.markdown)  # plain punctuation in user-facing copy


def test_reconciliation_and_claim_split_buttons(app):
    _button(app, "Run automated reconciliation").click().run()
    assert not app.exception, app.exception
    assert any("Reconciled 520 M-Pesa rows" in s.value for s in app.success)
    _button(app, "Simulate drought payout").click().run()
    assert not app.exception, app.exception
    assert "To SACCO loan accounts" in " ".join(m.value for m in app.markdown)


def test_whatsapp_simulation_unlocks_the_ward(app):
    _button(app, "Simulate 12 farmer geotagged submissions").click().run()
    assert not app.exception, app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "Verification consensus" in text
    assert "RED (PAYOUT UNLOCKED)" in text or "HOLD RELEASED" in text


def test_every_ward_and_season_filter_renders(app):
    for ward in ("imenti_north", "kangundo", "kimilili", "bureti"):
        app.sidebar.selectbox[0].select(ward).run()
        assert not app.exception, (ward, app.exception)
    app.radio[0].set_value("Short rains (OND)").run()
    assert not app.exception, app.exception


def test_pricing_and_rain_switches(app):
    text = " ".join(m.value for m in app.markdown)
    assert "Commercial premium" in text and "Zone pricing across the pilot wards" in text
    app.sidebar.radio(key="pricing_mode").set_value("One flat rate for every ward").run()
    assert not app.exception, app.exception
    app.sidebar.radio(key="rain_mode").set_value("Fixed mm for every ward").run()
    assert not app.exception, app.exception
    app.sidebar.selectbox[0].select("bureti").run()
    assert not app.exception, app.exception


def test_green_vci_disables_verification(app):
    app.slider(key="wa_vci").set_value(60.0).run()
    assert not app.exception, app.exception
    assert _button(app, "Simulate 12 farmer geotagged submissions").disabled
