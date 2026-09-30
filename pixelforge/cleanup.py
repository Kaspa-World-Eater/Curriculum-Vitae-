"""Post-processing that turns a quantized image into a usable game sprite:
background removal, orphan-pixel cleanup, outlines, cropping."""

from __future__ import annotations

import numpy as np

from .color import rgb_to_oklab

_N4 = ((0, 1), (0, -1), (1, 0), (-1, 0))
_N8 = _N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _shift(a: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    """Shift a 2-D (or 3-D) array, filling uncovered cells with ``fill``."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    ys = slice(max(dy, 0), h + min(dy, 0))
    xs = slice(max(dx, 0), w + min(dx, 0))
    yd = slice(max(-dy, 0), h + min(-dy, 0))
    xd = slice(max(-dx, 0), w + min(-dx, 0))
    out[ys, xs] = a[yd, xd]
    return out


def background_mask(
    lab: np.ndarray, tolerance: float = 0.03, background: np.ndarray | None = None
) -> np.ndarray:
    """Boolean mask of background pixels, flood-filled from the image border.

    Only pixels *connected to the border* and within ``tolerance`` (OKLab
    distance) of the background color are removed, so dark details inside the
    character survive even when they match the backdrop.
    """
    h, w = lab.shape[:2]
    if background is None:
        border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
        background = np.median(border, axis=0)
    candidate = np.sqrt(((lab - background) ** 2).sum(-1)) <= tolerance
    region = np.zeros((h, w), dtype=bool)
    region[0, :] = candidate[0, :]
    region[-1, :] = candidate[-1, :]
    region[:, 0] |= candidate[:, 0]
    region[:, -1] |= candidate[:, -1]
    while True:
        grown = region.copy()
        for dy, dx in _N4:
            grown |= _shift(region, dy, dx, False)
        grown &= candidate
        if (grown == region).all():
            return region
        region = grown


def remove_islands(alpha: np.ndarray, min_fraction: float = 0.02) -> np.ndarray:
    """Drop opaque blobs smaller than ``min_fraction`` of the largest blob.

    Background removal on noisy AI images leaves floating specks of "almost
    background" color; the character itself is (nearly) always the largest
    8-connected blob.
    """
    opaque = alpha > 0
    labels = np.zeros(alpha.shape, dtype=np.int32)
    sizes = [0]
    h, w = alpha.shape
    for y0, x0 in zip(*np.nonzero(opaque)):
        if labels[y0, x0]:
            continue
        lab = len(sizes)
        labels[y0, x0] = lab
        stack, size = [(y0, x0)], 0
        while stack:
            y, x = stack.pop()
            size += 1
            for dy, dx in _N8:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and opaque[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = lab
                    stack.append((ny, nx))
        sizes.append(size)
    if len(sizes) <= 2:
        return alpha
    sizes_arr = np.array(sizes)
    small = sizes_arr < max(sizes_arr) * min_fraction
    small[0] = False
    out = alpha.copy()
    out[small[labels]] = 0
    return out


def remove_orphans(indices: np.ndarray, alpha: np.ndarray, passes: int = 1) -> np.ndarray:
    """Replace isolated single pixels (all 4 neighbours agree on another color)."""
    idx = indices.copy()
    for _ in range(passes):
        neigh = [_shift(idx, dy, dx, -1) for dy, dx in _N4]
        n0 = neigh[0]
        same = np.all([n == n0 for n in neigh[1:]], axis=0)
        orphan = same & (n0 != idx) & (n0 >= 0) & (alpha > 0)
        idx[orphan] = n0[orphan]
    return idx


def remove_alpha_specks(alpha: np.ndarray, min_neighbors: int = 2) -> np.ndarray:
    """Drop opaque pixels with fewer than ``min_neighbors`` opaque 8-neighbours."""
    opaque = alpha > 0
    count = sum(_shift(opaque, dy, dx, False).astype(int) for dy, dx in _N8)
    out = alpha.copy()
    out[opaque & (count < min_neighbors)] = 0
    return out


def add_outline(rgba: np.ndarray, color, *, diagonal: bool = False, inner: bool = False) -> np.ndarray:
    """Draw a 1-px outline around the opaque silhouette.

    ``inner=False`` grows the sprite by drawing outside the silhouette (needs a
    1-px transparent margin, see :func:`pad`); ``inner=True`` recolors the
    silhouette's own edge pixels instead.
    """
    out = rgba.copy()
    opaque = rgba[..., 3] > 0
    neigh = _N8 if diagonal else _N4
    color = np.asarray(tuple(color)[:3] + (255,), dtype=np.uint8)
    if inner:
        edge = opaque & ~np.all([_shift(opaque, dy, dx, False) for dy, dx in neigh], axis=0)
    else:
        edge = ~opaque & np.any([_shift(opaque, dy, dx, False) for dy, dx in neigh], axis=0)
    out[edge] = color
    return out


def pad(rgba: np.ndarray, amount: int = 1) -> np.ndarray:
    return np.pad(rgba, ((amount, amount), (amount, amount), (0, 0)))


def crop_to_content(rgba: np.ndarray, margin: int = 1) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3])
    if len(ys) == 0:
        return rgba
    y0, y1 = max(ys.min() - margin, 0), min(ys.max() + 1 + margin, rgba.shape[0])
    x0, x1 = max(xs.min() - margin, 0), min(xs.max() + 1 + margin, rgba.shape[1])
    return rgba[y0:y1, x0:x1]


def darkest(colors: np.ndarray) -> np.ndarray:
    return colors[rgb_to_oklab(colors)[:, 0].argmin()]
