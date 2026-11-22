"""A printable quotation: one branded HTML page the SACCO officer can hand over, print or save as PDF."""
from __future__ import annotations

import html
from datetime import date

from engine import quote as qt
from engine.parametric_engine import WARDS
from ui import brand, theme

CSS = """
@page { size: A4; margin: 16mm; }
* { box-sizing: border-box; }
body { font-family: 'IBM Plex Sans', Arial, sans-serif; color: #344054; margin: 0; background: #f5f6f4; }
.doc { max-width: 820px; margin: 24px auto; background: #fff; padding: 40px 48px; border: 1px solid #e4e7ec;
       border-radius: 10px; }
header { display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #14532d;
         padding-bottom: 16px; }
.brand { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 700; color: #101828; }
.brand img { width: 44px; height: 44px; }
.brand small { display: block; font-size: 13px; font-weight: 500; color: #475467; letter-spacing: 0.01em; }
.number { text-align: right; font-size: 13px; color: #475467; }
.number b { display: block; font-size: 16px; color: #101828; }
h2 { font-size: 15px; color: #14532d; text-transform: uppercase; letter-spacing: 1.5px; margin: 26px 0 8px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
td { padding: 6px 0; border-bottom: 1px solid #eef0f2; }
td.amt { text-align: right; color: #101828; }
tr.total td { border-top: 2px solid #101828; border-bottom: none; font-weight: 700; color: #101828; padding-top: 9px; }
.pays { margin-top: 18px; background: #ecfdf3; border-radius: 8px; padding: 14px 18px; font-size: 15px; color: #14532d; }
.pays b { font-size: 26px; display: block; color: #101828; }
.note { font-size: 12px; color: #475467; margin-top: 18px; line-height: 1.5; }
.warn { background: #fef3f2; border-left: 3px solid #b42318; color: #7a271a; padding: 8px 12px; font-size: 12.5px;
        border-radius: 4px; margin-top: 14px; }
.sign { display: flex; gap: 40px; margin-top: 40px; font-size: 12.5px; color: #475467; }
.sign div { flex: 1; border-top: 1px solid #98a2b3; padding-top: 6px; }
@media print { body { background: #fff; } .doc { border: none; margin: 0; padding: 0; } }
"""


def _rows(rows: list[tuple]) -> str:
    out = []
    for row in rows:
        label, amount = row[:2]
        cls = f' class="{row[2]}"' if len(row) > 2 else ""
        out.append(f"<tr{cls}><td>{html.escape(label)}</td><td class=\"amt\">{html.escape(amount)}</td></tr>")
    return "<table>" + "".join(out) + "</table>"


def quotation_html(q: qt.Quote, prepared_for: dict | None = None, issued: date | None = None) -> str:
    """The quotation as a self-contained page (the logo is inline, so it opens offline)."""
    ward = WARDS[q.ward_key]
    number = qt.quotation_number(q, prepared_for)
    given = [(label, (prepared_for or {}).get(key, "").strip()) for key, label in qt.PREPARED_FOR]
    who = _rows([(label, value) for label, value in given if value]) if any(v for _, v in given) else \
        '<p class="note">No farmer details given: this is a price check, not made out to anyone.</p>'
    paid = q.history[q.history["payout_total"] > 0]
    cover = _rows([
        (f"Crop inputs: {theme.ksh(q.unit_cover['crop'])} an acre", theme.ksh(q.cover["crop"])),
        (f"Fodder gap: {theme.ksh(q.unit_cover['fodder'])} a cow", theme.ksh(q.cover["fodder"])),
        (f"Vet and health: {theme.ksh(q.unit_cover['vet'])} a cow", theme.ksh(q.cover["vet"])),
        ("Sum insured", theme.ksh(q.sum_insured), "total"),
    ])
    price_rows = [(f"Gross premium, {qt.rate_text(q.premium_rate)} of the sum insured", theme.ksh(q.gross_premium))]
    if q.government_share:
        price_rows.append((f"Government share (illustrative {q.subsidy_share:.0%}: none agreed)",
                           f"- {theme.ksh(q.government_share)}"))
    if q.discount:
        price_rows.append((f"Resilience discount, {q.resilience_points} points ({q.discount_rate:.0%})",
                           f"- {theme.ksh(q.discount)}"))
    price_rows.append(("Farmer pays a season", theme.ksh(q.farmer_pays), "total"))
    how_to_pay = ("One M-Pesa payment to the SACCO paybill with the member number as the account"
                  + (f", or about {theme.ksh(q.per_day_checkoff)} a day off the milk cheque for {qt.CHECKOFF_DAYS} days."
                     if q.per_day_checkoff is not None else "."))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Quotation {html.escape(number)}</title><style>{CSS}</style></head><body><div class="doc">
<header><div class="brand"><img src="{brand.logo_data_uri()}" alt=""><div>{html.escape(brand.APP_NAME)}<small>{html.escape(brand.BYLINE)}</small></div></div>
<div class="number"><b>Quotation {html.escape(number)}</b>Issued {qt.long_date(issued or date.today())} ·
valid until {qt.long_date(q.enrolment_closes)}</div></header>
<h2>Prepared for</h2>{who}
<h2>The farm and its cover</h2>
<p class="note" style="margin-top:0">{html.escape(ward.label)} ({html.escape(ward.zone)} zone),
{html.escape(qt.farm_words(q.acres, q.cows))}, {html.escape(qt.SEASON_WORDS[q.season])} {qt.COVER_YEAR}.
Cover starts {qt.long_date(q.cover_starts)}; the most it pays in one season is {theme.ksh(q.seasonal_cap)}.</p>
{cover}
<h2>Price</h2>{_rows(price_rows)}
<div class="pays"><b>{theme.ksh(q.farmer_pays)} a season</b>{html.escape(how_to_pay)}</div>
<h2>How it pays</h2>
<p class="note" style="margin-top:0">No claim form and no farm visit: payouts follow the ward's soil moisture,
pasture greenness, rainfall and heat readings and go out by M-Pesa within 10 days of the season's end. On 2015-2024
weather this cover would have paid in {len(paid)} of {len(q.history)} {html.escape(qt.SEASON_WORDS[q.season])}
seasons.</p>
<div class="warn">Illustrative quotation: not a filed product and not for sale. Terms need actuarial sign-off, the
partner insurer's agreement and IRA approval. Insurer: Partner insurer (to be named). Calculating agent:
KilimoShield.</div>
<div class="sign"><div>SACCO officer: name, signature, date</div><div>Farmer: name, signature, date</div></div>
<p class="note" style="text-align:center;margin-top:28px">{html.escape(brand.APP_NAME)} {html.escape(brand.BYLINE)}</p>
</div></body></html>"""
