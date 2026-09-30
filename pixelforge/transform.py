"""Palette-safe geometric transforms: flip, exact turns, and RotSprite rotation.

Rotating pixel art with a normal image tool gives a blurry, jagged mess and
introduces hundreds of in-between colors.  The classic fix (RotSprite, used by
Aseprite and most pixel editors) is:

1. upscale 8x with Scale2x three times (an edge-aware, color-preserving zoom),
2. rotate that big image with nearest-neighbour sampling,
3. shrink back down by taking, for each output pixel, the color that fills
   most of its 8x8 block.

Because Scale2x never invents colors and the final step takes a majority vote,
the result only ever contains the sprite's own palette.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image


def flip(rgba: np.ndarray, horizontal: bool = True) -> np.ndarray:
    return rgba[:, ::-1] if horizontal else rgba[::-1]


def turn(rgba: np.ndarray, quarter_turns: int) -> np.ndarray:
    """Exact 90-degree turns (positive = counter-clockwise)."""
    return np.rot90(rgba, quarter_turns % 4)


def scale2x(rgba: np.ndarray) -> np.ndarray:
    """Scale2x / EPX: 2x zoom that keeps edges sharp without adding colors."""
    h, w = rgba.shape[:2]
    p = np.pad(rgba, ((1, 1), (1, 1), (0, 0)), mode="edge")
    c = p[1:-1, 1:-1]
    a, b = p[:-2, 1:-1], p[1:-1, 2:]  # above, right
    cc, d = p[2:, 1:-1], p[1:-1, :-2]  # below, left

    def eq(x, y):
        return np.all(x == y, axis=-1)

    a_b, a_d, c_b, c_d = eq(a, b), eq(a, d), eq(cc, b), eq(cc, d)
    a_c, b_d = eq(a, cc), eq(b, d)
    plain = a_c | b_d

    out = np.empty((h * 2, w * 2, rgba.shape[2]), dtype=rgba.dtype)
    tl = np.where((a_d & ~plain)[..., None], a, c)
    tr = np.where((a_b & ~plain)[..., None], a, c)
    bl = np.where((c_d & ~plain)[..., None], cc, c)
    br = np.where((c_b & ~plain)[..., None], cc, c)
    out[0::2, 0::2], out[0::2, 1::2] = tl, tr
    out[1::2, 0::2], out[1::2, 1::2] = bl, br
    return out


def _majority_downscale(big: np.ndarray, factor: int) -> np.ndarray:
    """Shrink by ``factor`` picking the most common color in each block."""
    h, w = big.shape[0] // factor, big.shape[1] // factor
    blocks = big[: h * factor, : w * factor].reshape(h, factor, w, factor, 4)
    blocks = blocks.transpose(0, 2, 1, 3, 4).reshape(h, w, factor * factor, 4)
    # transparent pixels vote as one color regardless of their RGB
    blocks = blocks.copy()
    blocks[blocks[..., 3] == 0] = 0
    keys = (
        (blocks[..., 0].astype(np.int64) << 24)
        | (blocks[..., 1].astype(np.int64) << 16)
        | (blocks[..., 2].astype(np.int64) << 8)
        | blocks[..., 3].astype(np.int64)
    )
    out = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            vals, counts = np.unique(keys[y, x], return_counts=True)
            k = int(vals[counts.argmax()])
            out[y, x] = ((k >> 24) & 255, (k >> 16) & 255, (k >> 8) & 255, k & 255)
    return out


def rotate(rgba: np.ndarray, degrees: float, *, expand: bool = True, factor: int = 8) -> np.ndarray:
    """RotSprite-style rotation (counter-clockwise) that stays inside the palette."""
    rgba = np.asarray(rgba)
    if rgba.shape[-1] == 3:
        rgba = np.dstack([rgba, np.full(rgba.shape[:2], 255, np.uint8)])
    degrees = degrees % 360
    if degrees == 0:
        return rgba.copy()
    if degrees % 90 == 0:
        return turn(rgba, int(degrees // 90))

    big = rgba
    steps = int(round(math.log2(factor)))
    for _ in range(steps):
        big = scale2x(big)
    f = 2**steps
    # PIL rotates counter-clockwise for positive angles, matching np.rot90
    im = Image.fromarray(np.ascontiguousarray(big), "RGBA").rotate(
        degrees, resample=Image.NEAREST, expand=expand, fillcolor=(0, 0, 0, 0)
    )
    arr = np.asarray(im)
    # pad so the size is a multiple of f and the sprite stays centred
    ph, pw = (-arr.shape[0]) % f, (-arr.shape[1]) % f
    arr = np.pad(arr, ((ph // 2, ph - ph // 2), (pw // 2, pw - pw // 2), (0, 0)))
    return _majority_downscale(arr, f)


def spin_frames(rgba: np.ndarray, frames: int = 8, *, clockwise: bool = True) -> list[np.ndarray]:
    """``frames`` evenly spaced rotations, all on a common square canvas."""
    rgba = np.asarray(rgba)
    h, w = rgba.shape[:2]
    size = int(math.ceil(math.hypot(h, w))) + 2
    out = []
    for i in range(frames):
        angle = 360.0 * i / frames * (-1 if clockwise else 1)
        r = rotate(rgba, angle, expand=True)
        canvas = np.zeros((size, size, 4), dtype=np.uint8)
        y0, x0 = (size - r.shape[0]) // 2, (size - r.shape[1]) // 2
        canvas[y0 : y0 + r.shape[0], x0 : x0 + r.shape[1]] = r
        out.append(canvas)
    return out
