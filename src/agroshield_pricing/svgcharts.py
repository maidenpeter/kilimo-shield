"""Tiny inline-SVG charts for the HTML report.

Inline SVG keeps the report a single offline file, follows the page's light/dark
theme through CSS variables, and gives every mark a native hover tooltip via
<title>. Colours are referenced by role (var(--series-N), var(--ink-2), ...);
the template defines them for both themes.

Mark conventions: 2px lines, dots of radius 4 with a 2px surface ring, stacked
bar segments separated by a 2px surface gap, rounded data-end on the top segment,
recessive grid, one y-axis per chart.
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
    def __init__(self, x0, x1, y0, y1, width=W, height=H, label=""):
        self.w, self.h = width, height
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.parts: list[str] = []
        self.label = label

    def x(self, v):
        return PAD["l"] + (v - self.x0) / (self.x1 - self.x0) * (self.w - PAD["l"] - PAD["r"])

    def y(self, v):
        return self.h - PAD["b"] - (v - self.y0) / (self.y1 - self.y0) * (self.h - PAD["t"] - PAD["b"])

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
            p.append(f'<text class="axis-label" transform="translate(14 {(PAD["t"] + base) / 2:.1f}) rotate(-90)" text-anchor="middle">{escape(ylabel)}</text>')
        if xlabel:
            p.append(f'<text class="axis-label" x="{(PAD["l"] + self.w - PAD["r"]) / 2:.1f}" y="{self.h - 4}" text-anchor="middle">{escape(xlabel)}</text>')

    def svg(self) -> str:
        return (f'<svg class="chart" viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.label)}" '
                f'preserveAspectRatio="xMidYMid meet">{"".join(self.parts)}</svg>')


def _round_top_rect(x, y_top, w, y_bottom, r=4):
    """Rect whose top corners are rounded (the bar's data end)."""
    h = y_bottom - y_top
    r = max(0.0, min(r, w / 2, h))
    return (f"M{x:.1f},{y_bottom:.1f} V{y_top + r:.1f} Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y_top:.1f} {x + w:.1f},{y_top + r:.1f} V{y_bottom:.1f} Z")


def stacked_bars(years, stacks: dict[str, list[float]], colors: dict[str, str], label: str,
                 tooltip) -> str:
    """Bars per year, stacked by component (shares of sum insured, 0-1)."""
    totals = [sum(s[i] for s in stacks.values()) for i in range(len(years))]
    top = max(0.1, max(totals) * 1.1)
    p = Plot(-0.5, len(years) - 0.5, 0, top, label=label)
    yt = _nice_ticks(0, top, 4)
    p.y1 = max(top, yt[-1])
    step = max(1, len(years) // 12)
    p.axes(yt, lambda v: f"{v:.0%}", list(range(0, len(years), step)), lambda i: str(years[int(i)]),
           ylabel="Payout, share of sum insured")
    bw = (p.x(1) - p.x(0)) * 0.7
    for i, yr in enumerate(years):
        cx = p.x(i)
        acc = 0.0
        names = [n for n in stacks if stacks[n][i] > 0]
        for j, name in enumerate(names):
            v = stacks[name][i]
            y_bot, y_top = p.y(acc), p.y(acc + v)
            if j == len(names) - 1:
                d = _round_top_rect(cx - bw / 2, y_top, bw, y_bot)
                p.parts.append(f'<path d="{d}" fill="{colors[name]}" class="seg"/>')
            else:
                p.parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{y_top:.1f}" width="{bw:.1f}" '
                               f'height="{max(0, y_bot - y_top):.1f}" fill="{colors[name]}" class="seg"/>')
            acc += v
        # Full-height hit target, larger than the mark, carries the tooltip.
        p.parts.append(f'<rect class="hit" x="{cx - (p.x(1) - p.x(0)) / 2:.1f}" y="{PAD["t"]}" '
                       f'width="{p.x(1) - p.x(0):.1f}" height="{p.y(0) - PAD["t"]:.1f}">'
                       f'<title>{escape(tooltip(i))}</title></rect>')
    return p.svg()


def dots_with_levels(years, values, levels: list[tuple[str, float]], label: str, unit="mm",
                     highlight=None, width=300, height=210) -> str:
    """One dot per season, with horizontal reference lines (trigger, exit).

    Sized for a small multiple: the viewBox matches the rendered size so text
    stays legible instead of being scaled down with the whole chart.
    """
    vmax = max(max(values), *(v for _, v in levels)) * 1.1 or 1
    p = Plot(min(years) - 1, max(years) + 1, 0, vmax, width=width, height=height, label=label)
    yt = _nice_ticks(0, vmax, 4)
    p.y1 = max(vmax, yt[-1])
    p.axes(yt, lambda v: f"{v:g}", _nice_ticks(min(years), max(years), 4), lambda v: f"{int(v)}",
           ylabel=f"Phase rainfall ({unit})")
    # Labels sit at the right edge; push the lower one down when the lines are close.
    prev_y = None
    for name, v in sorted(levels, key=lambda lv: -lv[1]):
        yy = p.y(v)
        ty = yy - 5 if prev_y is None or yy - 5 - prev_y >= 12 else prev_y + 12
        p.parts.append(f'<line class="ref" x1="{PAD["l"]}" x2="{p.w - PAD["r"]}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        p.parts.append(f'<text class="ref-label" x="{p.w - PAD["r"] - 4}" y="{ty:.1f}" text-anchor="end">'
                       f'{escape(name)} {v:g} {unit}</text>')
        prev_y = ty
    for yr, v in zip(years, values):
        hot = highlight(v) if highlight else False
        fill = "var(--series-2)" if hot else "var(--series-1)"
        p.parts.append(f'<circle class="dot" cx="{p.x(yr):.1f}" cy="{p.y(v):.1f}" r="4" fill="{fill}">'
                       f'<title>{yr}: {v:.0f} {unit}</title></circle>')
    return p.svg()


def lines(series: dict[str, list[tuple[float, float]]], colors: dict[str, str], label: str,
          xfmt, yfmt, xlabel, ylabel, x_range=None, y_range=None, tooltip=None) -> str:
    xs = [x for pts in series.values() for x, _ in pts]
    ys = [y for pts in series.values() for _, y in pts]
    x0, x1 = x_range or (min(xs), max(xs))
    y0, y1 = y_range or (0, max(ys) * 1.1 or 1)
    p = Plot(x0, x1, y0, y1, label=label)
    yt = _nice_ticks(y0, y1, 4)
    p.y1 = max(y1, yt[-1])
    p.axes(yt, yfmt, _nice_ticks(x0, x1, 6), xfmt, ylabel=ylabel, xlabel=xlabel)
    for name, pts in series.items():
        d = " ".join(f"{'M' if i == 0 else 'L'}{p.x(x):.1f},{p.y(y):.1f}" for i, (x, y) in enumerate(pts))
        p.parts.append(f'<path d="{d}" fill="none" stroke="{colors[name]}" class="line"/>')
        if tooltip:
            for x, y in pts:
                p.parts.append(f'<circle class="hit-dot" cx="{p.x(x):.1f}" cy="{p.y(y):.1f}" r="7">'
                               f'<title>{escape(tooltip(name, x, y))}</title></circle>')
    return p.svg()


def band_line(xs, ys, bands: list[dict], label: str, xticks, xfmt, xlabel, ylabel) -> str:
    """A single line (e.g. climatology) over shaded x-bands (crop phases).

    bands: {start, end, group, short, name, insured}. Each group (season) gets one
    label across its span; each band gets its short label when there is room.
    """
    p = Plot(min(xs), max(xs), 0, max(ys) * 1.1 or 1, label=label)
    yt = _nice_ticks(0, p.y1, 4)
    p.y1 = max(p.y1, yt[-1])
    plot_top = PAD["t"] + 34  # two label rows above the plot area
    p.y = lambda v: p.h - PAD["b"] - (v - p.y0) / (p.y1 - p.y0) * (p.h - plot_top - PAD["b"])
    groups: dict[str, list[float]] = {}
    for bnd in bands:
        x0, x1 = p.x(bnd["start"]), p.x(bnd["end"] + 1)
        cls = "band-ins" if bnd["insured"] else "band"
        p.parts.append(f'<rect class="{cls}" x="{x0:.1f}" y="{plot_top}" width="{max(1, x1 - x0):.1f}" '
                       f'height="{p.y(0) - plot_top:.1f}"><title>{escape(bnd["name"])}</title></rect>')
        if x1 - x0 >= 18:
            p.parts.append(f'<text class="band-label" x="{(x0 + x1) / 2:.1f}" y="{plot_top - 6}" '
                           f'text-anchor="middle">{escape(bnd["short"])}</text>')
        groups.setdefault(bnd["group"], []).extend([x0, x1])
    for name, span in groups.items():
        a, b = min(span), max(span)
        p.parts.append(f'<text class="axis-label" x="{(a + b) / 2:.1f}" y="{PAD["t"] + 4}" '
                       f'text-anchor="middle">{escape(name)}</text>')
    p.axes(yt, lambda v: f"{v:g}", xticks, xfmt, ylabel=ylabel, xlabel=xlabel)
    d = " ".join(f"{'M' if i == 0 else 'L'}{p.x(x):.1f},{p.y(y):.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    p.parts.append(f'<path d="{d}" fill="none" stroke="var(--series-1)" class="line"/>')
    return p.svg()


def scatter(points: list[dict], classes: dict[str, tuple[str, str]], x_line: float, y_line: float,
            label: str) -> str:
    """Payout (x) vs yield (y); points carry `cls` keyed into classes -> (colour, legend)."""
    xmax = max(0.1, max(pt["x"] for pt in points) * 1.1)
    ymax = max(pt["y"] for pt in points) * 1.1
    p = Plot(0, xmax, 0, ymax, label=label)
    yt = _nice_ticks(0, ymax, 4)
    p.y1 = max(ymax, yt[-1])
    xt = _nice_ticks(0, xmax, 5)
    p.x1 = max(xmax, xt[-1])
    p.axes(yt, lambda v: f"{v:g}", xt, lambda v: f"{v:.0%}",
           ylabel="Yield (t/ha), SYNTHETIC", xlabel="Index payout, share of sum insured")
    p.parts.append(f'<line class="ref" x1="{p.x(x_line):.1f}" x2="{p.x(x_line):.1f}" y1="{PAD["t"]}" y2="{p.y(0):.1f}"/>')
    p.parts.append(f'<line class="ref" x1="{PAD["l"]}" x2="{p.w - PAD["r"]}" y1="{p.y(y_line):.1f}" y2="{p.y(y_line):.1f}"/>')
    p.parts.append(f'<text class="ref-label" x="{p.w - PAD["r"] - 4}" y="{p.y(y_line) - 5:.1f}" text-anchor="end">bad-season cutoff</text>')
    for pt in points:
        color, _ = classes[pt["cls"]]
        p.parts.append(f'<circle class="dot" cx="{p.x(pt["x"]):.1f}" cy="{p.y(pt["y"]):.1f}" r="4" fill="{color}">'
                       f'<title>{escape(pt["tip"])}</title></circle>')
    return p.svg()
