"""Pixel-grid detection and grid-aligned downsampling.

AI generators (and upscaled screenshots) produce "fake" pixel art: every logical
pixel is a blurry, compressed, slightly irregular block of N x N real pixels.
To get a real, editable, animatable sprite we have to recover the logical grid
and sample one color per cell.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .color import rgb_to_oklab


# Score = fraction of comb teeth landing on real edges.  Upscaled pixel art
# scores ~0.8-1.0; painterly AI "pixel-style" renders with no consistent grid
# score ~0.4-0.55.  Below this we don't trust the detection.
MIN_CONFIDENCE = 0.65


@dataclass
class Grid:
    scale_x: float
    scale_y: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    confidence: float = 0.0

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        w = int((width - self.offset_x) // self.scale_x)
        h = int((height - self.offset_y) // self.scale_y)
        return max(w, 1), max(h, 1)


def _edge_strength(lab: np.ndarray, axis: int) -> np.ndarray:
    """Mean color change between neighbouring columns (axis=1) or rows (axis=0)."""
    d = np.sqrt((np.diff(lab, axis=axis) ** 2).sum(-1))
    return d.mean(axis=1 - axis)


def _best_period(strength: np.ndarray, min_scale: float, max_scale: float, step: float):
    """Find the period of the edge profile with a comb filter.

    For a candidate period ``s`` about one column in ``s`` is a pixel boundary,
    so only the strongest ``0.9/s`` of columns are kept as "edges" for that
    candidate.  The score is the fraction of the comb's teeth (``o + k*s``) that
    land on a kept edge: ~0.9 for the true period, ~0.45 for a multiple (half
    the teeth hit), ~0.5-0.6 for a sub-period, and small for anything else.
    Codec block edges (JPEG/WebP, 8 px) are weak and drop out of the kept set
    whenever real pixel edges exist.
    """
    n = len(strength)
    xs = np.arange(n)
    order = np.sort(strength)
    best_all = (0.0, 1.0, 0.0)  # score, period, offset
    for s in np.arange(min_scale, max_scale + 1e-9, step):
        if s * 4 > n:
            break
        keep = max(1, int(round(n * 0.9 / s)))
        thr = max(order[-keep], 0.02)
        profile = (strength >= thr).astype(float)
        for o in np.arange(0.0, s, 0.5):
            pos = np.arange(o, n - 1, s)
            score = float(np.interp(pos, xs, profile).mean())
            if score > best_all[0] + 1e-9:
                best_all = (score, float(s), float(o))
    score, s, o = best_all
    if score <= 0:
        return 1.0, 0.0, 0.0
    # the profile is of *differences*, so an edge at index i sits between
    # pixels i and i+1 -> cells start at o + 1
    return s, float((o + 1) % s), score


def detect_grid(
    rgb: np.ndarray, min_scale: float = 2.0, max_scale: float = 24.0, step: float = 0.125
) -> Grid:
    """Estimate the logical pixel size of fake/upscaled pixel art."""
    lab = rgb_to_oklab(rgb)
    sx, ox, cx = _best_period(_edge_strength(lab, 1), min_scale, max_scale, step)
    sy, oy, cy = _best_period(_edge_strength(lab, 0), min_scale, max_scale, step)
    # Pixel art is almost always square-pixel; if the axes disagree slightly,
    # trust the more confident one.
    if abs(sx - sy) / max(sx, sy) < 0.15:
        s = sx if cx >= cy else sy
        sx = sy = s
    else:
        # Disagreeing axes usually means one axis locked onto a multiple.
        sx = sy = min(sx, sy)
    return Grid(sx, sy, ox, oy, confidence=min(cx, cy))


def downsample(
    rgb: np.ndarray, grid: Grid, *, inner: float = 0.5, samples: int = 3
) -> np.ndarray:
    """Sample one color per grid cell -> float OKLab array (h, w, 3).

    Only the inner part of each cell is sampled (the borders are where blur and
    compression artifacts live) and the per-channel median is taken, which
    rejects stray noisy pixels.
    """
    height, width = rgb.shape[:2]
    out_w, out_h = grid.output_size(width, height)
    lab = rgb_to_oklab(rgb)

    t = (np.arange(samples) + 0.5) / samples  # 0..1 within the inner region
    t = 0.5 - inner / 2 + t * inner
    xs = grid.offset_x + (np.arange(out_w)[:, None] + t[None, :]) * grid.scale_x
    ys = grid.offset_y + (np.arange(out_h)[:, None] + t[None, :]) * grid.scale_y
    xs = np.clip(np.floor(xs).astype(int), 0, width - 1)  # (w, S)
    ys = np.clip(np.floor(ys).astype(int), 0, height - 1)  # (h, S)

    block = lab[ys[:, None, :, None], xs[None, :, None, :]]  # (h, w, S, S, 3)
    block = block.reshape(out_h, out_w, samples * samples, 3)
    return np.median(block, axis=2)


def resample_to_width(rgb: np.ndarray, target_width: int) -> tuple[np.ndarray, Grid]:
    """For real high-res art (renders, paintings): a uniform grid of a chosen size."""
    height, width = rgb.shape[:2]
    s = width / target_width
    grid = Grid(s, s, 0.0, 0.0, confidence=1.0)
    return downsample(rgb, grid, inner=0.8, samples=4), grid
