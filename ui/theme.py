"""Shared look: colours, CSS, KPI cards and number formatting."""
from __future__ import annotations

import html

import streamlit as st

GREEN = "#14532d"
GREEN_SOFT = "#dcfce7"
AMBER = "#b45309"
AMBER_SOFT = "#fef3c7"
SLATE = "#f8fafc"
INK = "#0f172a"
MUTED = "#475569"
LINE = "#e2e8f0"
RED = "#b91c1c"
RED_SOFT = "#fee2e2"
LAYER_COLOURS = {"Payout A: crop inputs": GREEN, "Payout B: fodder gap": AMBER, "Payout C: vet and health": "#64748b"}

CSS = f"""
<style>
  .stApp {{ background: {SLATE}; color: {INK}; }}
  .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }}
  h1, h2, h3 {{ color: {GREEN}; letter-spacing: -0.01em; }}
  .ss-header {{ background: linear-gradient(120deg, {GREEN} 0%, #166534 70%, {AMBER} 160%); color: #fff;
      border-radius: 14px; padding: 18px 22px; margin-bottom: 14px; }}
  .ss-header h1 {{ color: #fff; font-size: 1.65rem; margin: 0; }}
  .ss-header p {{ margin: 4px 0 0; color: #ecfdf5; font-size: 0.95rem; }}
  .ss-chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
      margin: 6px 6px 0 0; background: rgba(255,255,255,0.16); color: #fff; border: 1px solid rgba(255,255,255,0.35); }}
  .ss-kpi {{ background: #fff; border: 1px solid {LINE}; border-top: 4px solid {GREEN}; border-radius: 12px;
      padding: 14px 16px; height: 100%; box-shadow: 0 1px 2px rgba(15,23,42,0.04); }}
  .ss-kpi.amber {{ border-top-color: {AMBER}; }}
  .ss-kpi.red {{ border-top-color: {RED}; }}
  .ss-kpi .label {{ color: {MUTED}; font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.04em; }}
  .ss-kpi .value {{ color: {INK}; font-size: 1.7rem; font-weight: 700; line-height: 1.2; margin-top: 4px; }}
  .ss-kpi .note {{ color: {MUTED}; font-size: 0.82rem; margin-top: 4px; }}
  .ss-badge {{ display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 700; font-size: 0.85rem; }}
  .ss-badge.GREEN {{ background: {GREEN_SOFT}; color: {GREEN}; }}
  .ss-badge.AMBER {{ background: {AMBER_SOFT}; color: {AMBER}; }}
  .ss-badge.RED {{ background: {RED_SOFT}; color: {RED}; }}
  .ss-note {{ background: #fff; border-left: 4px solid {AMBER}; border-radius: 8px; padding: 10px 14px;
      color: {MUTED}; font-size: 0.88rem; margin: 8px 0 12px; }}
  .ss-wa {{ background: #e5ddd5; border-radius: 14px; overflow: hidden; border: 1px solid {LINE}; max-width: 460px; }}
  .ss-wa .bar {{ background: #075e54; color: #fff; padding: 10px 14px; font-weight: 600; }}
  .ss-wa .bar small {{ display: block; font-weight: 400; color: #d1fae5; }}
  .ss-wa .bubble {{ background: #fff; margin: 12px; padding: 10px 12px; border-radius: 0 10px 10px 10px;
      font-size: 0.9rem; color: {INK}; white-space: pre-wrap; box-shadow: 0 1px 1px rgba(0,0,0,0.08); }}
  .ss-wa .meta {{ text-align: right; color: #64748b; font-size: 0.72rem; margin-top: 6px; }}
  .ss-footer {{ color: {MUTED}; font-size: 0.8rem; border-top: 1px solid {LINE}; margin-top: 28px; padding-top: 10px; }}
  div[data-testid="stTabs"] button p {{ font-size: 1rem; font-weight: 600; }}
  @media print {{
    section[data-testid="stSidebar"], header[data-testid="stHeader"], div[data-testid="stToolbar"],
    .stButton, .stDownloadButton, div[data-testid="stDecoration"] {{ display: none !important; }}
    .stApp {{ background: #fff; }}
    .ss-kpi {{ box-shadow: none; break-inside: avoid; }}
  }}
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def ksh(value: float, decimals: int = 0) -> str:
    return f"KSh {value:,.{decimals}f}"


def ksh_short(value: float) -> str:
    for size, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(value) >= size:
            return f"KSh {value / size:,.1f}{suffix}"
    return f"KSh {value:,.0f}"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def kpi(label: str, value: str, note: str = "", tone: str = "") -> None:
    st.markdown(
        f'<div class="ss-kpi {tone}"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div><div class="note">{html.escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def note(text: str) -> None:
    st.markdown(f'<div class="ss-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def badge(text: str, tone: str) -> str:
    return f'<span class="ss-badge {tone}">{html.escape(text)}</span>'


def plot_layout(fig, title: str, height: int = 420):
    fig.update_layout(
        title={"text": title, "x": 0.01, "font": {"size": 16, "color": GREEN}}, height=height,
        paper_bgcolor="#fff", plot_bgcolor="#fff", font={"color": INK},
        margin={"l": 60, "r": 20, "t": 60, "b": 50}, legend={"orientation": "h", "y": -0.18},
        hoverlabel={"bgcolor": "#fff"},
    )
    fig.update_xaxes(gridcolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, linecolor=LINE)
    return fig
