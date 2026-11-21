"""Run the whole Streamlit app headless and press every button."""
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui import brand

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def _button(at, label_start):
    return next(b for b in at.button if b.label.startswith(label_start))


def _text(at):
    return " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)


def test_identity_is_consistent():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == brand.APP_ID == "shambashield360"
    assert project["version"] == brand.APP_VERSION
    assert brand.LOGO_SVG.exists() and brand.LOGO_PNG.exists()
    assert brand.logo_data_uri().startswith("data:image/svg+xml;base64,")


def test_app_renders_all_three_tabs(app):
    labels = [t.label for t in app.tabs]
    assert len(labels) == 3
    assert "Reinsurer backtest" in labels[0] and "SACCO reconciliation" in labels[1] and "Trust loop" in labels[2]
    text = _text(app)
    assert f'content: "{brand.APP_NAME}"' in text  # the name is drawn into the navbar
    assert brand.identifier() in text
    assert "Partner insurer (to be named)" in text
    assert "Burn cost" in text and "Basis-risk score" in text
    assert "—" not in text  # plain punctuation in user-facing copy


def test_reconciliation_and_claim_split_buttons(app):
    _button(app, "Run reconciliation").click().run()
    assert not app.exception, app.exception
    assert "Reconciled 520 M-Pesa rows" in _text(app)
    _button(app, "Simulate payout").click().run()
    assert not app.exception, app.exception
    assert "To SACCO loans" in _text(app)


def test_whatsapp_simulation_unlocks_the_ward(app):
    _button(app, "Simulate 12 photo replies").click().run()
    assert not app.exception, app.exception
    text = _text(app)
    assert "Needed to unlock" in text
    assert "RED (PAYOUT UNLOCKED)" in text or "HOLD RELEASED" in text


def test_every_ward_and_season_filter_renders(app):
    for ward in ("imenti_north", "kangundo", "kimilili", "bureti"):
        app.sidebar.selectbox(key="ward").select(ward).run()
        assert not app.exception, (ward, app.exception)
    app.segmented_control(key="season_filter").set_value("Short rains").run()
    assert not app.exception, app.exception


def test_pricing_and_rain_switches(app):
    assert "Zone pricing across the pilot wards" in _text(app)
    app.sidebar.radio(key="pricing_mode").set_value("One flat rate for every ward").run()
    assert not app.exception, app.exception
    app.sidebar.radio(key="rain_mode").set_value("Fixed mm for every ward").run()
    assert not app.exception, app.exception
    app.sidebar.selectbox(key="ward").select("bureti").run()
    assert not app.exception, app.exception


def test_ceiling_change_asks_for_a_fresh_reconciliation(app):
    _button(app, "Run reconciliation").click().run()
    assert '<div class="label">Not offered</div><div class="value ">77<' in _text(app)  # Bureti members
    app.sidebar.slider(key="ceiling").set_value(18).run()  # Bureti (17.9%) is now under the ceiling
    assert not app.exception, app.exception
    assert "Premiums have changed" in _text(app)
    _button(app, "Run reconciliation").click().run()
    assert '<div class="label">Not offered</div><div class="value ">0<' in _text(app)


def test_green_vci_disables_verification(app):
    app.slider(key="wa_vci").set_value(60.0).run()
    assert not app.exception, app.exception
    assert _button(app, "Simulate 12 photo replies").disabled
