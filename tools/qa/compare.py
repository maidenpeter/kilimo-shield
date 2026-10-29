"""Before and after, side by side: docs/overnight/index.html from the two crawls (before.json, after.json).

Screenshots stay local (docs/overnight/before/ and after/ are gitignored), so the page links to them by relative path
and works when opened from the repository folder. Pages that only exist after the overnight work are shown alone.

    .venv/Scripts/python tools/qa/compare.py
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OV = REPO / "docs" / "overnight"


def load(label: str) -> dict:
    d = json.loads((OV / f"{label}.json").read_text(encoding="utf-8"))
    return {(v["role"], v["path"] if not v["path"].startswith("/members/") else "/members/<id>", v["width"], v["scheme"]): v
            for v in d["pages"]}


def issues(v: dict | None) -> str:
    if not v:
        return ""
    n = sum(a["nodes"] for a in v.get("axe", []))
    bits = [f"axe {len(v.get('axe', []))} rules / {n} nodes"] if v.get("axe") else ["axe clean"]
    if v.get("navRows", 0) > 1:
        bits.append(f"nav {v['navRows']} rows")
    if v.get("scrollWidth", 0) > v.get("innerWidth", 0):
        bits.append("horizontal scroll")
    if v.get("console_errors"):
        bits.append(f"{len(v['console_errors'])} console errors")
    if v.get("smallTargets"):
        bits.append(f"{len(v['smallTargets'])} small targets")
    return ", ".join(bits)


def main() -> None:
    before, after = load("before"), load("after")
    groups = defaultdict(list)
    for key in sorted(set(before) | set(after), key=lambda k: (k[0], k[1], -k[2], k[3])):
        groups[(key[0], key[1])].append(key)
    out = ["""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgroShield overnight: before and after</title>
<style>
:root { --bg:#F6F3EC; --ink:#1C1F26; --ink2:#4A4F5C; --line:#D9D3C7; --accent:#00695C; }
@media (prefers-color-scheme: dark) { :root { --bg:#0F1117; --ink:#ECEDEF; --ink2:#B6BAC4; --line:#2A2D36; --accent:#2DD4BF; } }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, sans-serif; }
main { max-width:1400px; margin:0 auto; padding:24px 16px 64px; }
nav.toc { columns: 3 220px; font-size:14px; } nav.toc a { color:var(--accent); }
details { border-top:1px solid var(--line); padding:8px 0; } summary { cursor:pointer; font-weight:700; min-height:32px; }
.row { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:12px 0 24px; }
.row figure { margin:0; } .row img { width:100%; height:auto; border:1px solid var(--line); border-radius:6px; background:#fff; }
.row figcaption { font-size:13px; color:var(--ink2); } .missing { padding:24px; border:1px dashed var(--line); border-radius:6px; color:var(--ink2); }
h3 { font-size:15px; margin:16px 0 4px; } @media (max-width: 700px) { .row { grid-template-columns:1fr; } }
</style></head><body><main>
<h1>AgroShield overnight: before and after</h1>
<p>Each view as crawled before the overnight work (left) and after it (right), by role, page, width and colour scheme.
Screenshots are local files in <code>docs/overnight/before/</code> and <code>docs/overnight/after/</code>. Fictional demo data.
See <a href="MORNING_REPORT.md">MORNING_REPORT.md</a> for the summary.</p>
<nav class="toc" aria-label="Pages">"""]
    for (role, path) in groups:
        out.append(f'<div><a href="#{html.escape(role + path)}">{html.escape(role)} {html.escape(path)}</a></div>')
    out.append("</nav>")
    for (role, path), keys in groups.items():
        out.append(f'<details id="{html.escape(role + path)}"><summary>{html.escape(role)} &middot; {html.escape(path)}</summary>')
        for key in keys:
            b, a = before.get(key), after.get(key)
            out.append(f"<h3>{key[2]} px, {key[3]}</h3><div class='row'>")
            for label, v in (("before", b), ("after", a)):
                if v and v.get("screenshot"):
                    out.append(f"<figure><img loading='lazy' src='{label}/{html.escape(v['screenshot'])}' alt='{label}: {html.escape(role)} {html.escape(path)} at {key[2]} px, {key[3]}'>"
                               f"<figcaption>{label}: {issues(v)}</figcaption></figure>")
                else:
                    out.append(f"<div class='missing'>{label}: {'page did not exist' if label == 'before' else 'not captured'}</div>")
            out.append("</div>")
        out.append("</details>")
    out.append("</main></body></html>")
    (OV / "index.html").write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"{len(groups)} pages, {len(set(before) | set(after))} views")


if __name__ == "__main__":
    main()
