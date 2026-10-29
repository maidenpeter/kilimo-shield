"""Build docs/research/advance-and-short-rains.html from the research results.

Run after research/advance.py and research/short_rains.py:
    .venv/Scripts/python research/report_advance_sr.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import jinja2

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "research"
OUT = REPO / "docs" / "research" / "advance-and-short-rains.html"
STYLE = re.search(r"<style>.*?</style>", (REPO / "research" / "templates" / "3b.html").read_text(encoding="utf-8"),
                  re.S).group(0)

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Advance and Short Rains</title>{{ style | safe }}</head>
<body><main>
<h1>Early advance on Layer B, and short-rains candidates</h1>
<p class="meta">Built {{ built }} from data/raw/research/advance_results.json and short_rains_results.json.
  Research only: nothing here changes a quote. <span class="chip ILLUSTRATIVE">ILLUSTRATIVE TERMS</span></p>

<div class="banner"><b>Short answers.</b>
<ul>
<li><b>Advance at Ward A (EXPERIMENTAL):</b> at day {{ a.terms.check_day_after_sos }}, a projected WRSI below
  {{ a.terms.projected_wrsi_below|g }} fired in {{ w.in_sample.fired }} of {{ w.seasons }} long-rains seasons
  ({{ w.years[0] }}&ndash;{{ w.years[1] }}). All {{ w.in_sample.hits }} were real Layer B payout seasons, with no false
  alarms; {{ w.in_sample.misses }} payout seasons got no advance. Out of sample (leave-one-out):
  {{ w.loocv.out_of_sample.hits }} hits and {{ w.loocv.out_of_sample.false_alarms }} false alarms
  ({{ w.loocv_conservative.out_of_sample.hits }} hits when ties go to the lowest threshold). The extra cost is about
  {{ kes(price10.expected_extra_kes) }} per acre a year (gross {{ kes(price10.gross_kes) }}) at KES 10,000 sum insured.</li>
<li><b>Short rains:</b> the shortlisted candidates near {{ sr.sites|map(attribute='near')|join(' and ') }} have real OND
  forecast skill (C3S r {{ sr.sites|map(attribute='c3s_ond.correlation.r')|map('round', 2)|join(' and ') }}), but
  Layer B maize cover is not insurable at a sensible price with a 100-day variety. Only {{ best.near }} with an
  80-day variety comes near the payout-frequency target, and even then gross premium is
  {{ pct(best_gross) }} of sum insured.</li>
</ul></div>

<h2>1. Early advance on Layer B (Ward A, long rains)</h2>
<p>About {{ a.terms.check_day_after_sos }} days after the start of season, the end-of-season WRSI is projected from
  observed CHIRPS so far, the {{ a.terms.forecast }} forecast and climatology for the rest of the season. Below
  {{ a.terms.projected_wrsi_below|g }}, the farmer gets {{ pct(a.terms.advance_share) }} of the sum insured at once. At the
  end of the season the advance is deducted from the Layer B payout and never clawed back, so the farmer receives the
  larger of the two. Only the extra (advance above the final payout, or the whole advance on a false alarm) is priced.</p>

<div class="card"><table>
<tr><th>Out of {{ w.seasons }} seasons</th><th class="num">Fired</th><th class="num">Hits</th><th class="num">Misses</th>
  <th class="num">False alarms</th><th class="num">Hit rate</th><th class="num">Peirce score</th></tr>
{% for label, v in [("Threshold " ~ (a.terms.projected_wrsi_below|g) ~ ", all seasons", w.in_sample),
                    ("Leave-one-out, ties to the nearest threshold to 95", w.loocv.out_of_sample),
                    ("Leave-one-out, ties to the lowest threshold", w.loocv_conservative.out_of_sample)] %}
<tr><td>{{ label }}</td><td class="num">{{ v.fired }}</td><td class="num">{{ v.hits }}</td><td class="num">{{ v.misses }}</td>
  <td class="num">{{ v.false_alarms }}</td><td class="num">{{ pct(v.hit_rate) }}</td><td class="num">{{ '%.2f'|format(v.peirce) }}</td></tr>
{% endfor %}
</table>
<p class="meta">A hit is an advance in a season that ended with a Layer B payout. In each leave-one-out fold the threshold
  was re-chosen from {{ a.terms.threshold_grid|join(', ') }} on the other {{ w.seasons - 1 }} seasons (best Peirce score:
  hit rate minus false-alarm rate) and applied to the held-out season. Folds chose:
  {% for t, n in w.loocv.thresholds_chosen.items() %}{{ t }} ({{ n }}){{ ', ' if not loop.last }}{% endfor %} (nearest-to-95 tie-break);
  {% for t, n in w.loocv_conservative.thresholds_chosen.items() %}{{ t }} ({{ n }}){{ ', ' if not loop.last }}{% endfor %} (lowest).</p></div>

<div class="answer"><b>How solid is 95?</b> Any threshold from {{ w.equivalent_range[0] }} to {{ w.equivalent_range[1] }}
  makes exactly the same decisions on these {{ w.seasons }} seasons, so 95 is not tuned to a knife edge. But the record is
  short: {{ w.in_sample.events }} payout seasons and {{ w.in_sample.fired }} advances. Zero false alarms in
  {{ w.in_sample.fired }} is encouraging, not proof. {% if flips %}With ties broken against 95, held-out
  {% for h in flips %}{{ h.year }} (projected {{ '%.1f'|format(h.projected_wrsi) }}){{ ', ' if not loop.last }}{% endfor %}
  loses its advance, which shows how few seasons sit near the threshold.{% endif %}
  {% if w.missing_years %}Missing: {{ w.missing_years|join(', ') }} ({{ w.missing_note }}){% endif %}</div>

<h3>Price of the advance (net extra cost only)</h3>
<div class="card"><table>
<tr><th>Sum insured per acre</th><th class="num">Expected extra</th><th class="num">Gross (same loadings as Layer B)</th></tr>
{% for o in w.pricing.per_acre %}<tr><td>{{ kes(o.sum_insured_kes_per_acre) }}</td><td class="num">{{ kes(o.expected_extra_kes) }}</td>
  <td class="num">{{ kes(o.gross_kes) }}</td></tr>{% endfor %}
</table><p class="meta">Expected extra cost {{ pct(w.pricing.expected_extra_share, 2) }} of sum insured a year. It comes from
  seasons where the advance was larger than the final payout (or a false alarm). Not in any quote while the status is
  EXPERIMENTAL.</p></div>

<h3>Threshold sensitivity</h3>
<div class="card table-wrap"><table>
<tr><th class="num">Threshold</th><th class="num">Fired</th><th class="num">Hits</th><th class="num">False alarms</th><th class="num">Misses</th>
  <th class="num">Expected extra (share of SI)</th></tr>
{% for r in w.sensitivity %}<tr{% if r.threshold == a.terms.projected_wrsi_below %} style="font-weight:700"{% endif %}>
  <td class="num">{{ r.threshold|g }}</td><td class="num">{{ r.fired }}</td><td class="num">{{ r.hits }}</td>
  <td class="num">{{ r.false_alarms }}</td><td class="num">{{ r.misses }}</td><td class="num">{{ pct(r.expected_extra_share, 2) }}</td></tr>{% endfor %}
</table></div>

<details><summary>Season by season</summary><div class="table-wrap"><table>
<tr><th>Year</th><th>Start of season</th><th class="num">Projected WRSI (day {{ a.terms.check_day_after_sos }})</th>
  <th class="num">Final WRSI</th><th class="num">Final Layer B payout</th><th>Advance</th><th class="num">Farmer receives</th>
  <th class="num">Extra cost</th></tr>
{% for h in w.history %}<tr><td>{{ h.year }}</td><td>{{ h.sos }}</td><td class="num">{{ '%.1f'|format(h.projected_wrsi) }}</td>
  <td class="num">{{ '%.1f'|format(h.actual_wrsi) }}</td><td class="num">{{ pct(h.final_share) }}</td>
  <td>{{ 'yes' if h.fired else '' }}</td><td class="num">{{ pct(h.farmer_receives_share) }}</td>
  <td class="num">{{ pct(h.extra_share, 1) if h.extra_share else '' }}</td></tr>{% endfor %}
</table></div></details>

<h2>2. Short-rains candidates (report only; not in the pilot config)</h2>
<p>Rule: {{ sr.rule }}. Ranking by OND share:
  {% for r in sr.ranked %}{{ r.near }} {{ pct(r.ond_share) }}{{ ', ' if not loop.last }}{% endfor %}.
  Each candidate is a single CHIRPS cell, not a ward boundary. Ward names come once IEBC boundaries are overlaid.
  Calendar (ILLUSTRATIVE): planting window {{ sr.calendar.planting_window.start }} to {{ sr.calendar.planting_window.end }},
  {{ sr.calendar.variety }}. Soil water capacity and elevation are placeholders. PET is the flagged Hargreaves fallback.</p>
{% for s in sr.sites %}
<h3>Near {{ s.near }} ({{ s.lat }}, {{ s.lon }})</h3>
<div class="card table-wrap"><table>
<tr><th>Variety length</th><th class="num">Median WRSI</th><th class="num">Payout seasons</th><th class="num">About 1 in</th>
  <th class="num">Replanting</th><th class="num">Gross rate</th><th class="num">Gross per acre (KES 10,000)</th></tr>
{% for lgp, b in s.layer_b.items() %}<tr><td>{{ lgp }} days</td><td class="num">{{ '%.1f'|format(b.median_wrsi) }}</td>
  <td class="num">{{ pct(b.main_payout_frequency) }}</td><td class="num">{{ '%.1f'|format(1 / b.main_payout_frequency) if b.main_payout_frequency else 'never' }}</td>
  <td class="num">{{ pct(b.replanting_frequency) }}</td><td class="num">{{ pct(b.gross_rate) }}</td>
  <td class="num">{{ kes(b.gross_kes_per_acre['10000']) }}</td></tr>{% endfor %}
</table>
<p class="meta">Target band: one payout season in 5 to 7 years ({{ pct(s.layer_b['100'].target_band[0]) }} to
  {{ pct(s.layer_b['100'].target_band[1]) }}). Trigger sensitivity at 100 days:
  {% for t in s.layer_b['100'].trigger_sensitivity %}WRSI {{ t.trigger_wrsi|g }}: {{ pct(t.main_frequency) }} / gross {{ pct(t.gross_rate) }}{{ '; ' if not loop.last }}{% endfor %}.
  Soil sensitivity at 100 days:
  {% for t in s.layer_b['100'].whc_sensitivity %}{{ t.whc_mm|g }} mm: {{ pct(t.payout_frequency) }} / gross {{ pct(t.gross_rate) }}{{ '; ' if not loop.last }}{% endfor %}.</p>
<p><b>C3S OND skill</b> (cell {{ s.c3s_cell[0] }}E {{ s.c3s_cell[1] }}, {{ s.c3s_ond.years[0] }}&ndash;{{ s.c3s_ond.years[1] }}):
  r {{ '%.2f'|format(s.c3s_ond.correlation.r) }} (95% CI {{ '%.2f'|format(s.c3s_ond.correlation.ci95[0]) }} to
  {{ '%.2f'|format(s.c3s_ond.correlation.ci95[1]) }}), ROC AUC for a below-normal OND
  {{ '%.2f'|format(s.c3s_ond.tercile.roc_auc) if s.c3s_ond.tercile.roc_auc is not none else 'n/a' }}.</p></div>
{% endfor %}

<div class="answer"><b>Reading.</b> Short-rains rain here is well forecast: OND skill is clearly above zero, unlike
  Nakuru's long rains. But maize on these soils fails often. With a 100-day variety the index pays in
  {{ pct(sr.sites[0].layer_b['100'].main_payout_frequency) }} and {{ pct(sr.sites[1].layer_b['100'].main_payout_frequency) }}
  of seasons, far above 1 in 5 to 7, and the payouts are large, so gross premium is a large share of sum insured. An
  80-day variety brings {{ best.near }} to the edge of the band, but losses stay severe when they happen. Before an OND
  ward goes further: (1) real crop calendars and varieties from the county, (2) soil data, (3) FEWS NET PET instead of
  Hargreaves at low elevation, and (4) whether the crop should be sorghum or green grams rather than maize. A
  forecast-based layer (Layer A-style) may suit these areas better than it suits Nakuru, because the skill is real.</div>

<h2>Caveats</h2>
<ul><li>All product terms are ILLUSTRATIVE. PET is the Hargreaves fallback, flagged; FEWS NET PET and WRSI are still unavailable.</li>
<li>The advance projections use leave-one-out climatology for the unobserved part of each season, so the held-out
  season never informs its own projection. CHIRPS-GEFS hindcasts start in 2000.</li>
<li>Short-rains candidates are research cells, not wards, and are not in config/.</li></ul>
</main></body></html>"""


def main() -> None:
    a = json.loads((RAW / "advance_results.json").read_text())
    sr = json.loads((RAW / "short_rains_results.json").read_text())
    w = a["wards"]["ward-a"]
    near = {h["year"]: h for h in w["loocv"]["history"]}
    cons = {h["year"]: h for h in w["loocv_conservative"]["history"]}
    proj = {h["year"]: h["projected_wrsi"] for h in w["history"]}
    flips = [{"year": y, "projected_wrsi": proj[y]} for y in near if near[y]["fired"] != cons[y]["fired"]]
    best = min(sr["sites"], key=lambda s: abs(s["layer_b"]["80"]["main_payout_frequency"] - 1 / 6))
    env = jinja2.Environment(autoescape=True, undefined=jinja2.StrictUndefined)
    env.filters["g"] = lambda v: f"{v:g}"
    html = env.from_string(TEMPLATE).render(
        style=STYLE, built=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), a=a, w=w, sr=sr, best=best, flips=flips,
        best_gross=best["layer_b"]["80"]["gross_rate"],
        price10=next(o for o in w["pricing"]["per_acre"] if o["sum_insured_kes_per_acre"] == 10000),
        kes=lambda v: f"KES {v:,.0f}", pct=lambda v, d=0: "n/a" if v is None else f"{v * 100:.{d}f}%")
    OUT.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
