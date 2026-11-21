import numpy as np
import pytest

from data.seed_generator import generate_members
from engine import parametric_engine as pe
from engine import underwriting as uw
from ui import risk_map
from ui.tab_parametric import pricing_sheet


@pytest.fixture(scope="module")
def backtests():
    params = pe.TriggerParams()
    return params, {key: pe.run_backtest(pe.load_weather(key)[0], params) for key in pe.WARDS}


def test_ward_risk_matches_a_hand_calculation(backtests):
    params, bt = backtests
    for key, seasons in bt.items():
        share = 100 * seasons["payout_total"].to_numpy() / params.sum_insured
        r = uw.ward_risk(seasons, params.sum_insured)
        paid = share > 0
        assert r.seasons == 20 and r.paid == paid.sum()
        assert r.frequency_pct == pytest.approx(100 * paid.mean())
        assert r.burn_pct == pytest.approx(pe.kpis(seasons, params).burn_cost_pct)
        assert r.severity_pct == pytest.approx(share[paid].mean())
        assert r.p90_pct == pytest.approx(np.quantile(share, 0.9))
        assert r.worst_pct == pytest.approx(share.max())
        assert r.volatility == pytest.approx(share.std(ddof=1) / share.mean())
        rain = seasons["rain_mm"].to_numpy()
        assert r.rain_cv == pytest.approx(rain.std(ddof=1) / rain.mean())
        # burn cost is frequency times severity
        assert r.burn_pct == pytest.approx(r.frequency_pct / 100 * r.severity_pct)


def test_pay_together_and_the_book(backtests):
    params, bt = backtests
    pairs = uw.pay_together(bt, ("LR", "SR"))
    assert len(pairs) == 10
    for p in pairs:
        x = bt[p.a].set_index("label")["payout_total"]
        y = bt[p.b].set_index("label")["payout_total"]
        assert p.correlation == pytest.approx(np.corrcoef(x, y)[0, 1])
        assert p.both_paid == int(((x > 0) & (y > 0)).sum())
    members = generate_members()["ward"].value_counts().to_dict()
    load = uw.season_load(bt, ("LR", "SR"), members)
    total = sum(bt[k]["payout_total"].sum() * members[k] for k in bt)
    assert load.sum() == pytest.approx(total)


def test_accumulation_lines_only_for_wards_that_pay_together(backtests):
    params, bt = backtests
    zones = pe.zone_pricing(params)
    members = generate_members()["ward"].value_counts().to_dict()
    figures = risk_map.ward_figures(zones, bt, ("LR", "SR"), params, members)
    together = uw.pay_together(bt, ("LR", "SR"))
    fig = risk_map.static_map("Accumulation", figures, params, "njoro", "seasons", together)
    lines = [tr for tr in fig.data if tr.mode == "lines" and tr.line.dash == "dot" and tr.hovertemplate]
    assert len(lines) == sum(p.correlation is not None and p.correlation >= risk_map.TOGETHER for p in together)
    assert len(lines) == 2  # Kimilili-Bureti (0.49) and Njoro-Bureti (0.37)
    sold = {w.key for w in figures if w.offered}
    book = {k: n for k, n in members.items() if k in sold}
    text = risk_map.story("Accumulation", figures, params, "seasons", together, uw.season_load(bt, ("LR", "SR"), book))
    assert "Short rains 2016" in text  # the worst season of the book as sold (Bureti, not sold, is left out)
    assert "Bureti is not sold, so left out" in text
    assert "Selling Bureti would add accumulation: it pays together with Kimilili" in text
    assert risk_map.measure("Accumulation", next(w for w in figures if w.key == "bureti"), params, 1.0)[1] == "not sold"


def test_pricing_sheet_agrees_with_the_zone_table(backtests):
    params, bt = backtests
    zones = pe.zone_pricing(params)
    members = generate_members()["ward"].value_counts().to_dict()
    sheet = pricing_sheet(zones, bt, params, members).set_index("ward")
    for _, z in zones.iterrows():
        row = sheet.loc[z["ward"]]
        assert row["premium_rate_pct"] == z["premium_rate_pct"] and row["burn_cost_pct"] == z["burn_cost_pct"]
        assert row["headroom_pts"] == pytest.approx(12 - z["premium_rate_pct"])
        assert row["expected_payouts_ksh"] == pytest.approx(z["burn_cost_pct"] / 100 * 60_000 * members[z["ward_key"]])
