"""Download the licence-checked Wikimedia Commons photos used on the public site and self-host them.

Each photo's licence and author were confirmed on its Commons file page (docs/overnight/phase_c_research.json,
an independent second check) before it was listed here. Output: static/img/<key>-<width>.webp and .jpg at
800 and 1600 px (never upscaled), plus static/img/credits.json used by the Credits page.

    .venv/Scripts/python tools/fetch_images.py
"""
from __future__ import annotations

import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "agroshield_platform" / "web" / "static" / "img"
UA = "AgroShield-site/0.1 (self-hosting licensed images; contact: mrnwanngari@gmail.com)"
WIDTHS = (800, 1600)

# key -> (Commons title, where it is used). Licence/author come from the checked research file.
USE = {
    "maize-mount-kenya": ("File:Maize on a Mount Kenya farm.jpg", "Home hero"),
    "maize-kuria": ("File:Maize Farming in Kuria East,Kenya.jpg", "Crops hero"),
    "maize-siaya": ("File:Maize growing in local areas in Siaya county.jpg", "How it works"),
    # farmer-shamba (USAID photo) removed on 30 Oct: it shows a donor's logo sign and names a private person.
    "women-farmers": ("File:African women farmers in Kenya.jpg", "Home, Crops"),
    "village-maize": ("File:CSIRO ScienceImage 4316 Equatorial rainforest is the backdrop to a village surrounded by a maize crop in Kenya Africa 1981.jpg", "For insurers"),
    "tea-kericho": ("File:Tea carpet plantation of Kericho highlands, in Kenya.jpg", "Home, highland farms"),
    "kericho-farms": ("File:Kericho, Kenya (4201348827).jpg", "Learn hub"),
    "camels-marsabit": ("File:Camels at Marsabit.jpg", "Livestock hero"),
    "camels-north-horr": ("File:Camels in North Horr.jpg", "Livestock"),
    "camels-isiolo-road": ("File:Camels on road in Kenya.jpg", "Home, livestock card"),
    "samburu-arid": ("File:Arid landscape with acacia tree, Samburu National Reserve, Kenya.jpg", "Livestock, dry rangeland"),
    "savannah-after-rains": ("File:Savannah after the rains (42855065331).jpg", "Livestock, green rangeland"),
    "dry-river-kitui": ("File:Dry river, Kitui County, Kenya.jpg", "Learn, basis risk"),
    "chasing-rain-mara": ("File:Chasing the rain, Masai Mara.jpg", "How it works, rainfall"),
    "women-sorting": ("File:African Women Sorting their produce after harvest.jpg", "For SACCOs"),
    "rainbow-samburu": ("File:Rainbow over Samburu National Reserve landscape, Kenya.jpg", "Request a demo"),
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def thumb_url(original: str, width: int) -> str:
    """upload.wikimedia.org/wikipedia/commons/a/ab/Name.jpg -> .../commons/thumb/a/ab/Name.jpg/<w>px-Name.jpg"""
    head, name = original.rsplit("/", 1)
    head = head.replace("/wikipedia/commons/", "/wikipedia/commons/thumb/")
    return f"{head}/{name}/{width}px-{name}"


def main() -> None:
    research = json.loads((REPO / "docs" / "overnight" / "phase_c_research.json").read_text(encoding="utf-8"))
    checked = {i["file_title"]: i for i in research["confirmedImages"]}
    OUT.mkdir(parents=True, exist_ok=True)
    credits = []
    cj = OUT / "credits.json"
    previous = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else []
    for key, (title, where) in USE.items():
        im = checked.get(title)
        if im is None:
            print(f"SKIP {key}: not in the confirmed list")
            continue
        old = next((c for c in previous if c["key"] == key), None)
        if old and all((OUT / f"{key}-{s['w']}.{ext}").exists() for s in old["sizes"] for ext in ("webp", "jpg")):
            credits.append(old)                                # already downloaded: no second request
            continue
        src_w = min(1920, im["width"])
        url = thumb_url(im["original_url"], src_w) if im["width"] > 1920 else im["original_url"]
        data = get(url)
        img = Image.open(io.BytesIO(data)).convert("RGB")
        made = []
        for w in WIDTHS:
            if w > img.width and w != WIDTHS[0]:
                continue
            ww = min(w, img.width)
            h = round(img.height * ww / img.width)
            r = img.resize((ww, h), Image.LANCZOS)
            r.save(OUT / f"{key}-{w}.webp", "WEBP", quality=76, method=6)
            r.save(OUT / f"{key}-{w}.jpg", "JPEG", quality=80, optimize=True, progressive=True)
            made.append({"width": ww, "height": h, "w": w})
        credits.append({"key": key, "title": title[5:], "file_page": im["file_page"], "author": im["author_text"],
                        "license": im["license_short"], "license_url": im["license_url"], "alt": im["alt_text"],
                        "location": im.get("location", ""), "used_on": where, "sizes": made,
                        "ratio": round(img.height / img.width, 4)})
        print(f"ok {key}: {img.width}x{img.height} from {url[:90]}")
        time.sleep(1.0)
    (OUT / "credits.json").write_text(json.dumps(credits, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
