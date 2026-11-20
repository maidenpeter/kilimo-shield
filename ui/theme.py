"""Design tokens, CSS and small components (top bar, stat strip, panels, notes) shared by every tab.

One accent colour (the brand green). Amber and red appear only as status: a warning or a problem.
"""
from __future__ import annotations

import html
from contextlib import contextmanager

import streamlit as st

from ui import brand

# Tokens
GREEN = "#14532d"          # brand accent
GREEN_HOVER = "#166534"
GREEN_SOFT = "#ecfdf3"
AMBER = "#a16207"          # warning status (also the fodder layer in charts)
AMBER_SOFT = "#fef9c3"
RED = "#b42318"            # problem status
RED_SOFT = "#fef3f2"
INK = "#101828"
BODY = "#344054"
MUTED = "#475467"          # 7:1 on white
LINE = "#e4e7ec"
PAGE = "#f5f6f4"
SURFACE = "#ffffff"
RADIUS = 10
LAYER_COLOURS = {"Payout A: crop inputs": GREEN, "Payout B: fodder gap": "#ca8a04", "Payout C: vet and health": "#64748b"}

CSS = f"""
<style>
  .stApp {{ background: {PAGE}; color: {BODY}; }}
  header[data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding-top: 2.6rem; padding-bottom: 2.5rem; max-width: 1360px; }}
  h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.01em; text-wrap-style: balance; }}
  h3 {{ font-size: 1.05rem !important; font-weight: 650 !important; margin: 0 0 0.15rem !important;
        padding: 0 !important; }}
  .stMarkdown p, .stMarkdown li {{ text-wrap-style: pretty; }}

  /* top bar */
  .ss-topbar {{ display: flex; align-items: center; gap: 14px; padding: 10px 0 14px; margin-bottom: 4px;
                border-bottom: 1px solid {LINE}; flex-wrap: wrap; }}
  .ss-topbar img {{ width: 40px; height: 40px; display: block; }}
  .ss-topbar .name {{ color: {INK}; font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; }}
  .ss-topbar .tagline {{ color: {MUTED}; font-size: 0.9rem; }}
  .ss-topbar .meta {{ margin-left: auto; text-align: right; color: {MUTED}; font-size: 0.8rem; line-height: 1.5; }}
  .ss-topbar code, .ss-footer code {{ font-size: 0.78rem; color: {BODY}; background: {SURFACE};
                                      border: 1px solid {LINE}; border-radius: 4px; padding: 0 4px; }}
  @media (max-width: 640px) {{ .ss-topbar .meta {{ margin-left: 0; text-align: left; width: 100%; }} }}

  /* panels: bordered containers keyed "sspanel-..." */
  div[class*="st-key-sspanel-"] {{ background: {SURFACE}; border: 1px solid {LINE} !important;
                                   border-radius: {RADIUS}px !important; padding: 18px 20px 14px !important;
                                   margin-bottom: 4px; }}
  .ss-panel-desc {{ color: {MUTED}; font-size: 0.86rem; margin: 0 0 0.6rem; }}

  /* stat strip */
  .ss-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); background: {SURFACE};
               border: 1px solid {LINE}; border-radius: {RADIUS}px; overflow: hidden; margin: 4px 0 14px; }}
  .ss-stat {{ padding: 14px 16px; border-left: 1px solid {LINE}; margin-left: -1px; }}
  .ss-stat .label {{ color: {MUTED}; font-size: 0.82rem; font-weight: 550; }}
  .ss-stat .value {{ color: {INK}; font-size: 1.6rem; font-weight: 700; line-height: 1.25; margin-top: 2px;
                     font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }}
  .ss-stat .value.good {{ color: {GREEN}; }}
  .ss-stat .value.warn {{ color: {AMBER}; }}
  .ss-stat .value.bad {{ color: {RED}; }}
  .ss-stat .note {{ color: {MUTED}; font-size: 0.8rem; margin-top: 4px; line-height: 1.4; }}

  /* status text and notes */
  .ss-status {{ display: inline-block; padding: 1px 8px; border-radius: 6px; font-weight: 650; font-size: 0.82rem;
                font-variant-numeric: tabular-nums; }}
  .ss-status.GREEN {{ background: {GREEN_SOFT}; color: {GREEN}; }}
  .ss-status.AMBER {{ background: {AMBER_SOFT}; color: {AMBER}; }}
  .ss-status.RED {{ background: {RED_SOFT}; color: {RED}; }}
  .ss-note {{ background: #f2f4f7; border-radius: 8px; padding: 9px 12px; color: {BODY}; font-size: 0.86rem;
              margin: 2px 0 10px; }}
  .ss-note b {{ color: {INK}; }}

  /* WhatsApp preview */
  .ss-wa {{ background: #efeae2; border-radius: {RADIUS}px; overflow: hidden; border: 1px solid {LINE}; }}
  .ss-wa .bar {{ background: #075e54; color: #fff; padding: 9px 12px; font-weight: 600; font-size: 0.92rem; }}
  .ss-wa .bar small {{ display: block; font-weight: 400; color: #d1fae5; font-size: 0.75rem; }}
  .ss-wa .bubble {{ background: #fff; margin: 10px; padding: 9px 11px; border-radius: 0 8px 8px 8px;
                    font-size: 0.88rem; color: {INK}; white-space: pre-wrap; }}
  .ss-wa .meta {{ text-align: right; color: #667085; font-size: 0.72rem; margin-top: 4px; }}

  /* buttons: one primary per view, steady colour in every state */
  button[data-testid="stBaseButton-primary"] {{ background: {GREEN} !important; border-color: {GREEN} !important;
                                                 color: #fff !important; }}
  button[data-testid="stBaseButton-primary"]:hover {{ background: {GREEN_HOVER} !important;
                                                       border-color: {GREEN_HOVER} !important; }}
  button[data-testid="stBaseButton-primary"]:focus, button[data-testid="stBaseButton-primary"]:active {{
      background: {GREEN} !important; border-color: {GREEN} !important; color: #fff !important; }}

  /* sidebar */
  section[data-testid="stSidebar"] {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
  section[data-testid="stSidebar"] h4 {{ font-size: 0.8rem !important; color: {MUTED} !important; font-weight: 650 !important;
                                         margin: 0.8rem 0 0.1rem !important; }}

  div[data-testid="stTabs"] button p {{ font-size: 0.95rem; font-weight: 600; }}
  .ss-footer {{ color: {MUTED}; font-size: 0.8rem; margin-top: 18px; padding-top: 10px; border-top: 1px solid {LINE}; }}
  @media print {{
    section[data-testid="stSidebar"], header[data-testid="stHeader"], div[data-testid="stToolbar"],
    .stButton, .stDownloadButton, div[data-testid="stDecoration"] {{ display: none !important; }}
    .stApp {{ background: #fff; }}
  }}
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def top_bar() -> None:
    st.markdown(
        f'<div class="ss-topbar"><img src="{brand.logo_data_uri()}" alt="">'
        f'<div><div class="name">{brand.APP_NAME}</div><div class="tagline">{html.escape(brand.TAGLINE)}</div></div>'
        f'<div class="meta">Calculating agent for: Partner insurer (to be named)<br>'
        f'Illustrative terms, synthetic SACCO data &nbsp;<code>{brand.identifier()}</code></div></div>',
        unsafe_allow_html=True,
    )


def footer(text: str) -> None:
    st.markdown(f'<div class="ss-footer">{text}<br><code>{brand.identifier()}</code></div>', unsafe_allow_html=True)


@contextmanager
def panel(title: str, description: str = ""):
    """A bordered white section with its own heading."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    with st.container(border=True, key=f"sspanel-{slug}"):
        st.markdown(f"### {title}")
        if description:
            st.markdown(f'<p class="ss-panel-desc">{html.escape(description)}</p>', unsafe_allow_html=True)
        yield


def stats(items: list[tuple]) -> None:
    """A row of figures in one strip: (label, value, note[, tone]) with tone '', 'good', 'warn' or 'bad'."""
    cells = []
    for item in items:
        label, value, note = item[:3]
        tone = item[3] if len(item) > 3 else ""
        cells.append(f'<div class="ss-stat"><div class="label">{html.escape(label)}</div>'
                     f'<div class="value {tone}">{html.escape(value)}</div>'
                     f'<div class="note">{html.escape(note)}</div></div>')
    st.markdown(f'<div class="ss-stats">{"".join(cells)}</div>', unsafe_allow_html=True)


def ksh(value: float, decimals: int = 0) -> str:
    return f"KSh {value:,.{decimals}f}"


def ksh_short(value: float) -> str:
    for size, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(value) >= size:
            return f"KSh {value / size:,.1f}{suffix}"
    return f"KSh {value:,.0f}"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def note(text: str) -> None:
    st.markdown(f'<div class="ss-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def status(text: str, tone: str) -> str:
    return f'<span class="ss-status {tone}">{html.escape(text)}</span>'


def plot_layout(fig, height: int = 400):
    """Charts sit inside a titled panel, so they carry no title of their own."""
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font={"color": BODY, "family": "Source Sans Pro, sans-serif"},
        margin={"l": 56, "r": 12, "t": 16, "b": 40}, legend={"orientation": "h", "y": -0.16, "x": 0},
        hoverlabel={"bgcolor": SURFACE},
    )
    fig.update_xaxes(gridcolor=LINE, linecolor=LINE, zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor=LINE, linecolor=LINE, zeroline=False, automargin=True)
    return fig
