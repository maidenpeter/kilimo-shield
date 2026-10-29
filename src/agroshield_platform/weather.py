"""Weather news and advisories (DISPLAY ONLY; never read by pricing, triggers or payouts).

    fetch()         polite fetch of enabled sources (config/weather.yaml): identifying User-Agent,
                    robots.txt checked on every run, the same URL at most once per min_interval_hours,
                    every request logged; new KMD county PDFs stored by SHA-256 with their validity dates
    upload()        manual PDF upload when fetching or parsing fails
    approve()       a person writes the English and Kiswahili summary and approves it; only then is it shown
    sms_blocked()   the reason an item may not go out by SMS (always, until written permission is on file)

There are no automatic sends anywhere in this module.
"""
from __future__ import annotations

import hashlib
import io
import re
import urllib.robotparser
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import audit
from .models import WeatherFetch, WeatherItem

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
_VALID = re.compile(r"valid[\s_-]+(\d{1,2})(?:st|nd|rd|th)?[\s_-]+([a-z]+)?[\s_-]*(?:(\d{4})[\s_-]+)?to[\s_-]+(\d{1,2})"
                    r"(?:st|nd|rd|th)?[\s_-]+([a-z]+)[\s_-]+(\d{4})", re.I)


class WeatherError(ValueError):
    pass


@dataclass
class Source:
    id: str
    name: str
    label: str
    kind: str
    enabled: bool
    listing_url: str
    display_allowed: bool
    sms_distribution_allowed: bool
    terms_checked_on: str
    note: str = ""
    county_slug: str = ""
    min_interval_hours: float = 6
    respect_robots: bool = True


def load_sources(config_dir: Path) -> tuple[dict, dict[str, Source]]:
    raw = yaml.safe_load((Path(config_dir) / "weather.yaml").read_text(encoding="utf-8"))
    return raw, {s["id"]: Source(**{k: v for k, v in s.items()}) for s in raw["sources"]}


def validity(text: str) -> tuple[date | None, date | None]:
    """'valid 27th October to 2nd November 2026' (or the file-name form with underscores)."""
    m = _VALID.search(text.replace("__", "_"))
    if not m:
        return None, None
    d0, mon0, y0, d1, mon1, y1 = m.groups()
    try:
        end = date(int(y1), MONTHS[mon1.lower()], int(d1))
        start_month = MONTHS[mon0.lower()] if mon0 else end.month
        start_year = int(y0) if y0 else (end.year - 1 if start_month > end.month else end.year)
        return date(start_year, start_month, int(d0)), end
    except (KeyError, ValueError):
        return None, None


def pdf_text(data: bytes, limit: int = 1500) -> str | None:
    try:
        from pypdf import PdfReader
        text = " ".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:2])
        return re.sub(r"\s+", " ", text).strip()[:limit] or None
    except Exception:
        return None


class Fetcher:
    def __init__(self, s: Session, raw: dict, store: Path, http: httpx.Client | None = None, now: datetime | None = None):
        self.s, self.store = s, store
        self.ua = raw["user_agent"]
        self.http = http or httpx.Client(timeout=60, headers={"User-Agent": self.ua}, follow_redirects=True)
        self.now = now or datetime.now(timezone.utc)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _log(self, src: Source, url: str, status: str, detail: str | None = None) -> None:
        self.s.add(WeatherFetch(source=src.id, url=url, status=status, detail=(detail or "")[:300] or None, at=self.now))

    def _recent(self, url: str, hours: float) -> bool:
        last = self.s.scalar(select(WeatherFetch).where(WeatherFetch.url == url, WeatherFetch.status.in_(("ok", "error")))
                             .order_by(WeatherFetch.at.desc()))
        if last is None:
            return False
        at = last.at if last.at.tzinfo else last.at.replace(tzinfo=timezone.utc)
        return self.now - at < timedelta(hours=hours)

    def _allowed(self, src: Source, url: str) -> bool:
        if not src.respect_robots:
            return True
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if root not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            r = self.http.get(root + "/robots.txt", headers={"User-Agent": self.ua})
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
                self.robots[root] = rp
            else:
                self.robots[root] = None          # no robots.txt: no declared rules (still polite)
        rp = self.robots[root]
        return rp is None or rp.can_fetch(self.ua, url)

    def get(self, src: Source, url: str) -> httpx.Response | None:
        if self._recent(url, src.min_interval_hours):
            self._log(src, url, "skipped_interval", f"fetched within {src.min_interval_hours:g} h")
            return None
        if not self._allowed(src, url):
            self._log(src, url, "disallowed", "robots.txt disallows this URL")
            return None
        try:
            r = self.http.get(url, headers={"User-Agent": self.ua})   # always identify ourselves
        except httpx.HTTPError as e:
            self._log(src, url, "error", type(e).__name__)
            return None
        self._log(src, url, "ok" if r.status_code == 200 else "error", f"HTTP {r.status_code}")
        return r if r.status_code == 200 else None

    def kmd_county(self, src: Source) -> list[WeatherItem]:
        listing = self.get(src, src.listing_url)
        if listing is None:
            return []
        pages = sorted({urljoin(src.listing_url, h) for h in re.findall(r'href="([^"]+)"', listing.text)
                        if src.county_slug in h.lower() and "forecast" in h.lower()})
        items = []
        for page_url in pages[:3]:
            page = self.get(src, page_url)
            if page is None:
                continue
            title_m = re.search(r"<title>(.*?)</title>", page.text, re.S)
            title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else page_url
            for href in sorted(set(re.findall(r'href="([^"]+\.pdf)"', page.text, re.I)))[:2]:
                pdf_url = urljoin(page_url, href)
                if self.s.scalar(select(WeatherItem).where(WeatherItem.url == pdf_url)):
                    continue
                pdf = self.get(src, pdf_url)
                if pdf is None:
                    continue
                items.append(store_pdf(self.s, self.store, src, pdf.content, title, pdf_url, "fetched"))
        return [i for i in items if i is not None]


def store_pdf(s: Session, store: Path, src: Source, data: bytes, title: str, url: str | None, origin: str,
              valid_from: date | None = None, valid_to: date | None = None) -> WeatherItem | None:
    if not data.startswith(b"%PDF"):
        raise WeatherError("not a PDF file")
    sha = hashlib.sha256(data).hexdigest()
    if s.scalar(select(WeatherItem).where(WeatherItem.pdf_sha256 == sha)):
        return None                                     # same document already held
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{sha}.pdf"
    path.write_bytes(data)
    v0, v1 = validity(title + " " + (url or ""))
    item = WeatherItem(source=src.id, source_label=src.label, title=title[:300], url=url, pdf_sha256=sha,
                       pdf_path=str(path), text_excerpt=pdf_text(data), valid_from=valid_from or v0,
                       valid_to=valid_to or v1, origin=origin)
    s.add(item)
    s.flush()
    audit(s, "weather", f"weather.{origin}", "weather_item", str(item.id), source=src.id, file_sha256=sha)
    return item


def fetch(s: Session, config_dir: Path, repo: Path, http: httpx.Client | None = None, now: datetime | None = None) -> dict:
    raw, sources = load_sources(config_dir)
    f = Fetcher(s, raw, repo / raw["store_dir"], http, now)
    out = {}
    for src in sources.values():
        if not src.enabled:
            out[src.id] = "off"                         # never contacted
            continue
        if src.kind != "kmd_county":
            out[src.id] = f"no fetcher for kind {src.kind}"
            continue
        out[src.id] = f"{len(f.kmd_county(src))} new"
    return out


def approve(s: Session, item: WeatherItem, summary_en: str, summary_sw: str, actor: str) -> WeatherItem:
    en, sw = (summary_en or "").strip(), (summary_sw or "").strip()
    if not en or not sw:
        raise WeatherError("write both the English and the Kiswahili summary before approving")
    if len(en) > 480 or len(sw) > 480:
        raise WeatherError("keep each summary under 480 characters")
    item.summary_en, item.summary_sw = en, sw
    item.status, item.approved_by, item.approved_at = "approved", actor, datetime.now(timezone.utc)
    audit(s, actor, "weather.approved", "weather_item", str(item.id), source=item.source,
          file_sha256=item.pdf_sha256 or "")
    return item


def visible_items(s: Session, today: date) -> list[WeatherItem]:
    """Approved items still valid today (an item with no end date is shown for 7 days)."""
    out = []
    for i in s.scalars(select(WeatherItem).where(WeatherItem.status == "approved").order_by(WeatherItem.created_at.desc())):
        end = i.valid_to or ((i.approved_at or i.created_at).date() + timedelta(days=7))
        if end >= today:
            out.append(i)
    return out


def sms_blocked(item: WeatherItem, sources: dict[str, Source]) -> str | None:
    """Why this item may not be sent by SMS, or None. Sending is always a person's action, never automatic."""
    src = sources.get(item.source)
    if src is None or not src.sms_distribution_allowed:
        return f"No SMS: we do not have written permission from {src.name if src else item.source} to send its content."
    if item.status != "approved":
        return "No SMS: the summary has not been approved."
    return None
