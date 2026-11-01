"""Greenness index of a sentinel camera photo (Pillow and numpy).

For every usable pixel the chromatic coordinates are r = R/(R+G+B), g = G/(R+G+B), b = B/(R+G+B). Then

    gcc             green chromatic coordinate: mean g over the image (about 0.33 for grey; higher is greener)
    exg             excess green: mean of 2g - r - b
    green_fraction  share of pixels with 2g - r - b above GREEN_EXG (pixels that look like plants)

Near-black and blown-out pixels carry no colour and are left out. These are relative indices: compare a camera with
itself over the season (same view, same hour), not one camera with another. The plant threshold is a DRAFT default.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

MAX_SIDE = 512             # analysed at this size: the mean barely changes, and a UXGA photo decodes fast
MAX_PIXELS = 25_000_000    # refuse anything bigger than any OV2640 frame (a decompression bomb guard)
GREEN_EXG = 0.10           # DRAFT: excess green above this counts as plant
DARK_SUM = 60              # R+G+B below this: too dark to read a colour
MIN_USABLE = 0.05          # at least 5% of the pixels must be usable


class PhotoError(ValueError):
    pass


def analyse(data: bytes) -> dict:
    """Width, height and the greenness indices of a JPEG. Raises PhotoError if it is not a usable JPEG photo."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "JPEG":
                raise PhotoError("not a JPEG photo")
            width, height = im.size
            if width * height > MAX_PIXELS:
                raise PhotoError("photo is too large")
            im.draft("RGB", (MAX_SIDE, MAX_SIDE))           # JPEG decodes straight to a smaller size
            rgb = im.convert("RGB")
            rgb.thumbnail((MAX_SIDE, MAX_SIDE))
            a = np.asarray(rgb, dtype=np.float64)
    except PhotoError:
        raise
    except Exception as e:                                   # truncated or corrupt file
        raise PhotoError("the photo could not be read") from e
    return {"width": width, "height": height, **indices(a)}


def indices(a: np.ndarray) -> dict:
    """Greenness of an RGB array (H x W x 3, values 0 to 255)."""
    total = a.sum(axis=2)
    usable = (total >= DARK_SUM) & ~(a >= 250).all(axis=2)
    if usable.mean() < MIN_USABLE:
        raise PhotoError("too dark to measure (night, or the lens is covered)")
    px = a[usable] / total[usable][:, None]
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    exg = 2 * g - r - b
    return {"gcc": round(float(g.mean()), 4), "exg": round(float(exg.mean()), 4),
            "green_fraction": round(float((exg > GREEN_EXG).mean()), 4)}
