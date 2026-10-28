"""Tiny inline-SVG charts for the HTML report.

Inline SVG keeps the report a single offline file, follows the page's light/dark
theme through CSS variables, and gives every mark a native hover tooltip via
<title>. Colours are referenced by role (var(--series-N), var(--ink-2), ...);
the template defines them for both themes.

Mark conventions: 2px lines, dots of radius 4 with a 2px surface ring, bars with
a rounded data end and a 2px surface gap, recessive grid, one y-axis per chart.
"""
from __future__ import annotations

import math
from html import escape

W, H = 760, 300
PAD = {"l": 56, "r": 16, "t": 16, "b": 40}


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


class Plot:
    def __init__(self, x0, x1, y0, y1, width=W, height=H, label="", top_pad=0):
        self.w, self.h = width, height
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.top = PAD["t"] + top_pad
        self.parts: list[str] = []
        self.label = label

    def x(self, v):
        return PAD["l"] + (v - self.x0) / (self.x1 - self.x0) * (self.w - PAD["l"] - PAD["r"])

    def y(self, v):
        return self.h - PAD["b"] - (v - self.y0) / (self.y1 - self.y0) * (self.h - self.top - PAD["b"])

    def axes(self, yticks, yfmt, xticks, xfmt, ylabel="", xlabel=""):
        p = self.parts
        for t in yticks:
            p.append(f'<line class="grid" x1="{PAD["l"]}" x2="{self.w - PAD["r"]}" y1="{self.y(t):.1f}" y2="{self.y(t):.1f}"/>')
            p.append(f'<text class="tick" x="{PAD["l"] - 8}" y="{self.y(t) + 4:.1f}" text-anchor="end">{escape(yfmt(t))}</text>')
        base = self.y(self.y0)
        p.append(f'<line class="axis" x1="{PAD["l"]}" x2="{self.w - PAD["r"]}" y1="{base:.1f}" y2="{base:.1f}"/>')
        for t in xticks:
            p.append(f'<text class="tick" x="{self.x(t):.1f}" y="{base + 18:.1f}" text-anchor="middle">{escape(xfmt(t))}</text>')
        if ylabel:
            p.append(f'<text class="axis-label" transform="translate(14 {(self.top + base) / 2:.1f}) rotate(-90)" '
                     f'text-anchor="middle">{escape(ylabel)}</text>')
        if xlabel:
            p.append(f'<text class="axis-label" x="{(PAD["l"] + self.w - PAD["r"]) / 2:.1f}" y="{self.h - 4}" '
                     f'text-anchor="middle">{escape(xlabel)}</text>')

    def ref_lines(self, levels: list[tuple[str, float]], unit: str = "", fmt=lambda v: f"{v:g}"):
        """Dashed horizontal reference lines with right-aligned labels that never overlap."""
        prev = None
        for name, v in sorted(levels, key=lambda lv: -lv[1]):
            yy = self.y(v)
            ty = yy - 5 if prev is None or yy - 5 - prev >= 12 else prev + 12
            self.parts.append(f'<line class="ref" x1="{PAD["l"]}" x2="{self.w - PAD["r"]}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
            self.parts.append(f'<text class="ref-label" x="{self.w - PAD["r"] - 4}" y="{ty:.1f}" text-anchor="end">'
                              f'{escape(name)} {fmt(v)}{unit}</text>')
            prev = ty

    def svg(self) -> str:
        return (f'<svg class="chart" viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.label)}" '
                f'preserveAspectRatio="xMidYMid meet">{"".join(self.parts)}</svg>')


def _round_top_rect(x, y_top, w, y_bottom, r=4):
    """Rect whose top corners are rounded (the bar's data end)."""
    h = y_bottom - y_top
    r = max(0.0, min(r, w / 2, h))
    return (f"M{x:.1f},{y_bottom:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} V{y_bottom:.1f} Z")


def bars(years, values, color: str, label: str, tooltip, y_max: float | None = None,
         height: int = 220, accent=None) -> str:
    """One bar per season (shares of sum insured). `accent(i)` gives an alternative colour."""
    top = y_max if y_max is not None else max(0.1, max(values) * 1.1)
    yt = _nice_ticks(0, top, 4)
    p = Plot(-0.5, len(years) - 0.5, 0, max(top, yt[-1]), height=height, label=label)
    step = max(1, len(years) // 12)
    p.axes(yt, lambda v: f"{v:.0%}", list(range(0, len(years), step)), lambda i: str(years[int(i)]),
           ylabel="Payout")
    slot = p.x(1) - p.x(0)
    bw = slot * 0.7
    for i, v in enumerate(values):
        cx = p.x(i)
        if v > 0:
            fill = (accent(i) if accent else None) or color
            p.parts.append(f'<path d="{_round_top_rect(cx - bw / 2, p.y(v), bw, p.y(0))}" fill="{fill}" class="seg"/>')
        p.parts.append(f'<rect class="hit" x="{cx - slot / 2:.1f}" y="{p.top}" width="{slot:.1f}" '
                       f'height="{p.y(0) - p.top:.1f}"><title>{escape(tooltip(i))}</title></rect>')
    return p.svg()


def lines(series: dict[str, list[tuple[float, float]]], colors: dict[str, str], label: str,
          xfmt, yfmt, xlabel, ylabel, x_range=None, y_range=None, tooltip=None, xticks=None,
          bands: list[dict] | None = None, height: int = H) -> str:
    """Line chart; optional shaded x-bands {start, end, label} drawn behind the lines."""
    xs = [x for pts in series.values() for x, _ in pts]
    ys = [y for pts in series.values() for _, y in pts]
    x0, x1 = x_range or (min(xs), max(xs))
    y0, y1 = y_range or (0, max(ys) * 1.1 or 1)
    yt = _nice_ticks(y0, y1, 4)
    p = Plot(x0, x1, y0, max(y1, yt[-1]), height=height, label=label, top_pad=18 if bands else 0)
    for b in bands or []:
        a, z = p.x(b["start"]), p.x(b["end"])
        p.parts.append(f'<rect class="band-ins" x="{a:.1f}" y="{p.top}" width="{max(1, z - a):.1f}" '
                       f'height="{p.y(y0) - p.top:.1f}"><title>{escape(b.get("title", b["label"]))}</title></rect>')
        p.parts.append(f'<text class="band-label" x="{(a + z) / 2:.1f}" y="{p.top - 6}" text-anchor="middle">'
                       f'{escape(b["label"])}</text>')
    p.axes(yt, yfmt, xticks if xticks is not None else _nice_ticks(x0, x1, 6), xfmt, ylabel=ylabel, xlabel=xlabel)
    for name, pts in series.items():
        d = " ".join(f"{'M' if i == 0 else 'L'}{p.x(x):.1f},{p.y(y):.1f}" for i, (x, y) in enumerate(pts))
        p.parts.append(f'<path d="{d}" fill="none" stroke="{colors[name]}" class="line"/>')
        if tooltip:
            for x, y in pts:
                p.parts.append(f'<circle class="hit-dot" cx="{p.x(x):.1f}" cy="{p.y(y):.1f}" r="7">'
                               f'<title>{escape(tooltip(name, x, y))}</title></circle>')
    return p.svg()


def wrsi_dots(years, wrsi: list[float | None], trigger: float, exit_: float, label: str) -> str:
    """End-of-season WRSI per year with trigger and exit lines; failed onsets marked at the base."""
    p = Plot(min(years) - 1, max(years) + 1, 0, 100, label=label)
    p.axes([0, 25, 50, 75, 100], lambda v: f"{v:g}", _nice_ticks(min(years), max(years), 8),
           lambda v: f"{int(v)}", ylabel="End-of-season WRSI")
    p.ref_lines([("trigger", trigger), ("exit (crop failure)", exit_)])
    for yr, v in zip(years, wrsi):
        if v is None:
            x, y = p.x(yr), p.y(0)
            p.parts.append(f'<path class="onset-x" d="M{x - 5:.1f},{y - 11:.1f} L{x + 5:.1f},{y - 1:.1f} '
                           f'M{x + 5:.1f},{y - 11:.1f} L{x - 5:.1f},{y - 1:.1f}"><title>{yr}: failed onset '
                           f'(no start of season in the planting window)</title></path>')
            continue
        fill = "var(--series-2)" if v < trigger else "var(--series-1)"
        p.parts.append(f'<circle class="dot" cx="{p.x(yr):.1f}" cy="{p.y(v):.1f}" r="4" fill="{fill}">'
                       f'<title>{yr}: WRSI {v:.0f}{" (below trigger)" if v < trigger else ""}</title></circle>')
    return p.svg()


def prob_dots(years, probs: list[float], threshold: float, hot: list[bool], label: str, tips: list[str]) -> str:
    """Forecast probability per season with the trigger threshold; `hot` seasons drawn in series-2."""
    p = Plot(min(years) - 1, max(years) + 1, 0, 1, label=label)
    p.axes([0, 0.25, 0.5, 0.75, 1.0], lambda v: f"{v:.0%}", _nice_ticks(min(years), max(years), 8),
           lambda v: f"{int(v)}", ylabel="P(below-normal rain)")
    p.ref_lines([("voucher threshold", threshold), ("climatology", 1 / 3)], fmt=lambda v: f"{v:.0%}")
    for yr, v, h, tip in zip(years, probs, hot, tips):
        fill = "var(--series-2)" if h else "var(--series-1)"
        p.parts.append(f'<circle class="dot" cx="{p.x(yr):.1f}" cy="{p.y(v):.1f}" r="4" fill="{fill}">'
                       f'<title>{escape(tip)}</title></circle>')
    return p.svg()


def scatter_xy(points: list[dict], label: str, xlabel: str, ylabel: str, lo=0.0, hi=100.0) -> str:
    """Our WRSI (x) vs a reference WRSI (y) with the 1:1 line."""
    p = Plot(lo, hi, lo, hi, label=label)
    ticks = _nice_ticks(lo, hi, 4)
    p.axes(ticks, lambda v: f"{v:g}", ticks, lambda v: f"{v:g}", ylabel=ylabel, xlabel=xlabel)
    p.parts.append(f'<line class="ref" x1="{p.x(lo):.1f}" y1="{p.y(lo):.1f}" x2="{p.x(hi):.1f}" y2="{p.y(hi):.1f}"/>')
    for pt in points:
        p.parts.append(f'<circle class="dot" cx="{p.x(pt["x"]):.1f}" cy="{p.y(pt["y"]):.1f}" r="4" '
                       f'fill="var(--series-1)"><title>{escape(pt["tip"])}</title></circle>')
    return p.svg()
