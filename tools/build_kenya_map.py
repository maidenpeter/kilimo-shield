"""Build assets/kenya_counties.geojson, the county outlines behind the chapter 1 risk map.

Source: geoBoundaries gbOpen KEN ADM1 (47 counties, RCMRD GeoPortal), public domain:
https://www.geoboundaries.org/api/current/gbOpen/KEN/ADM1/ -> "simplifiedGeometryGeoJSON".

    python tools/build_kenya_map.py path/to/geoBoundaries-KEN-ADM1_simplified.geojson

The outlines are simplified further (Douglas-Peucker, about 1 km) and rounded to 0.001 degrees, so the file stays
small enough to send to the browser on every rerun. The map needs no tiles and no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "kenya_counties.geojson"
TOLERANCE = 0.01  # degrees, about 1.1 km at the equator


def _distance(p, a, b) -> float:
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return ((x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2) ** 0.5


def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker, iterative so long rings cannot hit the recursion limit."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best, index = 0.0, None
        for i in range(first + 1, last):
            d = _distance(points[i], points[first], points[last])
            if d > best:
                best, index = d, i
        if index is not None and best > tolerance:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep) if k]


def ring(points: list) -> list | None:
    out = []
    for x, y in simplify(points, TOLERANCE):
        p = [round(x, 3), round(y, 3)]
        if not out or p != out[-1]:
            out.append(p)
    if out and out[0] != out[-1]:
        out.append(out[0])
    return out if len(out) >= 4 else None


def main(source: str) -> None:
    raw = json.loads(Path(source).read_text(encoding="utf-8"))
    features = []
    for f in raw["features"]:
        geom = f["geometry"]
        polygons = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        kept = []
        for polygon in polygons:
            rings = [ring(r) for r in polygon]
            if rings[0]:  # an outer ring that simplified away was a speck of an island
                kept.append([r for r in rings if r])
        features.append({"type": "Feature",
                         "properties": {"name": f["properties"]["shapeName"], "iso": f["properties"]["shapeISO"]},
                         "geometry": {"type": "MultiPolygon", "coordinates": kept}})
    features.sort(key=lambda f: f["properties"]["name"])
    OUT.write_text(json.dumps({"type": "FeatureCollection", "source": "geoBoundaries gbOpen KEN ADM1 (RCMRD), "
                               "public domain", "features": features}, separators=(",", ":")), encoding="utf-8")
    vertices = sum(len(r) for f in features for p in f["geometry"]["coordinates"] for r in p)
    print(f"{OUT}: {len(features)} counties, {vertices:,} vertices, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1])
