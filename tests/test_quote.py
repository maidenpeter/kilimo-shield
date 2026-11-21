from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from engine import parametric_engine as pe
from engine import quote as qt

P = pe.TriggerParams()
WEATHER = {key: pe.load_weather(key)[0] for key in pe.WARDS}
ZONES = pe.zone_pricing(P).set_index("ward_key")


def make(ward="njoro", season="LR", acres=2.0, cows=2, practices=None, params=P, offered=True):
    return qt.quote(WEATHER[ward], params, ward_key=ward, season=season, acres=acres, cows=cows,
                    practices=practices, ward_offered=offered)


@pytest.mark.parametrize("ward", [k for k in pe.WARDS if ZONES.loc[k, "offered"] == "Yes"])
def test_standard_farm_matches_zone_pricing(ward):
    q = make(ward)
    assert q.sum_insured == 60_000
    assert q.cover == {"crop": 30_000, "fodder": 20_000, "vet": 10_000}
    assert q.premium_rate * 100 == pytest.approx(ZONES.loc[ward, "premium_rate_pct"])
    assert q.gross_premium == pytest.approx(ZONES.loc[ward, "premium_ksh"])
    assert q.seasonal_cap == pytest.approx(50_000)


def test_ward_not_offered_gets_no_quote():
    with pytest.raises(qt.QuoteError, match="not offered"):
        make("bureti", offered=False)


@pytest.mark.parametrize("acres,cows", [(0, 0), (0.25, 0), (21, 2), (2, 21), (-1, 2)])
def test_impossible_farms_are_refused(acres, cows):
    with pytest.raises(qt.QuoteError):
        make(acres=acres, cows=cows)


@pytest.mark.parametrize("acres,cows", [(0.5, 0), (1, 0), (0, 1), (3, 5), (20, 20), (7.5, 1)])
def test_money_adds_up(acres, cows):
    params = replace(P, subsidy_share=0.5, max_sellable_rate=0.25)  # crop-only farms price above 12%
    q = make(acres=acres, cows=cows, practices={"certified_seed": True, "sacco_good_standing": True}, params=params)
    assert q.sum_insured == acres * 15_000 + cows * 15_000
    assert q.gross_premium == qt.money(Decimal(repr(q.sum_insured)) * Decimal(repr(q.premium_rate)))
    assert q.government_share + q.farmer_share == q.gross_premium
    assert q.farmer_share - q.discount == q.farmer_pays
    # the insurer always receives the full gross premium
    assert q.farmer_pays + q.government_share + q.discount == q.gross_premium
    assert q.per_day_checkoff == (pytest.approx(q.farmer_pays / 90) if cows else None)
    # target pricing: the farm's own loss ratio never exceeds the target
    assert q.burn_cost_rate / q.premium_rate <= P.target_loss_ratio + 1e-9


def test_subsidy_only_inside_the_acre_band():
    with_subsidy = replace(P, subsidy_share=0.5)
    inside = make(acres=2, params=with_subsidy)
    assert inside.subsidy_eligible and inside.government_share == qt.money(inside.gross_premium * 0.5)
    dairy_only = make(acres=0, cows=3, params=replace(with_subsidy, max_sellable_rate=0.25))
    assert not dairy_only.subsidy_eligible and dairy_only.government_share == 0
    assert make(acres=2).government_share == 0  # default: no subsidy agreed


def test_resilience_points_cap_and_groups():
    points, counted = qt.resilience({"irrigation_full": True, "irrigation_partial": True})
    assert points == 3 and len(counted) == 1  # only the better irrigation item counts
    everything = {item.id: True for item in qt.RESILIENCE_ITEMS}
    points, _ = qt.resilience(everything)
    assert points == 5 + 4 + 3 + 3 + 2
    q = make(practices=everything)
    assert q.discount_rate == qt.DISCOUNT_CAP  # 17 points, capped at 15%
    assert q.discount == qt.money(Decimal(q.farmer_share) * Decimal("0.15"))
    assert q.discount_exceeds_fee  # 15% of the farmer's share is more than the 10% platform fee
    with pytest.raises(qt.QuoteError):
        qt.resilience({"bribe": True})


def test_discount_never_touches_the_risk_price():
    plain = make()
    discounted = make(practices={"certified_seed": True})
    assert discounted.gross_premium == plain.gross_premium
    assert discounted.premium_rate == plain.premium_rate
    assert discounted.farmer_pays < plain.farmer_pays


def test_dates_follow_the_14_day_rule():
    lr = make(season="LR")
    assert (lr.enrolment_closes, lr.cover_starts) == (date(2027, 2, 15), date(2027, 3, 1))
    sr = make(season="SR")
    assert (sr.enrolment_closes, sr.cover_starts) == (date(2027, 9, 17), date(2027, 10, 1))


def test_history_matches_the_backtest():
    q = make(season="SR")
    seasons = pe.run_backtest(WEATHER["njoro"], qt.farm_params(P, 2, 2))
    sr = seasons[seasons["season"] == "SR"].reset_index(drop=True)
    assert list(q.history["payout_total"]) == pytest.approx(list(sr["payout_total"]))
    assert len(q.history) == 10


def test_quote_id_is_stable_and_specific():
    assert make().quote_id == make().quote_id
    assert make().quote_id != make(acres=3).quote_id
    assert make().quote_id.startswith("SS360-Q-")


def test_money_rounds_half_up_exactly():
    q = make(acres=0.5, cows=0, params=replace(P, max_sellable_rate=0.25))  # 7,500 x 11.5% = 862.5
    assert q.sum_insured == 7_500 and q.premium_rate == pytest.approx(0.115)
    assert q.gross_premium == 863
    assert qt.money(2.5) == 3 and qt.money(Decimal("3937.5")) == 3938


def test_cover_scales_with_the_product_sum_insured():
    bigger = replace(P, sum_insured=100_000, aggregate_cap_share=83_000 / 100_000)
    q = make(params=bigger)
    zone = pe.zone_pricing(bigger).set_index("ward_key").loc["njoro"]
    assert q.sum_insured == 100_000 and q.seasonal_cap == pytest.approx(83_000)
    assert q.gross_premium == pytest.approx(zone["premium_ksh"])
    assert q.unit_cover["crop"] == pytest.approx(25_000)


def test_a_farm_above_the_ceiling_gets_no_quote():
    with pytest.raises(qt.FarmAboveCeiling) as err:
        make("kimilili", acres=0, cows=5)
    assert err.value.rate > P.max_sellable_rate


def test_invalid_inputs_are_named():
    for acres, cows in ((0, 0), (2, 1.5), (2, True)):
        with pytest.raises(qt.FarmNotValid):
            make(acres=acres, cows=cows)
    with pytest.raises(qt.WardNotOffered):
        make("bureti", offered=False)


def test_no_milk_cheque_without_cows():
    q = make(acres=3, cows=0, params=replace(P, max_sellable_rate=0.25))
    assert q.per_day_checkoff is None
    assert "milk check-off" not in qt.quote_text(q)
    assert "Farm: 3 acres of maize and no dairy cows" in qt.quote_text(q)
    assert "Farm: 1 acre of maize and 1 dairy cow" in qt.quote_text(make(acres=1, cows=1))


def test_quote_id_follows_the_quote_not_unrelated_settings():
    base = make()
    assert make(params=replace(P, verifier_accuracy=0.5)).quote_id == base.quote_id
    assert make(practices={item.id: False for item in qt.RESILIENCE_ITEMS}).quote_id == base.quote_id
    assert make(acres=2).quote_id == make(acres=2.0).quote_id
    assert make(practices={"certified_seed": True}).quote_id != base.quote_id


def test_quote_text():
    text = qt.quote_text(make(practices={"certified_seed": True}))
    assert "ILLUSTRATIVE" in text and "Partner insurer (to be named)" in text
    assert "15 February 2027" in text and "Farmer pays" in text
    assert "—" not in text


def test_exact_cover_at_any_sum_insured():
    params = replace(P, sum_insured=25_000, aggregate_cap_share=21_000 / 25_000, max_sellable_rate=0.3)
    q = make(acres=0.5, cows=2, params=params)            # 3,125 + 12,500 = 15,625 at 6.8%: 1,062.5
    assert q.sum_insured == 15_625 and q.premium_rate == pytest.approx(0.068)
    assert q.gross_premium == 1_063
    small = make(acres=0.25, cows=1, params=params)
    assert small.sum_insured == 7_812.5 and small.seasonal_cap == 6_562.5
    assert "Sum insured   KSh     7,813" in qt.quote_text(small)


def test_quote_ids_are_long_and_include_the_fee():
    q = make(practices={item.id: True for item in qt.RESILIENCE_ITEMS})
    assert len(q.quote_id) == len("SS360-Q-") + 12
    assert make(practices={item.id: True for item in qt.RESILIENCE_ITEMS},
                params=replace(P, platform_fee_rate=0.2)).quote_id != q.quote_id


@pytest.mark.parametrize("sum_insured", [20_000.0, 25_000.0, 45_000.0, 60_000.0, 150_000.0])
@pytest.mark.parametrize("subsidy", [0.1, 0.25, 0.5, 0.7])
def test_chapter_one_farmer_share_matches_the_quote(sum_insured, subsidy):
    params = pe.TriggerParams(sum_insured=sum_insured, target_loss_ratio=0.5, subsidy_share=subsidy)
    weather = pe.load_weather("njoro")[0]
    k = pe.kpis(pe.run_backtest(weather, params), params)
    q = qt.quote(weather, params, ward_key="njoro", season="LR", acres=2, cows=2)
    assert k.premium_ksh == q.gross_premium
    assert k.farmer_premium_ksh == q.gross_premium - q.government_share


def test_minimum_applies_only_when_it_sets_the_price():
    params = pe.TriggerParams(target_loss_ratio=0.6)
    assert pe.commercial_rate(0.00556, params) == 0.01 and not pe.minimum_applies(0.00556, params)  # rounds up to 1%
    assert pe.commercial_rate(0.003, params) == 0.01 and pe.minimum_applies(0.003, params)
    assert pe.minimum_applies(0.0, params)
    assert not pe.minimum_applies(0.0, pe.TriggerParams(pricing_mode="flat"))


def test_rates_read_half_up():
    assert [qt.rate_text(r) for r in (0.0625, 0.0635, 0.086, 0.179)] == ["6.3%", "6.4%", "8.6%", "17.9%"]


def test_who_else_pays_never_states_the_subsidy_as_fact():
    from ui.tab_quote import who_else_pays
    weather = pe.load_weather("njoro")[0]
    subsidised = qt.quote(weather, pe.TriggerParams(subsidy_share=0.5), ward_key="njoro", season="LR", acres=2, cows=2)
    assert "illustrative subsidy: none is agreed" in who_else_pays(subsidised)
    tiny = qt.quote(weather, pe.TriggerParams(sum_insured=20_000.0, subsidy_share=0.01, sm_trigger=15.0,
                                              heat_temp_c=36.0, rain10_mode="fixed", rain10_trigger_mm=300.0),
                    ward_key="njoro", season="LR", acres=0.5, cows=0)
    if tiny.government_share == 0 and not tiny.discount:
        assert "less than half a shilling" in who_else_pays(tiny)


def test_cap_is_never_cut_short():
    assert pe.whole_shillings(pe.TriggerParams(sum_insured=45_000.0, aggregate_cap_share=13_000 / 45_000)
                              .aggregate_cap) == 13_000


def test_a_quotation_made_out_to_a_farm():
    from ui.quote_doc import quotation_html
    q = make()
    who = {"farmer": "Grace Wanjiku", "farm": "Kiprono Dairy", "member": "MBR-1042", "phone": "0712 345 678",
           "village": "Mau Narok"}
    assert qt.quotation_number(q) == q.quote_id
    number = qt.quotation_number(q, who)
    assert number.startswith(q.quote_id + "-") and number == qt.quotation_number(q, dict(who))
    assert number != qt.quotation_number(q, {**who, "farm": "Another Farm"})
    text = qt.quote_text(q, who)
    assert number in text and "Grace Wanjiku" in text and "Kiprono Dairy" in text and "MBR-1042" in text
    page = quotation_html(q, {**who, "farm": "<b>Shamba</b>"}, issued=date(2026, 2, 1))
    assert "&lt;b&gt;Shamba&lt;/b&gt;" in page and "<b>Shamba</b>" not in page
    assert "1 February 2026" in page and pe.WARDS["njoro"].label in page
    assert "price check" in quotation_html(q)
    assert "—" not in page
