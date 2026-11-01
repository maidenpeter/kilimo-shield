"""Ward soil water holding capacity from ISRIC SoilGrids 2.0.

What it computes
  Available water capacity (AWC) of the maize root zone, in mm, averaged over
  each ward's extraction polygon (the same box CHIRPS rainfall is averaged over).

      AWC = sum over soil layers of (theta_FC - theta_WP) x thickness_in_root_zone

  theta_FC  volumetric water content at field capacity, SoilGrids wv0033 (33 kPa).
            wv0010 (10 kPa) is kept as the wetter alternative definition.
  theta_WP  volumetric water content at wilting point, SoilGrids wv1500 (1500 kPa).
  Layers    the six SoilGrids standard depths (0-5, 5-15, 15-30, 30-60, 60-100,
            100-200 cm). A root zone that ends inside a layer takes the part of
            the layer above that depth.

Source and access
  ISRIC SoilGrids 2.0 (Poggio et al. 2021, SOIL 7:217-240) water retention
  layers, 250 m, CC BY 4.0, from ISRIC's open WCS at maps.isric.org. No account
  is needed. The raster is requested in its native Interrupted Goode Homolosine
  grid (an equal-area projection), so no resampling happens and each pixel
  counts equally in the polygon mean. wv* values are stored as integers in
  10^-3 cm3/cm3, so 350 means 0.350 cm3/cm3. (The ISRIC FAQ page that lists the
  units could not be reached on 2026-11-01; the scale is the only one that gives
  physically possible values: field capacity 0.29-0.36 at these wards.)

  Raw rasters are cached under data/raw/soil/soilgrids/<coverage>.tif, each with
  a .meta.json holding the request, retrieval time and SHA-256. The derived
  per-ward numbers go to data/soil/ward_awc.json.

Nothing here touches pricing directly: the chosen AWC is copied into
config/wards.yaml (soil_whc_mm) by a person, so a soil refresh never silently
changes a price.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

# SoilGrids 2.0 standard depth intervals (cm, top and bottom).
LAYERS: tuple[tuple[int, int], ...] = ((0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200))
LAYER_NAMES = tuple(f"{a}-{b}cm" for a, b in LAYERS)
# Mapped integer units of wv0010 / wv0033 / wv1500 are 10^-3 cm3/cm3.
WV_SCALE = 1000.0
# Mapped units of cfvo (coarse fragments) are cm3/dm3, i.e. 10^-3 of the volume.
CFVO_SCALE = 1000.0

WCS_URL = "https://maps.isric.org/mapserv"
SOILGRIDS_CRS_URI = "http://www.opengis.net/def/crs/EPSG/0/152160"
# Interrupted Goode Homolosine, the SoilGrids native grid (ISRIC's "EPSG:152160").
IGH_PROJ = "+proj=igh +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs"
# Grid of the native 250 m rasters: pixel edges sit at these origins + k x 250 m.
GRID_X0, GRID_Y0, GRID_RES = -19949750.0, 8361000.0, 250.0

PRIMARY_DEPTH_CM = 100       # maize root zone used for soil_whc_mm (see docs/pricing/soil-whc-comparison.md)
SENSITIVITY_DEPTHS_CM = (60, 100, 150)
PROPERTIES = ("wv0010", "wv0033", "wv1500")
STATS = ("mean", "Q0.05", "Q0.95")


# ------------------------------------------------------------------ the maths
def layer_overlap_cm(top: float, bottom: float, depth_cm: float) -> float:
    """Thickness of layer [top, bottom) that lies above depth_cm."""
    return max(0.0, min(bottom, depth_cm) - top)


def awc_mm(theta_fc: Sequence[float], theta_wp: Sequence[float], depth_cm: float,
           layers: Sequence[tuple[float, float]] = LAYERS,
           coarse_fraction: Sequence[float] | None = None) -> float:
    """Available water capacity (mm) of the top depth_cm of soil.

    theta_fc, theta_wp: volumetric water content per layer as fractions (cm3/cm3).
    coarse_fraction: optional stone volume per layer (0-1); water is only held in
    the fine earth, so each layer's AWC is scaled by (1 - coarse_fraction).
    A layer where wilting point exceeds field capacity contributes zero, never a
    negative amount.
    """
    if not (len(theta_fc) == len(theta_wp) == len(layers)):
        raise ValueError("theta_fc, theta_wp and layers must have one value per layer")
    if coarse_fraction is not None and len(coarse_fraction) != len(layers):
        raise ValueError("coarse_fraction must have one value per layer")
    if depth_cm <= 0:
        raise ValueError("depth_cm must be positive")
    if depth_cm > layers[-1][1]:
        raise ValueError(f"depth_cm {depth_cm} is below the deepest layer ({layers[-1][1]} cm)")
    total = 0.0
    for i, (top, bottom) in enumerate(layers):
        fc, wp = float(theta_fc[i]), float(theta_wp[i])
        for name, v in (("theta_fc", fc), ("theta_wp", wp)):
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} in layer {top}-{bottom} cm is {v}; expected a fraction 0-1")
        thick = layer_overlap_cm(top, bottom, depth_cm)
        if thick == 0:
            continue
        keep = 1.0 - (float(coarse_fraction[i]) if coarse_fraction is not None else 0.0)
        total += max(fc - wp, 0.0) * thick * 10.0 * keep     # cm of water -> mm
    return total


def awc_grid_mm(fc_layers: np.ndarray, wp_layers: np.ndarray, depth_cm: float,
                layers: Sequence[tuple[float, float]] = LAYERS) -> np.ndarray:
    """Per-pixel AWC (mm) from stacked layer grids, shape (n_layers, ...), as fractions."""
    out = np.zeros(fc_layers.shape[1:], dtype=float)
    for i, (top, bottom) in enumerate(layers):
        thick = layer_overlap_cm(top, bottom, depth_cm)
        if thick:
            out += np.clip(fc_layers[i] - wp_layers[i], 0.0, None) * thick * 10.0
    return out


# ------------------------------------------------------------- geometry
def ring_lonlat(geometry: dict) -> list[tuple[float, float]]:
    if geometry.get("type") != "Polygon":
        raise ValueError("only Polygon geometries are supported")
    return [(float(x), float(y)) for x, y in geometry["coordinates"][0]]


def native_bbox(geometries: Iterable[dict], margin_px: int = 2) -> tuple[float, float, float, float]:
    """Bounding box in the SoilGrids grid (xmin, ymin, xmax, ymax), snapped to pixel
    edges, covering every polygon plus margin_px pixels."""
    from rasterio.warp import transform
    xs, ys = [], []
    for g in geometries:
        ring = ring_lonlat(g)
        # densify each edge so the curved projected edges are covered
        for (x0, y0), (x1, y1) in zip(ring[:-1], ring[1:]):
            for t in np.linspace(0, 1, 11):
                xs.append(x0 + t * (x1 - x0))
                ys.append(y0 + t * (y1 - y0))
    px, py = transform("EPSG:4326", IGH_PROJ, xs, ys)
    xmin = GRID_X0 + (np.floor((min(px) - GRID_X0) / GRID_RES) - margin_px) * GRID_RES
    xmax = GRID_X0 + (np.ceil((max(px) - GRID_X0) / GRID_RES) + margin_px) * GRID_RES
    ymax = GRID_Y0 - (np.floor((GRID_Y0 - max(py)) / GRID_RES) - margin_px) * GRID_RES
    ymin = GRID_Y0 - (np.ceil((GRID_Y0 - min(py)) / GRID_RES) + margin_px) * GRID_RES
    return float(xmin), float(ymin), float(xmax), float(ymax)


def polygon_pixels(tif_path: str | Path, geometry: dict, scale: float) -> np.ndarray:
    """Values (divided by scale) of the pixels whose centre lies inside the polygon.

    Raises if the polygon is not fully inside the raster or has no valid pixel.
    """
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom
    with rasterio.open(tif_path) as src:
        geom = transform_geom("EPSG:4326", src.crs, geometry)
        data = src.read(1, masked=True)
        inside = ~geometry_mask([geom], out_shape=data.shape, transform=src.transform, invert=False)
        # every ring vertex must be inside the raster extent
        b = src.bounds
        for x, y in geom["coordinates"][0]:
            if not (b.left <= x <= b.right and b.bottom <= y <= b.top):
                raise ValueError(f"{tif_path} does not cover the whole polygon; re-fetch the soil rasters")
        vals = data[inside]
        nodata = src.nodata
    vals = np.ma.compressed(vals).astype(float)
    if nodata is not None:
        vals = vals[vals != nodata]
    vals = vals[vals > 0]          # SoilGrids uses 0 for no data over water and built-up areas
    if vals.size == 0:
        raise ValueError(f"no valid SoilGrids pixels inside the polygon in {tif_path}")
    return vals / scale


# ------------------------------------------------------------- download + cache
def coverage_id(prop: str, layer: str, stat: str) -> str:
    return f"{prop}_{layer}_{stat}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_coverage(cov: str, bbox: tuple[float, float, float, float], dest_dir: Path,
                   pause_s: float = 3.0, retries: int = 3, log=print) -> Path:
    """Download one SoilGrids coverage clipped to bbox (native grid) as GeoTIFF and
    write <cov>.meta.json beside it. One request at a time, with a pause after it."""
    prop = cov.split("_")[0]
    params = [("map", f"/map/{prop}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"),
              ("REQUEST", "GetCoverage"), ("COVERAGEID", cov), ("FORMAT", "image/tiff"),
              ("SUBSET", f"X({bbox[0]:.0f},{bbox[2]:.0f})"), ("SUBSET", f"Y({bbox[1]:.0f},{bbox[3]:.0f})"),
              ("SUBSETTINGCRS", SOILGRIDS_CRS_URI), ("OUTPUTCRS", SOILGRIDS_CRS_URI)]
    url = WCS_URL + "?" + urllib.parse.urlencode(params)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tif = dest_dir / f"{cov}.tif"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                body = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            if not body.startswith((b"II*\x00", b"MM\x00*")):
                raise RuntimeError(f"{cov}: server did not return a GeoTIFF ({ctype}): {body[:200]!r}")
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(10 * (attempt + 1))
    tif.write_bytes(body)
    meta = {
        "dataset": f"ISRIC SoilGrids 2.0, {cov}",
        "provider": "ISRIC World Soil Information (maps.isric.org WCS)",
        "licence": "CC BY 4.0",
        "request": {"url": WCS_URL, "params": [list(p) for p in params]},
        "bbox_native": list(bbox),
        "crs": "Interrupted Goode Homolosine (ISRIC EPSG:152160), 250 m",
        "mapped_units": "10^-3 cm3/cm3" if prop.startswith("wv") else "cm3/dm3",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": _sha256(tif),
    }
    (dest_dir / f"{cov}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", newline="\n")
    log(f"  {cov}: {len(body):,} bytes")
    time.sleep(pause_s)
    return tif


def all_coverages() -> list[str]:
    covs = [coverage_id(p, layer, s) for p in PROPERTIES for layer in LAYER_NAMES for s in STATS]
    covs += [coverage_id("cfvo", layer, "mean") for layer in LAYER_NAMES]
    return covs


def check_cached(raw_dir: Path, cov: str) -> Path:
    tif, meta = raw_dir / f"{cov}.tif", raw_dir / f"{cov}.meta.json"
    if not (tif.exists() and meta.exists()):
        raise FileNotFoundError(f"no cached SoilGrids raster {tif}; run `agroshield-price fetch-soil`")
    if _sha256(tif) != json.loads(meta.read_text())["sha256"]:
        raise ValueError(f"{tif} does not match its recorded SHA-256; the raw input was modified")
    return tif


def fetch_all(geometries: list[dict], raw_dir: Path, refresh: bool = False, log=print) -> list[Path]:
    bbox = native_bbox(geometries)
    out = []
    for cov in all_coverages():
        if not refresh:
            try:
                out.append(check_cached(raw_dir, cov))
                continue
            except (FileNotFoundError, ValueError):
                pass
        out.append(fetch_coverage(cov, bbox, raw_dir, log=log))
    return out


# ------------------------------------------------------------- per-ward summary
def _stack(raw_dir: Path, prop: str, stat: str, geometry: dict, scale: float) -> np.ndarray:
    return np.stack([polygon_pixels(check_cached(raw_dir, coverage_id(prop, layer, stat)), geometry, scale)
                     for layer in LAYER_NAMES])


def ward_awc(raw_dir: Path, geometry: dict) -> dict:
    """AWC summary for one polygon from the cached rasters."""
    fc33 = _stack(raw_dir, "wv0033", "mean", geometry, WV_SCALE)
    fc10 = _stack(raw_dir, "wv0010", "mean", geometry, WV_SCALE)
    wp = _stack(raw_dir, "wv1500", "mean", geometry, WV_SCALE)
    cf = _stack(raw_dir, "cfvo", "mean", geometry, CFVO_SCALE)
    if not (fc33.shape == fc10.shape == wp.shape == cf.shape):
        raise ValueError("SoilGrids layers do not have the same pixels inside the polygon")
    n = fc33.shape[1]
    layers = []
    for i, name in enumerate(LAYER_NAMES):
        row = {"layer": name, "wv0033_mean": round(float(fc33[i].mean()), 4),
               "wv0010_mean": round(float(fc10[i].mean()), 4), "wv1500_mean": round(float(wp[i].mean()), 4),
               "cfvo_mean": round(float(cf[i].mean()), 4)}
        for prop in PROPERTIES:
            for stat in ("Q0.05", "Q0.95"):
                v = polygon_pixels(check_cached(raw_dir, coverage_id(prop, name, stat)), geometry, WV_SCALE)
                row[f"{prop}_{stat}"] = round(float(v.mean()), 4)
        layers.append(row)

    def depth_block(depth: float) -> dict:
        grid = awc_grid_mm(fc33, wp, depth)
        mean_fc = fc33.mean(axis=1)
        mean_wp = wp.mean(axis=1)
        return {
            "depth_cm": depth,
            "awc_33kpa_mm": round(float(grid.mean()), 1),
            "awc_33kpa_of_polygon_means_mm": round(awc_mm(mean_fc, mean_wp, depth), 1),
            "awc_10kpa_mm": round(float(awc_grid_mm(fc10, wp, depth).mean()), 1),
            "awc_33kpa_less_stones_mm": round(awc_mm(mean_fc, mean_wp, depth, coarse_fraction=cf.mean(axis=1)), 1),
            "pixel_p10_mm": round(float(np.percentile(grid, 10)), 1),
            "pixel_p90_mm": round(float(np.percentile(grid, 90)), 1),
            "pixel_min_mm": round(float(grid.min()), 1),
            "pixel_max_mm": round(float(grid.max()), 1),
        }

    return {"pixels": int(n), "pixel_area_km2": GRID_RES ** 2 / 1e6,
            "layers": layers,
            "depths": {str(d): depth_block(d) for d in SENSITIVITY_DEPTHS_CM},
            "primary": depth_block(PRIMARY_DEPTH_CM)}
