"""Named quality tiers: one switch instead of remembering size + color flags.

Sizes are the longest side of the sprite in pixels; colors is the palette size.
They are starting points, not hard rules - every field can still be overridden.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    name: str
    max_size: int
    colors: int
    dither: str
    description: str


STYLES: dict[str, Style] = {
    "8bit": Style("8bit", 64, 12, "none", "NES-era: tiny, chunky, a dozen colors"),
    "16bit": Style("16bit", 128, 32, "none", "SNES/Genesis-era: medium sprites, 32 colors"),
    "snes": Style("snes", 160, 48, "none", "late-16-bit / early-32-bit: bigger, richer shading"),
    "hd": Style("hd", 224, 96, "none", "modern HD pixel (Blasphemous, Dead Cells): all detail kept"),
}

DEFAULT_STYLE = "hd"


def get_style(name: str) -> Style:
    try:
        return STYLES[name]
    except KeyError:
        raise ValueError(f"unknown style {name!r}; choose from {sorted(STYLES)}") from None
