import json

import pytest
from fastapi.testclient import TestClient

from agroshield_pricing.api import create_app
from agroshield_pricing.pet import make_pet_source
from agroshield_pricing.quote import QuoteError, RateBook, WardRates, quote, resilience_points
from agroshield_pricing.rainfall import make_source


@pytest.fixture
def book(cfg):
    """A fixed rate book, so the split and discount maths can be checked by hand."""
    return RateBook(
        rates={
            ("ward-a", "LR"): WardRates("ward-a", "Ward A", "LR", {5000.0: 1000.0, 10000.0: 2000.0, 15000.0: 3000.0},
                                        1000.0, 2000.0, {"layer_b": "B-test", "layer_a": "A-test"}, ["ILLUSTRATIVE"]),
            ("ward-b", "LR"): WardRates("ward-b", "Ward B", "LR", {5000.0: 500.0, 10000.0: 800.0, 15000.0: 900.0},
                                        None, None, {"layer_b": "B-test"}, ["ILLUSTRATIVE"]),
        },
        config_sha256=cfg.file_hashes, built_at="test")


@pytest.fixture
def cfg_a_on(cfg):
    """Layer A switched back on, to keep its (dormant) quote path tested."""
    c = cfg.model_copy(deep=True)
    c.product.layer_a.enabled = True
    return c


# ------------------------------------------------------------------ subsidy split
def test_subsidy_split_inside_the_acre_band(cfg, book):
    q = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"])
    assert q["gross_premium_kes"] == 4000.0
    assert q["subsidy"]["eligible"] and q["subsidy"]["government_share_kes"] == 2000.0
    assert q["farmer_share_before_discount_kes"] == 2000.0 == q["farmer_pays_kes"]
    assert q["subsidy"]["status"] == "not yet received"


@pytest.mark.parametrize("acres, eligible", [(0.4, False), (0.5, True), (20, True), (20.5, False)])
def test_subsidy_eligibility_band(cfg, book, acres, eligible):
    q = quote(cfg, book, ward_id="ward-a", acres=acres, layers=["B"])
    assert q["subsidy"]["eligible"] is eligible
    expected_gov = q["gross_premium_kes"] * 0.5 if eligible else 0.0
    assert q["subsidy"]["government_share_kes"] == pytest.approx(expected_gov)
    assert q["subsidy"]["status"] == ("not yet received" if eligible else "not applicable")


def test_shares_always_add_up(cfg_a_on, book):
    q = quote(cfg_a_on, book, ward_id="ward-a", acres=3.7, layers=["A", "B"], sum_insured_kes_per_acre=15000,
              resilience={"certified_seed_verified": True, "photos_on_schedule": True})
    assert q["subsidy"]["government_share_kes"] + q["farmer_share_before_discount_kes"] == pytest.approx(q["gross_premium_kes"])
    assert q["farmer_pays_kes"] + q["resilience"]["discount_kes"] == pytest.approx(q["farmer_share_before_discount_kes"])


# ------------------------------------------------------------------ Resilience discount
def test_discount_applies_to_farmer_share_only(cfg, book):
    plain = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"])
    disc = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"], resilience={"certified_seed_verified": True})
    assert disc["gross_premium_kes"] == plain["gross_premium_kes"]                 # risk price unchanged
    assert disc["subsidy"]["government_share_kes"] == plain["subsidy"]["government_share_kes"]
    assert disc["resilience"]["discount_rate"] == pytest.approx(0.05)
    assert disc["farmer_pays_kes"] == pytest.approx(2000.0 * 0.95)


def test_discount_is_capped(cfg, book):
    every = {p.id: True for p in cfg.product.resilience.points}
    q = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"], resilience=every)
    assert q["resilience"]["discount_rate"] == cfg.product.resilience.discount_cap == 0.15
    assert q["resilience"]["capped"] is True
    assert q["farmer_pays_kes"] == pytest.approx(2000.0 * 0.85)


def test_only_one_irrigation_item_counts(cfg):
    pts, counted = resilience_points(cfg, {"irrigation_full": True, "irrigation_partial": True})
    assert pts == 3 and [c["id"] for c in counted] == ["irrigation_full"]


def test_unknown_resilience_item_is_rejected(cfg, book):
    with pytest.raises(QuoteError, match="unknown Resilience"):
        quote(cfg, book, ward_id="ward-a", acres=1, layers=["B"], resilience={"owns_tractor": True})


# ------------------------------------------------------------------ product rules
def test_layer_a_not_offered_at_ward_b(cfg_a_on, book):
    with pytest.raises(QuoteError, match="not offered"):
        quote(cfg_a_on, book, ward_id="ward-b", acres=1, layers=["A"])


def test_layer_a_dropped_from_the_product(cfg, book):
    assert cfg.product.layer_a.enabled is False
    with pytest.raises(QuoteError, match="not part of the product"):
        quote(cfg, book, ward_id="ward-a", acres=1, layers=["A", "B"])


def test_insurer_receives_full_gross_and_funder_is_shown(cfg, book):
    q = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"],
              resilience={"certified_seed_verified": True, "sacco_good_standing": True})
    fl = q["premium_flows"]
    assert fl["insurer_receives_kes"] == q["gross_premium_kes"]
    assert fl["government_kes"] + fl["farmer_kes"] + fl["discount_funder_kes"] == pytest.approx(q["gross_premium_kes"])
    assert q["resilience"]["funder"] == fl["discount_funder"] == cfg.product.resilience.funder == "platform"
    assert fl["platform_fee_kes"] == pytest.approx(q["gross_premium_kes"] * 0.06)
    assert "does not reduce the parametric risk" in q["resilience"]["note"]


def test_sum_insured_must_be_an_option(cfg, book):
    with pytest.raises(QuoteError, match="sum insured"):
        quote(cfg, book, ward_id="ward-a", acres=1, layers=["B"], sum_insured_kes_per_acre=12000)


# ------------------------------------------------------------------ API
def test_api_quote_products_and_audit(cfg, book, tmp_path):
    audit = tmp_path / "quotes.jsonl"
    client = TestClient(create_app(cfg.root, book=book, audit_path=audit))
    assert client.get("/health").json()["ok"] is True
    prods = client.get("/v1/products").json()
    assert {w["ward_id"]: w["layers"] for w in prods["wards"]} == {"ward-a": ["B"], "ward-b": ["B"]}
    assert prods["layer_a"]["enabled"] is False
    r = client.post("/v1/quotes", json={"ward_id": "ward-a", "acres": 2, "layers": ["B"],
                                        "resilience": {"certified_seed_verified": True}})
    assert r.status_code == 200
    body = r.json()
    assert body["gross_premium_kes"] == 4000.0 and body["farmer_pays_kes"] == pytest.approx(2000.0 * 0.95)
    line = json.loads(audit.read_text().strip().splitlines()[-1])
    assert line["quote_id"] == body["quote_id"] and line["request"]["ward_id"] == "ward-a"
    bad = client.post("/v1/quotes", json={"ward_id": "ward-b", "acres": 1, "layers": ["A"]})
    assert bad.status_code == 422 and "not part of the product" in bad.json()["detail"]


def test_api_takes_quote_inputs_in_the_body_not_the_url(cfg, book, tmp_path):
    client = TestClient(create_app(cfg.root, book=book, audit_path=tmp_path / "q.jsonl"))
    assert client.get("/v1/quotes", params={"ward_id": "ward-a", "acres": 2}).status_code == 405


# ------------------------------------------------------------------ named acceptance scenario
def test_acceptance_scenario_wanjiku_kamau(cfg, tmp_path):
    """Regression pin from the real engine (borrowed idea #7, docs/BORROWED_FROM_MVP.md).

    Wanjiku Kamau (fictional), Ward A, long rains, 2 acres, KES 10,000 sum insured per
    acre, Layer B only, certified seed verified and SACCO member in good standing
    (7 points). Recorded from the engine on 2026-10-28: farmer pays KES 1,752.17.
    Re-recorded 2026-11-01 for B-1.2.1 (Ward A soil 130 mm from SoilGrids instead of the
    100 mm placeholder, gross rate 18.84% -> 16.70%): farmer pays KES 1,552.66.
    The band is +/-2%. If it moves, a term or an input changed; review the change and
    re-record the value deliberately. Never tune rates to land in this band.
    """
    book = RateBook.build(cfg, make_source(cfg, allow_download=False), make_pet_source(cfg, allow_download=False))
    q = quote(cfg, book, ward_id="ward-a", acres=2, layers=["B"], sum_insured_kes_per_acre=10000,
              resilience={"certified_seed_verified": True, "sacco_good_standing": True})
    assert q["subsidy"]["eligible"] and q["resilience"]["points"] == 7
    assert 1521.6 <= q["farmer_pays_kes"] <= 1583.7
