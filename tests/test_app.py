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


def test_app_tells_the_story_in_four_chapters(app):
    labels = [t.label for t in app.tabs]
    assert len(labels) == 4
    for number, name in enumerate(("The risk", "A farmer's quote", "Collecting the money", "Trust and the numbers"), 1):
        assert f"{number}. {name}" in labels[number - 1]
        assert f"Chapter {number}: {name}" in _text(app).replace("&#x27;", "'")
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
    app.sidebar.number_input(key="ceiling").set_value(18).run()  # Bureti (17.9%) is now under the ceiling
    assert not app.exception, app.exception
    assert "Premiums have changed" in _text(app)
    _button(app, "Run reconciliation").click().run()
    assert '<div class="label">Not offered</div><div class="value ">0<' in _text(app)


def test_quote_chapter(app):
    text = _text(app)
    assert "farm with 2 acres of maize and 2 dairy cows pays KSh 5,160 a season" in text  # Njoro, standard farm
    app.number_input(key="q_acres").set_value(5.0).run()
    app.checkbox(key="q_res_certified_seed").check().run()
    assert not app.exception, app.exception
    assert "5 acres of maize" in _text(app) and "Resilience discount, 5 points" in _text(app)
    app.selectbox(key="q_ward_njoro").select("bureti").run()
    assert not app.exception, app.exception
    assert "Bureti is not offered on the standard bundle" in _text(app)
    app.segmented_control(key="q_season").set_value("SR").run()
    assert not app.exception, app.exception


def test_green_vci_disables_verification(app):
    app.number_input(key="wa_vci").set_value(60.0).run()
    assert not app.exception, app.exception
    assert _button(app, "Simulate 12 photo replies").disabled


def test_every_number_can_be_typed(app):
    assert not app.sidebar.slider and not app.slider  # no slider left: every number is a box to type into
    app.sidebar.number_input(key="si").set_value(65_000).run()
    assert not app.exception, app.exception
    assert "KSh 65,000" in _text(app)


def test_a_payment_typed_by_hand(app):
    def check(ref, phone, name, amount):
        app.text_input(key="try_ref").set_value(ref)
        app.selectbox(key="try_phone").set_value(phone)
        app.text_input(key="try_name").set_value(name)
        app.number_input(key="try_amount").set_value(amount)
        _button(app, "Check this payment").click().run()
        assert not app.exception, app.exception
        return _text(app)

    assert "Credited to MBR-1042" in check("MBR-1042", "unknown", "", 3_600)
    assert "Credited to MBR-1042" in check("mbr 1O42", "MBR-1042", "", 3_600)
    assert "Sent to a person to review" in check("MBR-1043", "MBR-1042", "", 3_600)
    assert "Held in suspense" in check("SCHOOL FEES", "unknown", "Upendo Agrovet", 500)
    assert "Held: bad amount" in check("MBR-1042", "unknown", "", 0)


def test_how_it_works_is_there_for_newcomers(app):
    assert any("How ShambaShield360 works" in e.label for e in app.expander)
