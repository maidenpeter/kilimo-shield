"""Build docs/remaining/index.html: the new and changed screens of the remaining brief at 375 and 1440 px, from the
final QA crawl (docs/remaining/qa-final.json and its screenshots, which stay local and are not committed).

    python tools/qa/remaining_page.py
"""
import html
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "remaining"

# (role, path pattern, what changed)
SCREENS = [
    ("farmer", r"^/app$", "Photo app: farms, growth stages, camera with the ghost of the last photo, offline queue (Phase 3)"),
    ("farmer", r"^/app/weather$", "Farmer weather tab: approved KMD summaries, English and Kiswahili, Source: KMD (Phase 3)"),
    ("farmer", r"^/app/consent$", "The separate AI photo check choice, pending legal review (Phase 3)"),
    ("farmer", r"^/app/damage$", "Picture-based rider damage report, ILLUSTRATIVE, development only (Phase 3)"),
    ("officer", r"^/dashboard$", "Officer Home: 'Payment not confirmed: check with the farmer' appears here when a payment is flagged (Phase 1)"),
    ("manager", r"^/reports$", "Manager Reports: flagged payments with Paid / Not paid, refunds owed and paid (Phase 1)"),
    ("manager", r"^/members/", "Member page: refunds paid, photo app set-up, champion farms, AI photo choice (Phases 1 and 3)"),
    ("manager", r"^/weather$", "Manager weather: own SACCO's advisories only (Phase 1)"),
    ("ops", r"^/weather$", "AgroShield operations: advisories shown to every SACCO (Phase 1)"),
    ("underwriter", r"^/uw/money$", "Money: settlement with refunds owed and paid, and the premium paybill (Phase 1)"),
    ("underwriter", r"^/uw/photos$", "Photo review queue with checks and suggestions (Phase 3)"),
    ("underwriter", r"^/uw/photos/PH-", "One photo: checks, suggestion, the reviewer's decision (Phase 3)"),
    ("underwriter", r"^/uw/devices$", "Devices: registry and health; data for checking only, never a payout (Phase 4)"),
    ("underwriter", r"^/uw/devices/.+", "One device: readings, photos with greenness, CHIRPS check (Phase 4)"),
]


def main() -> None:
    data = json.loads((OUT / "qa-final.json").read_text(encoding="utf-8"))
    pages = [p for p in data["pages"] if p["scheme"] == "light" and p["width"] in (375, 1440) and p.get("screenshot")]
    blocks = []
    for role, rx, what in SCREENS:
        hits = [p for p in pages if p["role"] == role and re.search(rx, p["path"])]
        if not hits:
            why = ("The demo database has no registered devices, so there is no device page to show. "
                   "tools/devices/simulate.py registers devices and fills this page." if "devices" in rx
                   else f"Not in the crawl ({role} {rx}).")
            blocks.append(f'<section><h2>{html.escape(what)}</h2><p class="muted">{html.escape(why)}</p></section>')
            continue
        path = hits[0]["path"]
        shots = {p["width"]: p["screenshot"] for p in hits if p["path"] == path}
        figs = "".join(
            f'<figure><figcaption>{w} px</figcaption><a href="qa-final/{html.escape(shots[w])}">'
            f'<img loading="lazy" src="qa-final/{html.escape(shots[w])}" alt="{html.escape(role)} {html.escape(path)} at {w} px"></a></figure>'
            for w in (375, 1440) if w in shots)
        blocks.append(f'<section><h2>{html.escape(what)}</h2><p class="muted">{html.escape(role)} &middot; '
                      f'<code>{html.escape(path)}</code></p><div class="pair">{figs}</div></section>')
    n = len({(p["role"], p["path"]) for p in data["pages"]})
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Remaining brief: new screens</title>
<style>
:root {{ --bg:#f7f8f6; --ink:#17201b; --muted:#5b665f; --line:#d9ded9; --card:#fff; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1512; --ink:#e7ece8; --muted:#9aa69f; --line:#2a332e; --card:#161d19; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:16px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }}
h1 {{ font-size:1.6rem; }} h2 {{ font-size:1.1rem; margin:0 0 4px; }}
.muted {{ color:var(--muted); margin:0 0 8px; }}
.pair {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,3fr); gap:16px; align-items:start; }}
@media (max-width:700px) {{ .pair {{ grid-template-columns:1fr; }} }}
figure {{ margin:0; }} figcaption {{ font-size:.85rem; color:var(--muted); }}
img {{ width:100%; height:auto; max-height:900px; object-fit:cover; object-position:top; border:1px solid var(--line); border-radius:6px; }}
</style></head><body><main>
<h1>Remaining brief: new and changed screens</h1>
<p class="muted">From the final QA crawl ({n} pages, {len(data['pages'])} views, light theme shown). Fictional demo data.
Click a picture for the full page. Report: <a href="REPORT.md">REPORT.md</a>; crawl summary: <a href="qa-final-summary.md">qa-final-summary.md</a>.</p>
{''.join(blocks)}
</main></body></html>
"""
    (OUT / "index.html").write_text(page, encoding="utf-8", newline="\n")
    print("index.html:", len(blocks), "sections")


if __name__ == "__main__":
    main()
