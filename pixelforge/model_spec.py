"""Turn a front-view cutout into a spec for an "inflated cutout" 3D model.

Blender's bundled Python has no Pillow, so all image work happens here and the
result is a small JSON file the Blender script turns into a mesh:

* ``grid``     - which cells of a WxH grid are inside the character's silhouette
* ``depth``    - per cell, how far it should bulge (0 at the edge, 1 in the middle),
                 computed from the distance to the nearest edge, so the body is
                 round where it is wide (torso, hood) and thin where it is narrow
                 (arms, lantern chain)
* ``thickness``- total front-to-back thickness relative to the height, taken from
                 the side view when there is one

This is the classic "inflate the silhouette" trick: crude up close, convincing
at sprite scale, and it needs no modelling skill at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


def _distance_to_edge(mask: np.ndarray) -> np.ndarray:
    """Chessboard-ish distance from each inside pixel to the nearest outside pixel."""
    h, w = mask.shape
    inf = h + w
    d = np.where(mask, inf, 0).astype(np.int32)
    # two-pass (forward/backward) chamfer distance transform
    for y in range(h):
        for x in range(w):
            if d[y, x] == 0:
                continue
            best = d[y, x]
            if y > 0:
                best = min(best, d[y - 1, x] + 1)
                if x > 0:
                    best = min(best, d[y - 1, x - 1] + 1)
                if x + 1 < w:
                    best = min(best, d[y - 1, x + 1] + 1)
            if x > 0:
                best = min(best, d[y, x - 1] + 1)
            d[y, x] = best
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if d[y, x] == 0:
                continue
            best = d[y, x]
            if y + 1 < h:
                best = min(best, d[y + 1, x] + 1)
                if x > 0:
                    best = min(best, d[y + 1, x - 1] + 1)
                if x + 1 < w:
                    best = min(best, d[y + 1, x + 1] + 1)
            if x + 1 < w:
                best = min(best, d[y, x + 1] + 1)
            d[y, x] = best
    return d


def build_spec(
    front: Image.Image,
    side: Image.Image | None = None,
    *,
    columns: int = 64,
    thickness: float | None = None,
    roundness: float = 0.5,
) -> dict:
    """Compute the model spec from RGBA cutouts. ``columns`` = grid resolution."""
    front = front.convert("RGBA")
    alpha = np.asarray(front)[..., 3] > 127
    ys, xs = np.nonzero(alpha)
    if len(ys) == 0:
        raise ValueError("front view has no opaque pixels")
    alpha = alpha[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = alpha.shape
    rows = max(8, round(columns * h / w))
    small = np.asarray(Image.fromarray(alpha.astype(np.uint8) * 255).resize((columns, rows), Image.BOX)) > 127
    # fill single-pixel holes so the grid stays solid
    d = _distance_to_edge(small)
    inside = d > 0
    if inside.any():
        # normalise per row-neighbourhood: local width decides local roundness
        depth = (d / max(d.max(), 1)) ** roundness
        depth = np.where(inside, depth, 0.0)
    else:
        depth = np.zeros_like(d, dtype=float)

    if thickness is None:
        if side is not None:
            sa = np.asarray(side.convert("RGBA"))[..., 3] > 127
            sy, sx = np.nonzero(sa)
            if len(sy):
                side_w = sx.max() - sx.min() + 1
                side_h = sy.max() - sy.min() + 1
                thickness = float(np.clip(side_w / side_h, 0.12, 0.6))
        if thickness is None:
            thickness = 0.28  # a typical standing figure: depth ~ 28% of height

    return {
        "version": 1,
        "columns": int(columns),
        "rows": int(rows),
        "aspect": float(w / h),  # width / height of the silhouette
        "thickness": float(thickness),
        "grid": ["".join("1" if v else "0" for v in row) for row in inside],
        "depth": [[round(float(v), 3) for v in row] for row in depth],
    }


def write_spec(spec: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, separators=(",", ":")) + "\n")
    return path
