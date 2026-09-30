"""Procedural, palette-locked animation from a single still sprite.

Hand-animating every frame is the expensive part of pixel art.  A surprising
amount of "life" can be added procedurally instead - the same tricks used in
many 16-bit games:

* **sway**     - rows (or columns) displaced by a travelling sine wave: capes,
                 hair, banners, grass, flames, smoke.
* **breathe**  - the upper body drops 1px and comes back: idle breathing.
* **bob**      - the whole sprite floats: ghosts, hovering enemies.
* **flicker**  - bright pixels pulse lighter/darker *within the palette*:
                 lanterns, torches, magic, eyes.

Every effect only moves existing pixels or swaps them for other palette colors,
so frames never introduce new colors or blur - they stay real pixel art.
Effects are composable and each can be restricted to a box of the sprite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .color import rgb_to_oklab
from .palette import Palette

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the sprite


@dataclass
class Context:
    """Where the original sprite sits inside the (padded) animation canvas."""

    x0: int
    y0: int
    width: int
    height: int
    palette: Palette
    transparent: bool

    def box_px(self, box: Box) -> tuple[int, int, int, int]:
        bx0, by0, bx1, by1 = box
        x0 = self.x0 + int(round(bx0 * self.width))
        x1 = self.x0 + int(round(bx1 * self.width))
        y0 = self.y0 + int(round(by0 * self.height))
        y1 = self.y0 + int(round(by1 * self.height))
        if self.transparent:  # a cutout may move into the padding
            pad_l, pad_t = self.x0, self.y0
            x0 -= pad_l if bx0 <= 0 else 0
            y0 -= pad_t if by0 <= 0 else 0
            x1 += pad_l if bx1 >= 1 else 0
            y1 += pad_t if by1 >= 1 else 0
        return x0, y0, x1, y1


def _sample(src: np.ndarray, sy: np.ndarray, sx: np.ndarray, transparent: bool) -> np.ndarray:
    h, w = src.shape[:2]
    inside = (sy >= 0) & (sy < h) & (sx >= 0) & (sx < w)
    out = src[np.clip(sy, 0, h - 1), np.clip(sx, 0, w - 1)].copy()
    if transparent:
        out[~inside] = 0
    return out


def _displace(src, ctx: Context, box: Box, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Move pixels inside ``box`` by integer offsets (dx, dy are full-canvas maps)."""
    x0, y0, x1, y1 = ctx.box_px(box)
    h, w = src.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    sampled = _sample(src, yy - dy, xx - dx, ctx.transparent)
    out = src.copy()
    region = (slice(max(y0, 0), min(y1, h)), slice(max(x0, 0), min(x1, w)))
    out[region] = sampled[region]
    return out


@dataclass
class Sway:
    amplitude: float = 1.5
    anchor: str = "top"  # top|bottom (horizontal motion) or left|right (vertical motion)
    box: Box = (0.0, 0.0, 1.0, 1.0)
    wavelength: float = 0.6  # fraction of the box along the anchor axis
    cycles: int = 1  # full waves per animation loop
    power: float = 1.5  # how quickly motion grows away from the anchor
    phase: float = 0.0

    @property
    def reach(self) -> float:
        return self.amplitude

    def __call__(self, frame: np.ndarray, t: float, ctx: Context) -> np.ndarray:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = ctx.box_px(self.box)
        vertical_axis = self.anchor in ("top", "bottom")
        idx = np.arange(h if vertical_axis else w, dtype=float)
        lo, hi = (y0, y1) if vertical_axis else (x0, x1)
        pos = np.clip((idx - lo) / max(hi - lo, 1), 0.0, 1.0)
        dist = pos if self.anchor in ("top", "left") else 1.0 - pos
        weight = dist**self.power
        wave = np.sin(2 * math.pi * (self.cycles * t + self.phase) - 2 * math.pi * pos / self.wavelength)
        d = np.rint(self.amplitude * weight * wave).astype(int)
        zeros = np.zeros((h, w), dtype=int)
        if vertical_axis:
            return _displace(frame, ctx, self.box, zeros + d[:, None], zeros)
        return _displace(frame, ctx, self.box, zeros, zeros + d[None, :])


@dataclass
class Breathe:
    amplitude: int = 1
    pivot: float = 0.5  # rows above this fraction of the sprite move
    box: Box = (0.0, 0.0, 1.0, 1.0)

    @property
    def reach(self) -> float:
        return self.amplitude

    def __call__(self, frame, t, ctx):
        h, w = frame.shape[:2]
        off = int(round(self.amplitude * (0.5 - 0.5 * math.cos(2 * math.pi * t))))
        if off == 0:
            return frame
        bx0, by0, bx1, _ = self.box
        box = (bx0, by0, bx1, self.pivot)
        zeros = np.zeros((h, w), dtype=int)
        return _displace(frame, ctx, box, zeros, zeros + off)


@dataclass
class Bob:
    amplitude: float = 2.0
    cycles: int = 1

    @property
    def reach(self) -> float:
        return self.amplitude

    def __call__(self, frame, t, ctx):
        h, w = frame.shape[:2]
        off = int(round(self.amplitude * math.sin(2 * math.pi * self.cycles * t)))
        zeros = np.zeros((h, w), dtype=int)
        return _displace(frame, ctx, (0.0, 0.0, 1.0, 1.0), zeros, zeros + off)


@dataclass
class Flicker:
    amount: float = 0.08  # OKLab lightness swing
    threshold: float = 0.55  # only pixels at least this light flicker
    box: Box = (0.0, 0.0, 1.0, 1.0)
    cycles: int = 2
    ripple: float = 0.35  # spatial phase change per row -> flames "climb"
    seed: int = 0
    _rng_phase: np.ndarray | None = field(default=None, repr=False)

    reach = 0.0

    def __call__(self, frame, t, ctx):
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = ctx.box_px(self.box)
        lab = rgb_to_oklab(frame[..., :3])
        mask = np.zeros((h, w), dtype=bool)
        mask[max(y0, 0) : y1, max(x0, 0) : x1] = True
        mask &= (lab[..., 0] >= self.threshold) & (frame[..., 3] > 0)
        if not mask.any():
            return frame
        if self._rng_phase is None:
            # irregular but loop-safe: sum of two harmonics with random phase
            self._rng_phase = np.random.default_rng(self.seed).uniform(0, 2 * math.pi, 2)
        p1, p2 = self._rng_phase
        rows = np.arange(h)[:, None]
        angle = 2 * math.pi * self.cycles * t
        swing = 0.65 * np.sin(angle + p1 + rows * self.ripple) + 0.35 * np.sin(2 * angle + p2)
        lab[..., 0] += self.amount * np.broadcast_to(swing, (h, w))
        idx = ctx.palette.nearest(lab[mask])
        out = frame.copy()
        out[mask, :3] = ctx.palette.colors[idx]
        return out


EFFECTS = {"sway": Sway, "breathe": Breathe, "bob": Bob, "flicker": Flicker}

PRESETS: dict[str, list] = {
    "idle": [Breathe(1, pivot=0.45), Sway(1, anchor="top", box=(0, 0.45, 1, 1), wavelength=0.8)],
    "cloak": [Sway(2, anchor="top", box=(0, 0.3, 1, 1), wavelength=0.7)],
    "hover": [Bob(2), Sway(1.5, anchor="top", box=(0, 0.5, 1, 1))],
    "flame": [Sway(2, anchor="bottom", wavelength=0.5, cycles=2), Flicker(0.1, threshold=0.45)],
    "glow": [Flicker(0.1, threshold=0.55)],
    "grass": [Sway(2, anchor="bottom", box=(0, 0.75, 1, 1), wavelength=2.0, power=1.0)],
}


def parse_effect(spec: str):
    """Parse ``"sway:amplitude=2,anchor=bottom,box=0;0.7;1;1"`` into an effect."""
    name, _, args = spec.partition(":")
    if name not in EFFECTS:
        raise ValueError(f"unknown effect {name!r}; choose from {sorted(EFFECTS)}")
    kwargs = {}
    for part in filter(None, args.split(",")):
        key, _, value = part.partition("=")
        if key == "box":
            kwargs[key] = tuple(float(v) for v in value.split(";"))
        elif key == "anchor":
            kwargs[key] = value
        elif key in ("cycles", "seed"):
            kwargs[key] = int(value)
        else:
            kwargs[key] = float(value)
    if name == "breathe" and "amplitude" in kwargs:
        kwargs["amplitude"] = int(kwargs["amplitude"])
    return EFFECTS[name](**kwargs)


def animate(
    sprite: np.ndarray,
    effects: list,
    frames: int = 8,
    *,
    palette: Palette | None = None,
) -> list[np.ndarray]:
    """Render ``frames`` looping RGBA frames of ``sprite`` with ``effects`` applied.

    Cutout sprites (with transparency) get a transparent margin so motion is
    never clipped; every frame has the same size.
    """
    sprite = np.asarray(sprite)
    if sprite.shape[-1] == 3:
        sprite = np.dstack([sprite, np.full(sprite.shape[:2], 255, np.uint8)])
    transparent = bool((sprite[..., 3] == 0).any())
    if palette is None:
        opaque = sprite[sprite[..., 3] > 0][:, :3]
        palette = Palette(np.unique(opaque, axis=0))
    pad = int(math.ceil(sum(e.reach for e in effects))) if transparent else 0
    canvas = np.pad(sprite, ((pad, pad), (pad, pad), (0, 0)))
    ctx = Context(pad, pad, sprite.shape[1], sprite.shape[0], palette, transparent)
    out = []
    for i in range(frames):
        t = i / frames
        frame = canvas
        for effect in effects:
            frame = effect(frame, t, ctx)
        out.append(frame)
    return out
