"""Sprite sheets: packing frames, slicing sheets, metadata, and GIF previews."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class Animation:
    name: str
    frames: list[int]  # indices into the sheet
    fps: float = 8.0
    loop: bool = True


@dataclass
class SpriteSheet:
    image: Image.Image
    frame_width: int
    frame_height: int
    columns: int
    animations: list[Animation] = field(default_factory=list)

    @property
    def frame_count(self) -> int:
        rows = self.image.height // self.frame_height
        return rows * self.columns

    def rect(self, index: int) -> tuple[int, int, int, int]:
        """(x, y, w, h) of a frame in the sheet."""
        return (
            (index % self.columns) * self.frame_width,
            (index // self.columns) * self.frame_height,
            self.frame_width,
            self.frame_height,
        )

    def frame(self, index: int) -> Image.Image:
        x, y, w, h = self.rect(index)
        return self.image.crop((x, y, x + w, y + h))

    def metadata(self, image_name: str) -> dict:
        return {
            "image": image_name,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "columns": self.columns,
            "animations": {a.name: {k: v for k, v in asdict(a).items() if k != "name"} for a in self.animations},
        }

    def save(self, png_path: str | Path) -> Path:
        png_path = Path(png_path)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(png_path)
        meta_path = png_path.with_suffix(".json")
        meta_path.write_text(json.dumps(self.metadata(png_path.name), indent=2) + "\n")
        return meta_path

    @classmethod
    def load(cls, json_path: str | Path) -> "SpriteSheet":
        json_path = Path(json_path)
        meta = json.loads(json_path.read_text())
        anims = [Animation(name, **a) for name, a in meta.get("animations", {}).items()]
        image = Image.open(json_path.parent / meta["image"]).convert("RGBA")
        return cls(image, meta["frame_width"], meta["frame_height"], meta["columns"], anims)


def _to_image(frame) -> Image.Image:
    if isinstance(frame, Image.Image):
        return frame.convert("RGBA")
    return Image.fromarray(np.asarray(frame, dtype=np.uint8), "RGBA")


def pack(
    animations: dict[str, list] | list,
    *,
    fps: float | dict[str, float] = 8.0,
    columns: int | None = None,
    loop: bool = True,
) -> SpriteSheet:
    """Pack frames into one sheet.

    ``animations`` maps name -> list of frames (PIL images or RGBA arrays).  Each
    animation starts on a new row, which keeps sheets readable in Aseprite and
    in Godot's SpriteFrames editor.  Frames of different sizes are centered
    horizontally and bottom-aligned (feet stay on the ground) in a common cell.
    """
    if isinstance(animations, list):
        animations = {"default": animations}
    images = {name: [_to_image(f) for f in frames] for name, frames in animations.items()}
    all_frames = [im for frames in images.values() for im in frames]
    if not all_frames:
        raise ValueError("no frames to pack")
    fw = max(im.width for im in all_frames)
    fh = max(im.height for im in all_frames)
    longest = max(len(f) for f in images.values())
    cols = columns or min(longest, max(1, int(math.ceil(2048 / fw))))

    rows = sum(math.ceil(len(f) / cols) for f in images.values())
    sheet = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
    anims, row = [], 0
    for name, frames in images.items():
        indices = []
        for i, im in enumerate(frames):
            index = row * cols + i
            x = (index % cols) * fw + (fw - im.width) // 2
            y = (index // cols) * fh + (fh - im.height)
            sheet.paste(im, (x, y))
            indices.append(index)
        rate = fps[name] if isinstance(fps, dict) else fps
        anims.append(Animation(name, indices, float(rate), loop))
        row += math.ceil(len(frames) / cols)
    return SpriteSheet(sheet, fw, fh, cols, anims)


def slice_sheet(image: Image.Image, frame_width: int, frame_height: int, count: int | None = None) -> list[Image.Image]:
    """Cut a regular grid sheet into frames (skipping fully empty cells at the end)."""
    image = image.convert("RGBA")
    cols, rows = image.width // frame_width, image.height // frame_height
    frames = []
    for r in range(rows):
        for c in range(cols):
            box = (c * frame_width, r * frame_height, (c + 1) * frame_width, (r + 1) * frame_height)
            frames.append(image.crop(box))
    while count is None and frames and frames[-1].getbbox() is None:
        frames.pop()
    return frames[:count] if count else frames


def save_gif(frames: list, path: str | Path, fps: float = 8.0, zoom: int = 4, background=None) -> None:
    """Upscaled looping GIF preview (nearest-neighbour, transparency preserved)."""
    ims = [_to_image(f) for f in frames]
    ims = [im.resize((im.width * zoom, im.height * zoom), Image.NEAREST) for im in ims]
    if background is not None:
        ims = [Image.alpha_composite(Image.new("RGBA", im.size, background), im) for im in ims]
        conv = [im.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255) for im in ims]
        conv[0].save(path, save_all=True, append_images=conv[1:], duration=int(1000 / fps), loop=0, disposal=2)
        return
    # reserve palette index 255 for transparency
    conv = []
    for im in ims:
        alpha = np.asarray(im)[..., 3]
        p = im.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=255)
        arr = np.asarray(p).copy()
        arr[alpha < 128] = 255
        q = Image.fromarray(arr, "P")
        q.putpalette(p.getpalette()[: 255 * 3] + [0, 0, 0])
        conv.append(q)
    conv[0].save(
        path, save_all=True, append_images=conv[1:], duration=int(1000 / fps),
        loop=0, transparency=255, disposal=2,
    )
