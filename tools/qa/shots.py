"""Real screenshots of the underwriter workspace for the public "For insurers" page.

Runs the fictional demo (same throwaway portal as crawl.py), signs in as the demo underwriter and saves the top of
each page at 1440 px in light mode as static/img/shots/<key>-{800,1600}.{webp,jpg}, plus shots.json (alt text and
caption). Everything shown is fictional demo data, and the captions say so.

    .venv/Scripts/python tools/qa/shots.py
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from crawl import BASE, REPO, login, start_server  # noqa: E402

OUT = REPO / "src" / "agroshield_platform" / "web" / "static" / "img" / "shots"
SHOTS = {
    "shot-uw-portfolio": ("/uw", "Underwriter portfolio: policies, sums insured and premium by ward and SACCO",
                          "Portfolio and exposure by ward and SACCO"),
    "shot-uw-triggers": ("/uw/triggers", "Triggers and payouts: ward index status and payouts waiting for approval",
                         "Triggers and payouts, with approve or hold and the 10-day clock"),
    "shot-uw-money": ("/uw/money", "Money: premium collected, subsidy pending and payouts by status",
                      "Premium, subsidy and payout money in one place"),
    "shot-uw-bordereaux": ("/uw/bordereaux", "Bordereaux: monthly premium and claims files with checksums",
                           "Bordereaux with a manifest and checksum for each file"),
    "shot-uw-pricing": ("/uw/pricing", "Pricing runs and audit: every engine run with its config and data hashes",
                        "Pricing runs you can reproduce from the inputs"),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    proc = start_server(REPO / "var" / "shots-server.log")
    meta = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light", device_scale_factor=1)
            page = ctx.new_page()
            login(page, "demo-underwriter")
            for key, (path, alt, caption) in SHOTS.items():
                page.goto(BASE + path)
                page.wait_for_load_state("networkidle")
                img = Image.open(io.BytesIO(page.screenshot(full_page=False))).convert("RGB")
                sizes = []
                for w in (800, 1600):
                    ww = min(w, img.width)
                    r = img.resize((ww, round(img.height * ww / img.width)), Image.LANCZOS)
                    r.save(OUT / f"{key}-{w}.webp", "WEBP", quality=82, method=6)
                    r.save(OUT / f"{key}-{w}.jpg", "JPEG", quality=84, optimize=True, progressive=True)
                    sizes.append({"width": r.width, "height": r.height, "w": w})
                meta.append({"key": key, "kind": "screenshot", "path": path, "alt": alt + " (fictional demo data)",
                             "caption": caption, "sizes": sizes, "ratio": round(img.height / img.width, 4)})
                print("ok", key)
            b.close()
    finally:
        proc.kill()
    (OUT / "shots.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
