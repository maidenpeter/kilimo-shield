"""Design tokens, CSS and small components (top bar, stat strip, panels, notes) shared by every tab.

One accent colour (the brand green). Amber and red appear only as status: a warning or a problem.
"""
from __future__ import annotations

import html
import math
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal, localcontext

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
  /* navbar: Streamlit's own header bar carries the logo and the name */
  header[data-testid="stHeader"] {{ background: {SURFACE}; border-bottom: 1px solid {LINE}; }}
  header[data-testid="stHeader"]::before {{
      content: "{brand.APP_NAME}"; position: absolute; left: 1.25rem; top: 0; height: 100%; z-index: 1;
      display: flex; align-items: center; padding-left: 36px; pointer-events: none;
      background: url("{brand.logo_data_uri()}") no-repeat left center / 27px 27px;
      font-family: "IBM Plex Sans", sans-serif; font-weight: 700; font-size: 1.15rem; color: {INK};
      letter-spacing: -0.015em; }}
  .stApp:has(section[data-testid="stSidebar"][data-collapsed="true"]) header[data-testid="stHeader"]::before {{
      left: 3.5rem; }}
  .block-container {{ padding-top: 4.4rem; padding-bottom: 2.5rem; max-width: 1360px; }}
  h1, h2, h3, h4 {{ color: {INK}; letter-spacing: -0.01em; text-wrap-style: balance; }}
  h3 {{ font-size: 1.05rem !important; font-weight: 650 !important; margin: 0 0 0.15rem !important;
        padding: 0 !important; }}
  .stMarkdown p, .stMarkdown li {{ text-wrap-style: pretty; }}

  /* context line under the navbar */
  .ss-context {{ color: {MUTED}; font-size: 0.85rem; margin: 0 0 2px; }}
  .ss-context b {{ color: {BODY}; font-weight: 600; }}
  .ss-footer code {{ font-family: "IBM Plex Mono", monospace; font-size: 0.78rem; color: {BODY};
                     background: {SURFACE}; border: 1px solid {LINE}; border-radius: 4px; padding: 0 4px; }}

  /* panels: bordered containers keyed "sspanel-..." */
  div[class*="st-key-sspanel-"] {{ background: {SURFACE}; border: 1px solid {LINE} !important;
                                   border-radius: {RADIUS}px !important; padding: 18px 20px 14px !important;
                                   margin-bottom: 4px; }}
  .ss-panel-desc {{ color: {MUTED}; font-size: 0.86rem; margin: 0 0 0.6rem; }}
  .stMarkdown p.ss-map-story {{ color: {INK}; font-size: 1.02rem; line-height: 1.5; margin: 4px 0 14px;
    text-wrap: pretty; }}

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

  /* story: chapter header, ledger, steps, next */
  .stMarkdown p.ss-eyebrow {{ color: {GREEN}; font-size: 0.85rem; font-weight: 600; margin: 6px 0 2px; }}
  .ss-eyebrow span {{ color: {MUTED}; font-weight: 400; }}
  .stMarkdown p.ss-lede {{ color: {INK}; font-size: 1.85rem; line-height: 1.22; font-weight: 650;
                           letter-spacing: -0.015em; margin: 0 0 8px; max-width: 44ch; text-wrap-style: balance; }}
  .stMarkdown p.ss-sub {{ color: {BODY}; font-size: 1.02rem; margin: 0 0 14px; max-width: 78ch; }}
  @media (max-width: 640px) {{ .stMarkdown p.ss-lede {{ font-size: 1.4rem; }} }}
  .ss-ledger {{ display: grid; grid-template-columns: 1fr auto; gap: 6px 16px; font-variant-numeric: tabular-nums;
                margin: 4px 0 8px; }}
  .ss-ledger .amt {{ text-align: right; color: {INK}; }}
  .ss-ledger .muted {{ color: {MUTED}; }}
  .ss-ledger .total {{ border-top: 1px solid {INK}; padding-top: 6px; font-weight: 700; color: {INK}; }}
  .ss-big {{ font-size: 2.4rem; font-weight: 700; color: {INK}; line-height: 1.1; font-variant-numeric: tabular-nums;
             letter-spacing: -0.02em; }}
  .ss-big small {{ font-size: 1rem; font-weight: 500; color: {MUTED}; letter-spacing: 0; }}
  .ss-steps {{ list-style: none; counter-reset: step; padding: 0; margin: 4px 0 0; display: grid;
               grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
  .ss-steps li {{ counter-increment: step; border-top: 2px solid {GREEN}; padding-top: 8px; color: {BODY};
                  font-size: 0.9rem; }}
  .ss-steps li::before {{ content: counter(step); display: block; color: {GREEN}; font-weight: 700; font-size: 0.85rem; }}
  .ss-steps li b {{ display: block; color: {INK}; font-size: 0.98rem; margin-bottom: 2px; }}
  .stMarkdown p.ss-next {{ margin: 18px 0 0; padding: 12px 0 0; border-top: 1px dashed {LINE}; color: {MUTED};
                           font-size: 0.92rem; }}
  .ss-next b {{ color: {GREEN}; }}

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


def context_line() -> None:
    """One quiet line under the navbar: what this is, for whom, and how real the numbers are."""
    st.markdown(
        f'<p class="ss-context">{html.escape(brand.TAGLINE)}. Calculating agent for: <b>Partner insurer (to be '
        f'named)</b>. Illustrative terms, synthetic SACCO data.</p>',
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


def _half_up(value: float, decimals: int) -> Decimal:
    """Money rounds half up (KSh 2.50 shows as KSh 3), not to even as Python's format does. Float noise below a
    millionth is removed first, so 20,249,999.999999996 (noise for 20,250,000) is treated as the whole it is."""
    with localcontext() as ctx:
        ctx.prec = 60
        shown = Decimal(repr(round(float(value), 6))).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return shown + 0 if shown else abs(shown)  # never "KSh -0"


def ksh(value: float, decimals: int = 0) -> str:
    if value is None or not math.isfinite(float(value)):
        return "KSh n/a"
    return f"KSh {_half_up(value, decimals):,.{decimals}f}"


def ksh_short(value: float) -> str:
    """KSh 1.2m style. The unit is chosen after rounding, so 999,950 shows as KSh 1.0m, not KSh 1,000.0k."""
    units = ((1e9, "bn"), (1e6, "m"), (1e3, "k"))
    for i, (size, suffix) in enumerate(units):
        if abs(value) >= size:
            shown = _half_up(value / size, 1)
            if abs(shown) >= 1000 and i > 0:  # rounding carried it into the next unit
                size, suffix = units[i - 1]
                shown = _half_up(value / size, 1)
            return f"KSh {shown:,.1f}{suffix}"
    return ksh(value)


def pct(value: float, decimals: int = 1) -> str:
    """Percentages round half up too: 82.5% at no decimals shows as 83%."""
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{_half_up(value, decimals)}%"


def chapter(number: int, name: str, context: str, lede: str, sub: str = "") -> None:
    """Open a chapter: where we are, the one sentence the numbers say, and what it means."""
    st.markdown(
        f'<p class="ss-eyebrow">Chapter {number}: {html.escape(name)} <span>&middot; {html.escape(context)}</span></p>'
        f'<p class="ss-lede">{html.escape(lede)}</p>' + (f'<p class="ss-sub">{html.escape(sub)}</p>' if sub else ""),
        unsafe_allow_html=True,
    )


def next_chapter(number: int, name: str, teaser: str) -> None:
    st.markdown(f'<p class="ss-next"><b>Next, chapter {number}: {html.escape(name)}.</b> {html.escape(teaser)} '
                f'Open it in the tabs above.</p>', unsafe_allow_html=True)


def ledger(rows: list[tuple]) -> None:
    """Label and amount rows: (label, amount text[, 'muted' | 'total'])."""
    cells = []
    for row in rows:
        label, amount = row[:2]
        kind = row[2] if len(row) > 2 else ""
        cells.append(f'<span class="{kind}">{html.escape(label)}</span><span class="amt {kind}">{html.escape(amount)}</span>')
    st.markdown(f'<div class="ss-ledger">{"".join(cells)}</div>', unsafe_allow_html=True)


def big(value: str, small: str = "") -> None:
    st.markdown(f'<div class="ss-big">{html.escape(value)} <small>{html.escape(small)}</small></div>',
                unsafe_allow_html=True)


def steps(items: list[tuple[str, str]]) -> None:
    lis = "".join(f"<li><b>{html.escape(t)}</b>{html.escape(d)}</li>" for t, d in items)
    st.markdown(f'<ol class="ss-steps">{lis}</ol>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="ss-note">{html.escape(text)}</div>', unsafe_allow_html=True)


def status(text: str, tone: str) -> str:
    return f'<span class="ss-status {tone}">{html.escape(text)}</span>'


def year_axis(fig, years) -> None:
    """Two-digit year labels ('15 to '24) so ten years fit a phone-width chart without turning sideways."""
    fig.update_xaxes(tickmode="array", tickvals=list(years), ticktext=[f"’{y % 100:02d}" for y in years],
                     tickangle=0, title="Year")


def plot_layout(fig, height: int = 400):
    """Charts sit inside a titled panel, so they carry no title of their own."""
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font={"color": BODY, "family": "IBM Plex Sans, sans-serif"},
        margin={"l": 56, "r": 12, "t": 16, "b": 40}, legend={"orientation": "h", "y": -0.16, "x": 0},
        hoverlabel={"bgcolor": SURFACE},
    )
    fig.update_xaxes(gridcolor=LINE, linecolor=LINE, zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor=LINE, linecolor=LINE, zeroline=False, automargin=True)
    return fig
