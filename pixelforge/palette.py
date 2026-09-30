"""Palettes: extraction, nearest-color lookup, and file I/O (.hex, .gpl, .png)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .color import hex_to_rgb, oklab_to_rgb, rgb_to_hex, rgb_to_oklab


@dataclass
class Palette:
    colors: np.ndarray  # (N, 3) uint8 RGB

    def __post_init__(self) -> None:
        self.colors = np.asarray(self.colors, dtype=np.uint8).reshape(-1, 3)
        if len(self.colors) == 0:
            raise ValueError("palette is empty")
        self._lab = rgb_to_oklab(self.colors)

    def __len__(self) -> int:
        return len(self.colors)

    @property
    def lab(self) -> np.ndarray:
        return self._lab

    # ------------------------------------------------------------------ lookup
    def nearest(self, lab: np.ndarray, chunk: int = 65536) -> np.ndarray:
        """Index of the nearest palette color for each OKLab pixel (..., 3)."""
        flat = lab.reshape(-1, 3)
        out = np.empty(len(flat), dtype=np.int32)
        for start in range(0, len(flat), chunk):
            block = flat[start : start + chunk]
            d = ((block[:, None, :] - self._lab[None, :, :]) ** 2).sum(-1)
            out[start : start + chunk] = d.argmin(1)
        return out.reshape(lab.shape[:-1])

    def min_spacing(self) -> float:
        """Median distance from each color to its nearest neighbour (OKLab)."""
        if len(self) < 2:
            return 0.1
        d = np.sqrt(((self._lab[:, None] - self._lab[None]) ** 2).sum(-1))
        np.fill_diagonal(d, np.inf)
        return float(np.median(d.min(1)))

    def sorted_by_lightness(self) -> "Palette":
        return Palette(self.colors[np.argsort(self._lab[:, 0])])

    # ------------------------------------------------------------- extraction
    @classmethod
    def from_image(
        cls,
        image: Image.Image | np.ndarray,
        n_colors: int = 16,
        *,
        accent_boost: float = 0.5,
        iterations: int = 30,
        seed: int = 0,
    ) -> "Palette":
        """Extract a palette with weighted k-means in OKLab.

        Colors are first binned, and each bin is weighted by ``count ** accent_boost``.
        With ``accent_boost < 1`` rare-but-important accents (a lantern's glow, gold
        trim, a green flame) keep a cluster of their own instead of being swamped by
        the huge dark background.
        """
        rgb, alpha = _split_rgba(image)
        pixels = rgb.reshape(-1, 3)
        if alpha is not None:
            pixels = pixels[alpha.reshape(-1) > 127]
        if len(pixels) == 0:
            raise ValueError("image has no opaque pixels")

        binned = (pixels >> 2).astype(np.int32)
        keys = (binned[:, 0] << 12) | (binned[:, 1] << 6) | binned[:, 2]
        uniq, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
        # average true color of each bin
        sums = np.zeros((len(uniq), 3))
        np.add.at(sums, inverse, pixels.astype(np.float64))
        bin_rgb = np.rint(sums / counts[:, None]).astype(np.uint8)
        points = rgb_to_oklab(bin_rgb)
        weights = counts.astype(np.float64) ** accent_boost

        k = min(n_colors, len(points))
        centers = _weighted_kmeans(points, weights, k, iterations, seed)
        palette = cls(oklab_to_rgb(centers))
        # de-duplicate identical colors produced by rounding
        uniq_colors = np.unique(palette.colors, axis=0)
        return cls(uniq_colors).sorted_by_lightness()

    # -------------------------------------------------------------------- I/O
    @classmethod
    def load(cls, path: str | Path) -> "Palette":
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix in {".hex", ".txt"}:
            lines = [l.strip() for l in path.read_text().splitlines()]
            return cls([hex_to_rgb(l) for l in lines if l and not l.startswith(";")])
        if suffix == ".gpl":
            colors = []
            for line in path.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
                    colors.append([int(p) for p in parts[:3]])
            return cls(colors)
        if suffix in {".png", ".gif", ".bmp", ".webp"}:
            rgb, alpha = _split_rgba(Image.open(path))
            px = rgb.reshape(-1, 3)
            if alpha is not None:
                px = px[alpha.reshape(-1) > 127]
            _, idx = np.unique(px, axis=0, return_index=True)
            return cls(px[np.sort(idx)])
        raise ValueError(f"unsupported palette format: {path.suffix}")

    def save(self, path: str | Path, name: str | None = None) -> None:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".hex":
            path.write_text("\n".join(rgb_to_hex(c) for c in self.colors) + "\n")
        elif suffix == ".gpl":
            lines = ["GIMP Palette", f"Name: {name or path.stem}", "Columns: 8", "#"]
            lines += [f"{r:3d} {g:3d} {b:3d}\t{rgb_to_hex((r, g, b))}" for r, g, b in self.colors]
            path.write_text("\n".join(lines) + "\n")
        elif suffix == ".png":
            self.swatch(cell=1).save(path)
        else:
            raise ValueError(f"unsupported palette format: {path.suffix}")

    def swatch(self, cell: int = 16, columns: int = 8) -> Image.Image:
        n = len(self)
        cols = min(columns, n)
        rows = (n + cols - 1) // cols
        arr = np.zeros((rows, cols, 4), dtype=np.uint8)
        for i, c in enumerate(self.colors):
            arr[i // cols, i % cols, :3] = c
            arr[i // cols, i % cols, 3] = 255
        img = Image.fromarray(arr, "RGBA")
        return img.resize((cols * cell, rows * cell), Image.NEAREST) if cell > 1 else img


def _split_rgba(image: Image.Image | np.ndarray) -> tuple[np.ndarray, np.ndarray | None]:
    if isinstance(image, Image.Image):
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        arr = np.asarray(image.convert("RGBA" if has_alpha else "RGB"))
    else:
        arr = np.asarray(image)
    if arr.ndim == 3 and arr.shape[-1] == 4:
        return arr[..., :3], arr[..., 3]
    return arr[..., :3], None


def _weighted_kmeans(
    points: np.ndarray, weights: np.ndarray, k: int, iterations: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # k-means++ seeding
    probs = weights / weights.sum()
    centers = [points[rng.choice(len(points), p=probs)]]
    d2 = ((points - centers[0]) ** 2).sum(1)
    for _ in range(1, k):
        p = d2 * weights
        if p.sum() <= 0:
            break
        centers.append(points[rng.choice(len(points), p=p / p.sum())])
        d2 = np.minimum(d2, ((points - centers[-1]) ** 2).sum(1))
    centers = np.array(centers)

    for _ in range(iterations):
        d = ((points[:, None, :] - centers[None, :, :]) ** 2).sum(-1)
        labels = d.argmin(1)
        new = np.zeros_like(centers)
        wsum = np.bincount(labels, weights=weights, minlength=len(centers))
        for c in range(3):
            new[:, c] = np.bincount(labels, weights=weights * points[:, c], minlength=len(centers))
        empty = wsum == 0
        new[~empty] /= wsum[~empty, None]
        new[empty] = centers[empty]
        if np.allclose(new, centers, atol=1e-5):
            centers = new
            break
        centers = new
    return centers
