"""ShambaShield360: parametric backtest, SACCO reconciliation (ShambaRecon) and the WhatsApp trust loop.

    streamlit run app.py
"""
import streamlit as st

from ui import brand, tab_parametric, tab_recon, tab_whatsapp, theme

st.set_page_config(page_title=brand.APP_NAME, page_icon=str(brand.LOGO_PNG), layout="wide",
                   initial_sidebar_state="auto")
theme.apply()
theme.top_bar()

backtest_tab, recon_tab, whatsapp_tab = st.tabs([
    ":material/monitoring: Reinsurer backtest",
    ":material/account_balance: SACCO reconciliation",
    ":material/forum: Trust loop and unit economics",
])

with backtest_tab:
    backtest = tab_parametric.render()
with recon_tab:
    params = backtest["params"]
    tab_recon.render(backtest["offered_premiums"], backtest["zone_farmer_premiums"], sum_insured=params.sum_insured,
                     gross_premiums=backtest["zone_premiums"])
with whatsapp_tab:
    tab_whatsapp.render(backtest["ward_key"], backtest["kpis"].burn_cost_pct, backtest["kpis"].premium_rate_pct / 100)

theme.footer(
    'Weather data by <a href="https://open-meteo.com/" target="_blank">Open-Meteo.com</a> (CC BY 4.0, ERA5-based '
    'reanalysis). Soil moisture and NDVI are synthetic proxies computed from that weather, not satellite readings. '
    'SACCO members, M-Pesa payments and WhatsApp verifiers are fictional. Sums insured, premium rates, triggers and '
    'fees are illustrative and need actuarial sign-off, the partner insurer\'s agreement and IRA approval before any sale.'
)
