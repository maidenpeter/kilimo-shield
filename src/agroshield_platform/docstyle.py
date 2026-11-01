"""Styles for stand-alone documents: the IRA documentation pack (tools/ira) and the simulated-season report.

They are single HTML files that open from disk with no server, so the design system's colour, type and spacing
tokens (web/static/tokens.css, light and dark) are inlined, without the web fonts (served only by the portal; the
display face falls back to Georgia). Components here read the tokens and nothing else, like app.css.
"""
from __future__ import annotations

import re
from pathlib import Path

TOKENS = Path(__file__).parent / "web" / "static" / "tokens.css"

DOC_CSS = """
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--bg); color: var(--ink-1); font-family: var(--font-body); font-size: var(--fs-base);
       line-height: var(--lh-body); }
main { max-width: 980px; margin: 0 auto; padding: var(--sp-5) var(--gutter) var(--sp-8); }
h1, h2, h3 { font-family: var(--font-display); line-height: var(--lh-tight); color: var(--ink-1); }
h1 { font-size: var(--fs-2xl); margin: var(--sp-4) 0 var(--sp-2); }
h2 { font-size: var(--fs-xl); margin: var(--sp-7) 0 var(--sp-3); padding-top: var(--sp-3); border-top: 1px solid var(--border); }
h3 { font-size: var(--fs-lg); margin: var(--sp-5) 0 var(--sp-2); }
p, li { max-width: var(--maxw-prose); }
a { color: var(--accent); }
code, .mono { font-family: var(--font-mono); font-size: var(--fs-xs); overflow-wrap: anywhere; }
.muted { color: var(--ink-3); font-size: var(--fs-sm); }
.lead { font-size: var(--fs-md); color: var(--ink-2); }
.banner { display: flex; flex-wrap: wrap; gap: var(--sp-2) var(--sp-3); align-items: center; margin: 0 0 var(--sp-4);
          padding: var(--sp-3) var(--sp-4); border: 1px solid var(--gold); border-radius: var(--r-md);
          background: var(--gold-soft); color: var(--ink-1); font-size: var(--fs-sm); }
.banner b { color: var(--gold); letter-spacing: .04em; }
.chip { display: inline-block; padding: 1px var(--sp-2); border-radius: var(--r-pill); font-size: var(--fs-2xs);
        font-weight: var(--fw-semibold); letter-spacing: .03em; border: 1px solid var(--border-strong);
        background: var(--surface-2); color: var(--ink-2); white-space: nowrap; }
.chip.ok { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.chip.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.chip.crit { background: var(--crit-soft); color: var(--crit); border-color: var(--crit); }
.chip.info { background: var(--info-soft); color: var(--info); border-color: var(--info); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: var(--sp-4) var(--sp-5);
        margin: var(--sp-3) 0; box-shadow: var(--sh-1); break-inside: avoid; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-3); }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); }
.kpi .v { font-size: var(--fs-lg); font-weight: var(--fw-semibold); font-variant-numeric: tabular-nums; }
.kpi .k { color: var(--ink-3); font-size: var(--fs-xs); }
.table-wrap { overflow-x: auto; margin: var(--sp-2) 0 var(--sp-3); }
table { border-collapse: collapse; width: 100%; font-size: var(--fs-sm); background: var(--surface); }
th, td { text-align: left; padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--surface-2); color: var(--ink-2); font-weight: var(--fw-semibold); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
tr { break-inside: avoid; }
.step { position: relative; }
.step .when { font-family: var(--font-mono); font-size: var(--fs-sm); color: var(--accent-strong); font-weight: var(--fw-semibold); }
.step h3 { margin-top: var(--sp-1); }
.ok-text { color: var(--ok); font-weight: var(--fw-semibold); }
.crit-text { color: var(--crit); font-weight: var(--fw-semibold); }
.clock { display: grid; grid-template-columns: repeat(11, 1fr); gap: 2px; margin: var(--sp-3) 0; }
.clock div { min-height: 64px; padding: var(--sp-1); border-radius: var(--r-sm); background: var(--surface-2);
             border: 1px solid var(--border); font-size: var(--fs-2xs); color: var(--ink-3); }
.clock div.hit { background: var(--accent-soft); border-color: var(--accent); color: var(--ink-1); }
.clock div.due { border-color: var(--crit); }
.clock b { display: block; color: var(--ink-1); font-size: var(--fs-xs); }
svg text { fill: var(--ink-2); font-family: var(--font-body); font-size: 12px; }
svg .line { fill: none; stroke: var(--chart-1); stroke-width: 2; }
svg .trig { stroke: var(--warn); stroke-dasharray: 5 4; }
svg .exit { stroke: var(--crit); stroke-dasharray: 2 4; }
svg .grid { stroke: var(--grid); }
svg .mark { fill: var(--chart-2); }
.toc ol { columns: 2; column-gap: var(--sp-6); }
.page-break { break-before: page; }
@media (max-width: 640px) { .toc ol { columns: 1; } h1 { font-size: var(--fs-xl); } .clock { grid-template-columns: repeat(6, 1fr); } }
@media print {
  @page { size: A4; margin: 18mm 14mm 20mm; }
  :root { color-scheme: light; }
  body { background: #fff; font-size: 10.5pt; }
  main { max-width: none; padding: 0; }
  h2 { break-after: avoid; }
  .card, .kpi { box-shadow: none; }
  a { color: inherit; text-decoration: none; }
}
"""


def tokens_css() -> str:
    """tokens.css without its @font-face rules (their URLs only resolve inside the portal)."""
    return re.sub(r"@font-face\s*\{[^}]*\}\s*", "", TOKENS.read_text(encoding="utf-8"))


def css() -> str:
    return tokens_css() + DOC_CSS
