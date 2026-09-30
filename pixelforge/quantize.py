"""Map OKLab pixels onto a palette, optionally with dithering."""

from __future__ import annotations

import numpy as np

from .palette import Palette

DITHER_MODES = ("none", "bayer", "floyd")


def bayer_matrix(n: int = 4) -> np.ndarray:
    """Normalized ordered-dither threshold matrix in [-0.5, 0.5)."""
    m = np.array([[0, 2], [3, 1]])
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return (m + 0.5) / m.size - 0.5


def quantize(
    lab: np.ndarray,
    palette: Palette,
    *,
    dither: str = "none",
    strength: float = 1.0,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Return palette indices (h, w) for an OKLab image (h, w, 3).

    ``bayer``  : ordered dithering - the classic, stable, animation-friendly look.
                 Because the pattern is fixed in screen space it does not
                 "boil" between frames.
    ``floyd``  : error diffusion - smoother gradients, but noisy and unstable
                 across frames; best for single illustrations.
    ``strength``: 0..1+, scales dither spread relative to palette spacing.
    """
    if dither not in DITHER_MODES:
        raise ValueError(f"dither must be one of {DITHER_MODES}")
    if dither == "none" or strength <= 0:
        return palette.nearest(lab)
    if dither == "bayer":
        h, w = lab.shape[:2]
        m = bayer_matrix(4)
        thresh = np.tile(m, (h // 4 + 1, w // 4 + 1))[:h, :w]
        spread = palette.min_spacing() * strength
        jittered = lab.copy()
        jittered[..., 0] += thresh * spread
        return palette.nearest(jittered)
    return _floyd_steinberg(lab, palette, strength, mask)


def _floyd_steinberg(lab, palette: Palette, strength: float, mask) -> np.ndarray:
    h, w = lab.shape[:2]
    work = lab.astype(np.float64).copy()
    out = np.zeros((h, w), dtype=np.int32)
    pal = palette.lab
    for y in range(h):
        for x in range(w):
            old = work[y, x]
            idx = int(((pal - old) ** 2).sum(1).argmin())
            out[y, x] = idx
            if mask is not None and not mask[y, x]:
                continue
            err = (old - pal[idx]) * strength
            if x + 1 < w:
                work[y, x + 1] += err * (7 / 16)
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += err * (3 / 16)
                work[y + 1, x] += err * (5 / 16)
                if x + 1 < w:
                    work[y + 1, x + 1] += err * (1 / 16)
    return out
