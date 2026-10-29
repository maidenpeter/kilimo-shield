"""QA crawl: every route, every role, four widths, light and dark.

Starts its own portal (port 8790) on a throwaway database seeded with the fictional demo,
then for each page records: a screenshot, axe-core violations, console errors, failed
requests, broken images, internal links that fail, horizontal scroll, navbar wrapping,
h1 count, heading order and (at 375 px) tap targets under 44 px.

    .venv/Scripts/python tools/qa/crawl.py before        # -> docs/overnight/before/ + before.json
    .venv/Scripts/python tools/qa/crawl.py after --widths 1440,375

Never follows external links (no outside contact): only same-origin URLs are checked.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
AXE = REPO / "tools" / "qa" / "node_modules" / "axe-core" / "axe.min.js"
PORT = 8790
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "demo-only-change-me"
ROLES = {"public": None, "officer": "demo-officer", "manager": "demo-manager", "underwriter": "demo-underwriter"}
WIDTHS = [1440, 1024, 768, 375]
SCHEMES = ["light", "dark"]

# Static routes per role; dynamic ones (a member page, a pricing report) are discovered from links.
ROUTES = {
    "public": ["/", "/crops", "/livestock", "/how-it-works", "/insurers", "/saccos", "/learn", "/faq", "/credits", "/demo",
               "/login"],
    "officer": ["/dashboard", "/enrol", "/quote", "/members", "/payouts", "/bulk", "/dev/mpesa"],
    "manager": ["/dashboard", "/enrol", "/quote", "/members", "/payouts", "/reports", "/import", "/weather", "/sms",
                "/dev/mpesa"],
    "underwriter": ["/uw", "/uw/triggers", "/uw/money", "/uw/bordereaux", "/uw/pricing", "/uw/reinsurer"],
}
DISCOVER = {"public": [r"^/learn/[a-z0-9-]+$"], "officer": [r"^/members/[0-9a-f]{32}$"], "manager": [r"^/members/[0-9a-f]{32}$"],
            "underwriter": [r"^/uw/runs/[^/]+/report\.html$"]}
SKIP_LINK = re.compile(r"^/(logout|export/|bulk/template|uw/bordereaux/.+\.zip|weather/\d+/pdf)")

PAGE_CHECKS = """() => {
  const vw = window.innerWidth, de = document.documentElement;
  const out = {scrollWidth: de.scrollWidth, innerWidth: vw, title: document.title};
  out.h1 = document.querySelectorAll('h1').length;
  const hs = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => +h.tagName[1]);
  out.headingSkips = hs.filter((l, i) => i > 0 && l > hs[i - 1] + 1).length;
  out.firstHeading = hs[0] || null;
  const header = document.querySelector('header.site, header.top');
  if (header) {
    const nav = header.querySelector('nav.primary, nav.main');
    const r = header.getBoundingClientRect();
    out.headerHeight = Math.round(r.height);
    if (nav && getComputedStyle(nav).display !== 'none' && nav.offsetParent) {
      // rows = items whose top differs by more than 12 px from every earlier row (small offsets are alignment, not wrapping)
      const tops = [...nav.querySelectorAll(':scope > a, :scope > details > summary, :scope > .dropdown > button')]
        .filter(a => a.offsetParent).map(a => a.getBoundingClientRect().top).sort((x, y) => x - y);
      const rows = []; tops.forEach(t => { if (!rows.some(r => Math.abs(r - t) <= 12)) rows.push(t); });
      out.navRows = rows.length;
      out.navOverflow = nav.scrollWidth > nav.clientWidth + 1;
    } else { out.navRows = 0; }
  }
  out.brokenImages = [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.currentSrc || i.src);
  out.imagesNoAlt = [...document.images].filter(i => !i.hasAttribute('alt')).map(i => i.src);
  out.links = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'));
  if (vw <= 400) {
    out.smallTargets = [...document.querySelectorAll('a, button, summary, input, select, textarea, label.check, .choice label')]
      .filter(e => e.offsetParent !== null && !e.closest('table') && !(e.tagName === 'A' && e.closest('p, li, td, .muted, .sub')))
      .map(e => ({tag: e.tagName, text: (e.textContent || e.name || e.type || '').trim().slice(0, 30), h: Math.round(e.getBoundingClientRect().height)}))
      .filter(x => x.h > 0 && x.h < 44 && !['INPUT'].includes(x.tag) || (x.tag === 'INPUT' && x.h > 0 && x.h < 24));
  }
  const overflow = [...document.querySelectorAll('main *')].filter(e => {
    const cs = getComputedStyle(e);
    return e.scrollWidth > e.clientWidth + 2 && cs.overflowX === 'visible' && e.clientWidth > 0 && !['TABLE','TBODY','TR','TD','TH','THEAD'].includes(e.tagName) && !(e instanceof SVGElement) && !e.closest('.table-wrap');
  }).slice(0, 5).map(e => e.tagName + '.' + ((e.className && e.className.baseVal !== undefined) ? e.className.baseVal : (e.className || '')).toString().slice(0, 30));
  out.overflowing = overflow;
  return out;
}"""


def start_server(log_path: Path) -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{(REPO / 'var' / 'qa.db').as_posix()}"}
    (REPO / "var" / "qa.db").unlink(missing_ok=True)
    exe = REPO / ".venv" / "Scripts" / "agroshield-portal.exe"
    subprocess.run([str(exe), "demo"], env=env, cwd=REPO, check=True, capture_output=True)
    subprocess.run([str(exe), "monitor"], env=env, cwd=REPO, check=True, capture_output=True)
    proc = subprocess.Popen([str(exe), "serve", "--port", str(PORT)], env=env, cwd=REPO,
                            stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(BASE + "/", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("portal did not start")


def slug(path: str) -> str:
    s = path.strip("/").replace("/", "_") or "home"
    s = re.sub(r"[0-9a-f]{32}", "id", s)
    return re.sub(r"[^A-Za-z0-9_.-]", "-", s)[:60]


def login(page, user: str) -> None:
    page.goto(BASE + "/login")
    page.fill("#username", user)
    page.fill("#password", PASSWORD)
    page.click("form.stack button[type=submit]")
    page.wait_for_load_state("networkidle")


def crawl(label: str, widths: list[int], schemes: list[str], roles: list[str], shots: bool) -> dict:
    out_dir = REPO / "docs" / "overnight" / label
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    server = start_server(REPO / "var" / f"qa-server-{label}.log")
    axe_src = AXE.read_text(encoding="utf-8")
    results, link_status = [], {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            for role in roles:
                # discover dynamic routes once per role
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                pg = ctx.new_page()
                if ROLES[role]:
                    login(pg, ROLES[role])
                routes = list(ROUTES[role])
                for path in list(routes):
                    pg.goto(BASE + path)
                    for href in pg.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"):
                        if any(re.match(rx, href or "") for rx in DISCOVER.get(role, [])) and href not in routes:
                            routes.append(href)
                            break
                # internal link check, with this role's session
                hrefs = set()
                for path in routes:
                    pg.goto(BASE + path)
                    hrefs |= {h.split("#")[0] for h in pg.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
                              if h and h.startswith("/") and not SKIP_LINK.match(h)}
                for h in sorted(hrefs):
                    key = (role, h)
                    if key not in link_status and h:
                        r = ctx.request.get(BASE + h, max_redirects=0, fail_on_status_code=False)
                        link_status[key] = r.status
                ctx.close()
                for width in widths:
                    for scheme in schemes:
                        ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 400 else 812},
                                                  color_scheme=scheme, device_scale_factor=1,
                                                  has_touch=width <= 400, is_mobile=width <= 400)
                        page = ctx.new_page()
                        console, failed = [], []
                        page.on("console", lambda m, c=console: c.append(m.text) if m.type == "error" else None)
                        page.on("requestfailed", lambda r, f=failed: f.append(f"{r.url} {r.failure}"))
                        page.on("response", lambda r, f=failed: f.append(f"{r.url} HTTP {r.status}") if r.status >= 400 else None)
                        if ROLES[role]:
                            login(page, ROLES[role])
                            console.clear(); failed.clear()
                        for path in routes:
                            console_before, failed_before = len(console), len(failed)
                            resp = page.goto(BASE + path, wait_until="networkidle")
                            status = resp.status if resp else None
                            checks = page.evaluate(PAGE_CHECKS)
                            page.add_script_tag(content=axe_src)
                            axe = page.evaluate("""async () => { const r = await axe.run(document, {resultTypes: ['violations']});
                                return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.length,
                                  sample: v.nodes.slice(0, 3).map(n => n.target.join(' '))})); }""")
                            name = f"{role}__{slug(path)}__{width}__{scheme}.jpg"
                            if shots:
                                # load lazy images first, so a full-page screenshot shows them
                                page.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) {
                                    window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); }
                                    await Promise.all([...document.images].map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; })));
                                    window.scrollTo(0, 0); }""")
                                page.screenshot(path=out_dir / name, full_page=True, type="jpeg", quality=70)
                            checks.pop("links", None)
                            results.append({"role": role, "path": path, "width": width, "scheme": scheme, "status": status,
                                            "screenshot": name if shots else None, **checks, "axe": axe,
                                            "console_errors": console[console_before:], "failed_requests": failed[failed_before:]})
                        ctx.close()
            browser.close()
    finally:
        server.terminate()
    data = {"label": label, "widths": widths, "schemes": schemes, "pages": results,
            "links": [{"role": r, "href": h, "status": s} for (r, h), s in sorted(link_status.items())]}
    (REPO / "docs" / "overnight" / f"{label}.json").write_text(json.dumps(data, indent=1), encoding="utf-8", newline="\n")
    return data


def summarise(data: dict) -> str:
    pages = data["pages"]
    lines = [f"# QA crawl: {data['label']}", "",
             f"{len({(p['role'], p['path']) for p in pages})} pages x {len(data['widths'])} widths x {len(data['schemes'])} schemes "
             f"= {len(pages)} page views.", ""]
    axe_by = defaultdict(lambda: {"impact": None, "help": "", "views": 0, "nodes": 0, "pages": set()})
    for p in pages:
        for v in p["axe"]:
            a = axe_by[v["id"]]
            a["impact"], a["help"] = v["impact"], v["help"]
            a["views"] += 1
            a["nodes"] += v["nodes"]
            a["pages"].add(f"{p['role']} {p['path']}")
    lines += ["## Accessibility (axe-core)", "", "| Rule | Impact | Views | Nodes | Pages |", "|---|---|---|---|---|"]
    order = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3, None: 4}
    for rid, a in sorted(axe_by.items(), key=lambda kv: (order[kv[1]["impact"]], -kv[1]["views"])):
        lines.append(f"| `{rid}` {a['help']} | {a['impact']} | {a['views']} | {a['nodes']} | {len(a['pages'])}: "
                     f"{', '.join(sorted(a['pages'])[:4])}{' ...' if len(a['pages']) > 4 else ''} |")
    def section(title, rows):
        lines.extend(["", f"## {title}", ""] + (rows or ["None."]))
    section("HTTP status not 200", [f"- {p['role']} {p['path']}: {p['status']}" for p in pages
                                    if p["status"] != 200 and p["width"] == data["widths"][0] and p["scheme"] == "light"])
    section("Horizontal scroll", sorted({f"- {p['role']} {p['path']} at {p['width']} px: {p['scrollWidth']} > {p['innerWidth']}"
                                         for p in pages if p["scrollWidth"] > p["innerWidth"]}))
    section("Navbar on more than one row", sorted({f"- {p['role']} {p['path']} at {p['width']} px: {p.get('navRows')} rows, header {p.get('headerHeight')} px"
                                                   for p in pages if (p.get("navRows") or 0) > 1}))
    section("h1 count not 1", sorted({f"- {p['role']} {p['path']}: {p['h1']}" for p in pages if p["h1"] != 1}))
    section("Heading levels skipped", sorted({f"- {p['role']} {p['path']}: {p['headingSkips']} skip(s)" for p in pages if p["headingSkips"]}))
    section("Console errors", sorted({f"- {p['role']} {p['path']}: {e[:160]}" for p in pages for e in p["console_errors"]}))
    section("Failed requests", sorted({f"- {p['role']} {p['path']}: {e[:160]}" for p in pages for e in p["failed_requests"]}))
    section("Broken images", sorted({f"- {p['role']} {p['path']}: {i}" for p in pages for i in p["brokenImages"]}))
    section("Images without alt", sorted({f"- {p['role']} {p['path']}: {i}" for p in pages for i in p["imagesNoAlt"]}))
    section("Internal links not 200 (303 redirects listed separately)",
            [f"- {l['role']} {l['href']}: {l['status']}" for l in data["links"] if l["status"] not in (200, 303)])
    section("Internal links that redirect", [f"- {l['role']} {l['href']}: {l['status']}" for l in data["links"] if l["status"] == 303])
    section("Tap targets under 44 px at 375 px", sorted({f"- {p['role']} {p['path']}: {t['tag']} '{t['text']}' {t['h']} px"
                                                          for p in pages for t in (p.get("smallTargets") or [])}))
    section("Elements overflowing their box", sorted({f"- {p['role']} {p['path']} at {p['width']}: {', '.join(p['overflowing'])}"
                                                       for p in pages if p.get("overflowing")}))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)))
    ap.add_argument("--schemes", default=",".join(SCHEMES))
    ap.add_argument("--roles", default=",".join(ROLES))
    ap.add_argument("--no-shots", action="store_true")
    a = ap.parse_args()
    data = crawl(a.label, [int(w) for w in a.widths.split(",")], a.schemes.split(","), a.roles.split(","), not a.no_shots)
    report = summarise(data)
    (REPO / "docs" / "overnight" / f"{a.label}-summary.md").write_text(report, encoding="utf-8", newline="\n")
    print(report[:6000])
