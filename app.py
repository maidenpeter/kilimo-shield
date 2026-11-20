"""ShambaShield 360 and ShambaRecon: executive dashboard.

    streamlit run app.py
"""
import streamlit as st

from ui import tab_parametric, tab_recon, tab_whatsapp, theme

st.set_page_config(page_title="ShambaShield 360 & ShambaRecon", page_icon="🌾", layout="wide",
                   initial_sidebar_state="auto")
theme.apply()

st.markdown(
    '<div class="ss-header"><h1>ShambaShield 360 &amp; ShambaRecon</h1>'
    '<p>Mixed-farm parametric insurance (crop and livestock) and automated SACCO reconciliation for Kenya</p>'
    '<span class="ss-chip">Calculating agent for: Partner insurer (to be named)</span>'
    '<span class="ss-chip">ILLUSTRATIVE pilot terms</span>'
    '<span class="ss-chip">Synthetic SACCO data</span></div>',
    unsafe_allow_html=True,
)

backtest_tab, recon_tab, whatsapp_tab = st.tabs(
    ["Reinsurer backtest engine", "SACCO reconciliation matcher", "WhatsApp trust loop and unit economics"])

with backtest_tab:
    backtest = tab_parametric.render()
with recon_tab:
    params = backtest["params"]
    tab_recon.render(backtest["offered_premiums"], backtest["zone_farmer_premiums"], sum_insured=params.sum_insured)
with whatsapp_tab:
    tab_whatsapp.render(backtest["ward_key"], backtest["kpis"].burn_cost_pct, backtest["kpis"].premium_rate_pct / 100)

st.markdown(
    '<div class="ss-footer">Weather data by <a href="https://open-meteo.com/" target="_blank">Open-Meteo.com</a> '
    '(CC BY 4.0, ERA5-based reanalysis). Soil moisture and NDVI are synthetic proxies computed from that weather, '
    'not satellite readings. SACCO members, M-Pesa payments and WhatsApp verifiers are fictional. Sums insured, '
    'premium rates, triggers and fees are illustrative and need actuarial sign-off, the partner insurer\'s '
    'agreement and IRA approval before any sale.</div>',
    unsafe_allow_html=True,
)
