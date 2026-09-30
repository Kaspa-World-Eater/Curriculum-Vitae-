"""Color-space helpers.

All perceptual work (palette extraction, nearest-color lookup, dithering) happens
in OKLab, which is far closer to how humans judge color difference than RGB.
That matters a lot for dark art like the references: in RGB, the distance
between two near-black blues is tiny, so they collapse into one color; in OKLab
they stay distinct.
"""

from __future__ import annotations

import numpy as np

_M1 = np.array(
    [
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005],
    ]
)
_M2 = np.array(
    [
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660],
    ]
)
_M2_INV = np.array(
    [
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480],
    ]
)
_M1_INV = np.array(
    [
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034186147, 1.7076147010],
    ]
)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255.0), 0, 255).astype(np.uint8)


def rgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """uint8 RGB array (..., 3) -> float OKLab array (..., 3)."""
    lin = srgb_to_linear(rgb[..., :3])
    lms = np.cbrt(lin @ _M1.T)
    return lms @ _M2.T


def oklab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """float OKLab array (..., 3) -> uint8 RGB array (..., 3)."""
    lms = (np.asarray(lab, dtype=np.float64) @ _M2_INV.T) ** 3
    return linear_to_srgb(lms @ _M1_INV.T)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected RRGGBB hex color, got {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb) -> str:
    return "{:02x}{:02x}{:02x}".format(*(int(v) for v in rgb[:3]))
