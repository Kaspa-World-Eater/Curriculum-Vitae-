"""The main pipeline: any image -> clean, palette-locked, game-ready sprite."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from . import cleanup
from .color import oklab_to_rgb
from .grid import MIN_CONFIDENCE, Grid, detect_grid, downsample
from .palette import Palette
from .quantize import quantize


@dataclass
class PixelateOptions:
    scale: float | str = "auto"  # "auto" or logical pixel size in source pixels
    max_size: int = 224  # fallback when auto-detection is not confident
    width: int | None = None  # force output width in sprite pixels
    height: int | None = None  # force output height in sprite pixels
    colors: int = 96
    palette: Palette | None = None
    dither: str = "none"
    dither_strength: float = 0.6
    remove_background: bool = False
    bg_tolerance: float = 0.03
    despeckle: bool = True
    outline: str | None = None  # None | "auto" | hex color
    outline_diagonal: bool = False
    crop: bool = False


@dataclass
class PixelateResult:
    image: Image.Image  # RGBA, sprite resolution
    indices: np.ndarray  # (h, w) palette indices, -1 = transparent
    palette: Palette
    grid: Grid
    notes: list[str] = field(default_factory=list)

    def preview(self, zoom: int = 4) -> Image.Image:
        return self.image.resize((self.image.width * zoom, self.image.height * zoom), Image.NEAREST)


def resolve_grid(rgb: np.ndarray, opts: PixelateOptions, notes: list[str]) -> Grid:
    h, w = rgb.shape[:2]
    if opts.width or opts.height:
        s = w / opts.width if opts.width else h / opts.height
        return Grid(s, s, 0.0, 0.0, 1.0)
    if opts.scale != "auto":
        s = float(opts.scale)
        return Grid(s, s, 0.0, 0.0, 1.0)
    grid = detect_grid(rgb)
    if grid.confidence >= MIN_CONFIDENCE:
        notes.append(f"detected grid: {grid.scale_x:g}px (confidence {grid.confidence:.2f})")
        return grid
    s = max(w, h) / opts.max_size
    notes.append(
        f"no reliable pixel grid (confidence {grid.confidence:.2f}); "
        f"resampling to fit {opts.max_size}px"
    )
    return Grid(s, s, 0.0, 0.0, grid.confidence)


def pixelate(image: Image.Image | str, opts: PixelateOptions | None = None) -> PixelateResult:
    opts = opts or PixelateOptions()
    if isinstance(image, str):
        image = Image.open(image)
    rgba_src = np.asarray(image.convert("RGBA"))
    rgb = rgba_src[..., :3]
    notes: list[str] = []

    grid = resolve_grid(rgb, opts, notes)
    inner = 0.5 if grid.scale_x >= 3 else 0.9
    lab = downsample(rgb, grid, inner=inner, samples=3 if grid.scale_x >= 3 else 2)
    h, w = lab.shape[:2]

    # alpha: keep source transparency, optionally flood-remove the background
    src_alpha = rgba_src[..., 3]
    alpha = np.full((h, w), 255, dtype=np.uint8)
    if (src_alpha < 255).any():
        ys = np.clip(((np.arange(h) + 0.5) * grid.scale_y + grid.offset_y).astype(int), 0, rgb.shape[0] - 1)
        xs = np.clip(((np.arange(w) + 0.5) * grid.scale_x + grid.offset_x).astype(int), 0, rgb.shape[1] - 1)
        alpha = np.where(src_alpha[ys[:, None], xs[None, :]] > 127, 255, 0).astype(np.uint8)
    if opts.remove_background:
        alpha[cleanup.background_mask(lab, opts.bg_tolerance)] = 0
        if opts.despeckle:
            alpha = cleanup.remove_alpha_specks(alpha)
            alpha = cleanup.remove_islands(alpha)

    palette = opts.palette
    if palette is None:
        opaque_rgb = oklab_to_rgb(lab)[alpha > 0]
        palette = Palette.from_image(opaque_rgb[None], n_colors=opts.colors)

    indices = quantize(lab, palette, dither=opts.dither, strength=opts.dither_strength, mask=alpha > 0)
    if opts.despeckle and opts.dither == "none":
        indices = cleanup.remove_orphans(indices, alpha)

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = palette.colors[indices]
    rgba[..., 3] = alpha

    if opts.outline:
        from .color import hex_to_rgb

        color = cleanup.darkest(palette.colors) if opts.outline == "auto" else hex_to_rgb(opts.outline)
        rgba = cleanup.add_outline(cleanup.pad(rgba), color, diagonal=opts.outline_diagonal)
        if opts.outline != "auto" and not (palette.colors == np.array(color)).all(1).any():
            palette = Palette(np.vstack([palette.colors, color]))
    if opts.crop:
        rgba = cleanup.crop_to_content(rgba)

    final_idx = _indices_for(rgba, palette)
    return PixelateResult(Image.fromarray(rgba, "RGBA"), final_idx, palette, grid, notes)


def _indices_for(rgba: np.ndarray, palette: Palette) -> np.ndarray:
    key = lambda c: (c[..., 0].astype(np.int64) << 16) | (c[..., 1].astype(np.int64) << 8) | c[..., 2]
    lookup = {int(k): i for i, k in enumerate(key(palette.colors))}
    k = key(rgba[..., :3])
    out = np.vectorize(lambda v: lookup.get(int(v), -1), otypes=[np.int32])(k)
    out[rgba[..., 3] == 0] = -1
    return out


def pixelate_frames(
    frames: list[Image.Image],
    opts: PixelateOptions | None = None,
    *,
    stabilize: float = 0.04,
) -> list[PixelateResult]:
    """Pixelate an animation (e.g. frames from a video model) consistently.

    * one palette shared by every frame (extracted jointly),
    * one grid shared by every frame (detected on the first frame),
    * temporal stabilization: a pixel whose color changed by less than
      ``stabilize`` (OKLab distance) keeps its previous-frame color, which kills
      most of the "boiling" that makes AI animations look wrong as pixel art.
    """
    opts = opts or PixelateOptions()
    if not frames:
        return []
    notes: list[str] = []
    first = np.asarray(frames[0].convert("RGB"))
    grid = resolve_grid(first, opts, notes)
    # Per-frame cropping would misalign frames, so it is never applied here.
    fixed = PixelateOptions(
        **{**opts.__dict__, "scale": grid.scale_x, "width": None, "height": None, "crop": False}
    )
    labs = [downsample(np.asarray(f.convert("RGB")), grid) for f in frames]
    if fixed.palette is None:
        stacked = np.concatenate([oklab_to_rgb(l).reshape(-1, 3) for l in labs])
        fixed.palette = Palette.from_image(stacked[None], n_colors=opts.colors)

    results = [pixelate(f, fixed) for f in frames]
    if stabilize > 0 and len(results) > 1:
        pad = 1 if fixed.outline else 0
        colors = fixed.palette.colors
        prev_idx = results[0].indices
        for t in range(1, len(results)):
            r = results[t]
            idx = r.indices.copy()
            h, w = labs[t].shape[:2]
            region = idx[pad : pad + h, pad : pad + w]
            prev_region = prev_idx[pad : pad + h, pad : pad + w]
            # compare the *source* colors, not the quantized ones: small drift
            # in the source is what flips pixels between two palette entries.
            drift = np.sqrt(((labs[t] - labs[t - 1]) ** 2).sum(-1))
            keep = (drift < stabilize) & (region >= 0) & (prev_region >= 0)
            if keep.any():
                region[keep] = prev_region[keep]
                arr = np.asarray(r.image).copy()
                sub = arr[pad : pad + h, pad : pad + w]
                sub[keep, :3] = colors[region[keep]]
                r.image = Image.fromarray(arr, "RGBA")
                r.indices = idx
            prev_idx = idx
    for r in results:
        r.notes = notes + r.notes
    if any("no reliable" in n for n in notes):
        warnings.warn(notes[0])
    return results
