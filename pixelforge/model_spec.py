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


# --------------------------------------------------------------------- hull
def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges [start, end) of True runs in a 1-D boolean array."""
    out = []
    x = 0
    n = len(row)
    while x < n:
        if row[x]:
            s = x
            while x < n and row[x]:
                x += 1
            out.append((s, x))
        else:
            x += 1
    return out


def _mask(image: Image.Image) -> np.ndarray:
    a = np.asarray(image.convert("RGBA"))[..., 3] > 127
    ys, xs = np.nonzero(a)
    if len(ys) == 0:
        raise ValueError("view has no opaque pixels")
    return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def build_hull_spec(
    front: Image.Image,
    side: Image.Image,
    back: Image.Image | None = None,
    *,
    columns: int = 64,
    side_faces: str = "left",
    arm_depth_ratio: float = 1.4,
) -> dict:
    """Carve a voxel model from the front and side silhouettes (a visual hull).

    Every horizontal slice is the intersection of what the front view allows
    (x range) and what the side view allows (y range), rounded into ellipses
    per run so bodies, hoods and arms get round cross-sections instead of
    boxes.  ``side_faces`` says which way the side view looks ("left" = the
    character's front is on the image's left, as on most turnaround sheets).
    """
    f = _mask(front)
    s = _mask(side)
    b = _mask(back)[:, ::-1] if back is not None else None  # mirror: seen from behind
    h, w = f.shape
    rows = max(8, round(columns * h / w))
    cell = 1.0 / rows  # cubic voxels in units of height
    depth_cols = max(4, round((s.shape[1] / s.shape[0]) / cell))

    def shrink(mask, size):
        return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.BOX)) > 127

    F = shrink(f, (columns, rows))
    S = shrink(s, (depth_cols, rows))
    if side_faces == "right":
        S = S[:, ::-1]
    if b is not None:
        B = shrink(b, (columns, rows))
        F = F & (B | ~B.any(axis=1, keepdims=True))  # back view can only remove, never add
    vox = np.zeros((rows, depth_cols, columns), dtype=bool)  # z, y, x
    for z in range(rows):
        f_runs = _runs(F[z])
        s_runs = _runs(S[z])
        if not f_runs or not s_runs:
            continue
        widest = max(x1 - x0 for x0, x1 in f_runs)
        for x0, x1 in f_runs:
            cx, hw = (x0 + x1 - 1) / 2, max((x1 - x0) / 2, 0.5)
            for y0, y1 in s_runs:
                cy, hd = (y0 + y1 - 1) / 2, max((y1 - y0) / 2, 0.5)
                if x1 - x0 < widest * 0.6:  # a thin run (arm, chain) is not torso-deep
                    hd = min(hd, hw * arm_depth_ratio)
                xs = np.arange(x0, x1)
                ys = np.arange(max(y0, 0), min(y1, depth_cols))
                xn = ((xs - cx) / hw)[None, :]
                yn = ((ys - cy) / hd)[:, None]
                vox[z, ys[:, None], xs[None, :]] |= (xn**2 + yn**2) <= 1.0
    if not vox.any():
        raise ValueError("hull is empty; check that the side view faces the right way")
    packed = [["".join("1" if v else "0" for v in vox[z, y]) for y in range(depth_cols)] for z in range(rows)]
    return {
        "version": 2,
        "mode": "hull",
        "columns": int(columns),
        "rows": int(rows),
        "depth_columns": int(depth_cols),
        "aspect": float(w / h),
        "thickness": float(depth_cols / rows),
        "voxels": packed,
    }
