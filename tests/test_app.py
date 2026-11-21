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
    assert "Pricing sheet: every pilot ward" in _text(app)
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
        app.run()
        assert not app.exception, app.exception
        return _text(app)

    assert "Credited to MBR-1042" in check("MBR-1042", "unknown", "", 3_600)
    assert "Credited to MBR-1042" in check("mbr 1O42", "MBR-1042", "", 3_600)
    assert "Sent to a person to review" in check("MBR-1043", "MBR-1042", "", 3_600)
    assert "Held in suspense" in check("SCHOOL FEES", "unknown", "Upendo Agrovet", 500)
    assert "Held: bad amount" in check("MBR-1042", "unknown", "", 0)


def test_how_it_works_is_there_for_newcomers(app):
    assert any("How ShambaShield360 works" in e.label for e in app.expander)


def test_typed_numbers_are_used_as_shown_and_kept_in_range(app):
    app.sidebar.radio(key="pricing_mode").set_value("One flat rate for every ward").run()
    app.sidebar.number_input(key="num-premium-rate-for-every-ward").set_value(6.35).run()
    assert not app.exception, app.exception
    assert app.sidebar.number_input(key="num-premium-rate-for-every-ward").value == 6.4
    text = _text(app)
    assert "At the flat 6.4% rate it costs KSh 3,840" in text and "6.35" not in text
    app.sidebar.number_input(key="si").set_value(200_000).run()
    assert app.sidebar.number_input(key="si").value == 150_000
    assert "KSh 200,000 is outside the allowed range, so KSh 150,000 is used." in _text(app)


def test_name_only_payments_get_a_true_reason(app):
    app.text_input(key="try_ref").set_value("")
    app.selectbox(key="try_phone").set_value("unknown")
    app.text_input(key="try_name").set_value("Gitonga Njagi")
    app.run()
    text = _text(app)
    assert "Two names alone are too common" in text


def test_loan_share_follows_chapter_three_at_once(app):
    _button(app, "Run reconciliation").click().run()
    app.number_input(key="split_share").set_value(55).run()
    assert not app.exception, app.exception
    assert "Up to 45%" in _text(app)


def test_tryout_amount_out_of_range_is_noted(app):
    app.text_input(key="try_ref").set_value("MBR-1042")
    app.selectbox(key="try_phone").set_value("unknown")
    app.text_input(key="try_name").set_value("")
    app.number_input(key="try_amount").set_value(600_000)
    app.run()
    text = _text(app)
    assert "KSh 600,000 is outside the allowed range, so KSh 500,000 is used." in text
    assert "Paid in</span><span class=\"amt \">KSh 500,000" in text  # the breakdown uses the amount checked


def test_one_name_is_not_called_nothing(app):
    app.text_input(key="try_ref").set_value("")
    app.selectbox(key="try_phone").set_value("unknown")
    app.text_input(key="try_name").set_value("Gitonga")
    app.run()
    assert "is not enough to pick out one" in _text(app)


def test_quote_shows_what_each_setting_changes_live(app):
    from engine import parametric_engine as pe
    from engine import quote as qt
    weather = pe.load_weather("njoro")[0]
    params = pe.TriggerParams()
    base = qt.quote(weather, params, ward_key="njoro", season="LR", acres=2, cows=2)
    more = qt.quote(weather, params, ward_key="njoro", season="LR", acres=3, cows=2)
    text = _text(app)
    assert "What changes the price" in text
    assert f"One more acre: +{theme_ksh(more.farmer_pays - base.farmer_pays)} a season." in text
    app.number_input(key="q_acres").set_value(5.0).run()
    assert not app.exception, app.exception
    five = qt.quote(weather, params, ward_key="njoro", season="LR", acres=5, cows=2)
    diff = five.farmer_pays - base.farmer_pays
    text = _text(app)
    assert "Last change: acres 2 to 5." in text
    assert (f'<span class="up">Farmer pays {theme_ksh(base.farmer_pays)} → {theme_ksh(five.farmer_pays)} '
            f'(+{theme_ksh(diff)}).</span>' in text)  # a rise is red
    app.checkbox(key="q_res_certified_seed").check().run()
    text = _text(app)
    assert "Last change: ticked bought certified maize seed" in text and 'class="down"' in text


def theme_ksh(value):
    from ui import theme
    return theme.ksh(value)


def test_warnings_are_red(app):
    app.selectbox(key="q_ward_njoro").select("bureti").run()
    assert 'class="ss-warn"' in _text(app)  # why Bureti has no quote


def test_every_map_measure_renders(app):
    from ui.risk_map import VIEWS, VIEW_HELP
    for view in VIEWS:
        app.selectbox(key="map_measure").set_value(view).run()
        assert not app.exception, (view, app.exception)
        assert VIEW_HELP[view] in _text(app)
    assert "Underwriting profile: Njoro Ward, Nakuru County" in _text(app)


def test_payment_breakdown_splits_every_shilling(app):
    from engine import recon_engine as rec
    app.text_input(key="try_ref").set_value("MBR-1042")
    app.selectbox(key="try_phone").set_value("unknown")
    app.text_input(key="try_name").set_value("")
    app.number_input(key="try_amount").set_value(9_000).run()
    assert not app.exception, app.exception
    text = _text(app)
    assert "Credited to MBR-1042" in text and "Every shilling placed" in text and "KSh 9,000" in text
    assert "Where this payment goes" in text
    _button(app, "Run reconciliation").click().run()
    assert "One member's money" in _text(app)
    app.text_input(key="try_ref").set_value("MBR-1202").run()  # a Njoro member: the ward is offered
    assert "after the payments already on this statement" in _text(app)
    app.text_input(key="try_ref").set_value("MBR-1042").run()  # Bureti is not offered at the 12% ceiling
    assert "ward not offered: none due" in _text(app)
