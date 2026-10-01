"""Split a Midjourney turnaround sheet into separate view cutouts.

The sheet is one image with several full-body views on a plain background.
We remove the background, find the separate blobs, merge blobs that overlap
horizontally (a lantern hanging beside a body is still that body), and sort
them left to right.  Names default to front / side / back for three views.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .cleanup import background_mask, border_color, defringe
from .color import rgb_to_oklab

DEFAULT_NAMES = {1: ["front"], 2: ["front", "back"], 3: ["front", "side", "back"], 4: ["front", "quarter", "side", "back"]}


@dataclass
class View:
    name: str
    image: Image.Image  # RGBA cutout
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in the sheet


def cutout(image: Image.Image, tolerance: float = 0.08) -> np.ndarray:
    """RGBA array with the flood-filled background made transparent."""
    rgb = np.asarray(image.convert("RGB"))
    lab = rgb_to_oklab(rgb)
    bg_color = border_color(lab)
    bg = background_mask(lab, tolerance, bg_color)
    alpha = defringe(np.where(bg, 0, 255).astype(np.uint8), lab, bg_color, tolerance)
    return np.dstack([rgb, alpha])


def _column_runs(alpha: np.ndarray, min_gap: int, min_width: int) -> list[tuple[int, int]]:
    """Ranges of columns containing opaque pixels, merged across small gaps."""
    cols = (alpha > 0).any(axis=0)
    runs: list[list[int]] = []
    x = 0
    while x < len(cols):
        if cols[x]:
            start = x
            while x < len(cols) and cols[x]:
                x += 1
            runs.append([start, x])
        else:
            x += 1
    merged: list[list[int]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if b - a >= min_width]


def split_sheet(
    image: Image.Image,
    *,
    names: list[str] | None = None,
    tolerance: float = 0.08,
    expected: int | None = None,
) -> list[View]:
    rgba = cutout(image, tolerance)
    alpha = rgba[..., 3]
    h, w = alpha.shape
    gap = max(4, w // 60)
    runs = _column_runs(alpha, gap, min_width=max(8, w // 40))
    if expected and len(runs) > expected:
        # keep the widest N runs (drops labels, stray marks)
        runs = sorted(sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:expected])
    labels = names or DEFAULT_NAMES.get(len(runs), [f"view{i+1}" for i in range(len(runs))])
    views: list[View] = []
    for (x0, x1), name in zip(runs, labels):
        strip = alpha[:, x0:x1]
        ys = np.nonzero(strip.any(axis=1))[0]
        if len(ys) == 0:
            continue
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        crop = rgba[y0:y1, x0:x1]
        views.append(View(name, Image.fromarray(np.ascontiguousarray(crop), "RGBA"), (x0, y0, x1, y1)))
    return views


def normalize_heights(views: list[View]) -> list[View]:
    """Scale every view to the tallest one's height (sheets often vary a bit)."""
    if not views:
        return views
    target = max(v.image.height for v in views)
    out = []
    for v in views:
        if v.image.height != target:
            s = target / v.image.height
            im = v.image.resize((max(1, round(v.image.width * s)), target), Image.LANCZOS)
            out.append(View(v.name, im, v.box))
        else:
            out.append(v)
    return out
