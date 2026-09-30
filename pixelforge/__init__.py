"""pixelforge - tools for making game-ready pixel art sprites and animations."""

from .animate import PRESETS, Bob, Breathe, Flicker, Sway, animate
from .grid import Grid, detect_grid
from .palette import Palette
from .pixelate import PixelateOptions, PixelateResult, pixelate, pixelate_frames
from .spritesheet import Animation, SpriteSheet, pack, save_gif, slice_sheet

__version__ = "0.1.0"

__all__ = [
    "Animation", "Bob", "Breathe", "Flicker", "Grid", "PRESETS", "Palette", "PixelateOptions",
    "PixelateResult", "SpriteSheet", "Sway", "animate", "detect_grid", "pack", "pixelate",
    "pixelate_frames", "save_gif", "slice_sheet",
]
