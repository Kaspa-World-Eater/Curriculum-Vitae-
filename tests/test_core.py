import io
import json

import numpy as np
import pytest
from PIL import Image

from pixelforge import (
    Palette,
    animate,
    detect_grid,
    pack,
    pixelate,
    pixelate_frames,
    rotate,
    spin_frames,
    PixelateOptions,
)
from pixelforge.animate import PRESETS
from pixelforge.color import oklab_to_rgb, rgb_to_oklab
from pixelforge.godot import sprite_frames_tres
from pixelforge.grid import MIN_CONFIDENCE
from pixelforge.model_spec import build_spec
from pixelforge.prompts import PROMPT_KINDS, build_all, build_prompt
from pixelforge.sheet import split_sheet
from pixelforge.transform import scale2x


def _random_pixel_art(seed=0, w=32, h=40, n=6):
    rng = np.random.default_rng(seed)
    pal = rng.integers(0, 255, (n, 3)).astype(np.uint8)
    return Image.fromarray(pal[rng.integers(0, n, (h, w))])


def _colors(rgba):
    a = np.asarray(rgba)
    return {tuple(p) for p in a[a[..., 3] > 0][:, :3]}


def test_oklab_roundtrip():
    rgb = np.random.default_rng(1).integers(0, 256, (100, 3)).astype(np.uint8)
    back = oklab_to_rgb(rgb_to_oklab(rgb))
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


@pytest.mark.parametrize("scale", [3, 4, 6, 8, 12])
def test_grid_detection_survives_compression(scale):
    small = _random_pixel_art(scale)
    big = small.resize((small.width * scale, small.height * scale), Image.NEAREST)
    canvas = Image.new("RGB", (big.width + 7, big.height + 5))
    canvas.paste(big, (3, 2))
    buf = io.BytesIO()
    canvas.save(buf, "WEBP", quality=80)
    grid = detect_grid(np.asarray(Image.open(buf).convert("RGB")))
    assert grid.scale_x == scale and grid.scale_y == scale
    assert grid.confidence >= MIN_CONFIDENCE


def test_grid_detection_rejects_painterly_image():
    from PIL import ImageFilter

    rng = np.random.default_rng(3)
    noise = rng.integers(0, 256, (60, 44, 3)).astype(np.uint8)
    smooth = Image.fromarray(noise).resize((600, 440), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3))
    assert detect_grid(np.asarray(smooth)).confidence < MIN_CONFIDENCE


def test_palette_keeps_rare_accent():
    img = np.zeros((100, 100, 3), dtype=np.uint8) + 20  # dark background
    img[45:50, 45:50] = (250, 200, 40)  # tiny gold accent, 0.25% of pixels
    pal = Palette.from_image(img, n_colors=4)
    d = np.sqrt(((pal.lab - rgb_to_oklab(np.array([[250, 200, 40]], dtype=np.uint8))) ** 2).sum(1))
    assert d.min() < 0.05


def test_palette_io(tmp_path):
    pal = Palette(np.array([[0, 0, 0], [255, 0, 0], [12, 34, 56]], dtype=np.uint8))
    for ext in (".hex", ".gpl", ".png"):
        pal.save(tmp_path / f"p{ext}")
        assert sorted(map(tuple, Palette.load(tmp_path / f"p{ext}").colors)) == sorted(map(tuple, pal.colors))


def test_pixelate_locks_palette_and_size():
    src = _random_pixel_art(5, 60, 80, 12).resize((300, 400), Image.BICUBIC)
    pal = Palette(np.array([[0, 0, 0], [255, 255, 255], [200, 30, 30], [30, 200, 30]], dtype=np.uint8))
    r = pixelate(src, PixelateOptions(width=60, palette=pal))
    assert r.image.size == (60, 80)
    assert _colors(r.image) <= set(map(tuple, pal.colors))


def test_pixelate_frames_share_palette_and_shape():
    frames = [_random_pixel_art(i, 30, 30, 8).resize((120, 120), Image.BICUBIC) for i in range(3)]
    results = pixelate_frames(frames, PixelateOptions(width=30, colors=8))
    assert len({r.image.size for r in results}) == 1
    pal = set(map(tuple, results[0].palette.colors))
    for r in results:
        assert _colors(r.image) <= pal


def test_animate_no_new_colors_and_constant_size():
    sprite = np.asarray(_random_pixel_art(9, 24, 40, 5).convert("RGBA")).copy()
    sprite[:5, :, 3] = 0  # some transparency so padding kicks in
    before = _colors(sprite)
    for name, effects in PRESETS.items():
        frames = animate(sprite, [type(e)(**e.__dict__) for e in effects], 6)
        assert len(frames) == 6
        assert len({f.shape for f in frames}) == 1
        assert all(_colors(f) <= before for f in frames), name


def test_rotation_keeps_palette():
    sprite = np.asarray(_random_pixel_art(11, 20, 30, 6).convert("RGBA"))
    before = _colors(sprite)
    r = rotate(sprite, 33)
    assert _colors(r) <= before
    assert rotate(sprite, 90).shape[:2] == (20, 30)
    spins = spin_frames(sprite, 8)
    assert len({s.shape for s in spins}) == 1 and len(spins) == 8


def test_scale2x_doubles_without_new_colors():
    sprite = np.asarray(_random_pixel_art(2, 10, 10, 4).convert("RGBA"))
    big = scale2x(sprite)
    assert big.shape == (20, 20, 4) and _colors(big) <= _colors(sprite)


def test_pack_and_godot_resource(tmp_path):
    frames = {"walk": [_random_pixel_art(i, 16, 20).convert("RGBA") for i in range(4)],
              "idle": [_random_pixel_art(i, 12, 20).convert("RGBA") for i in range(2)]}
    sheet = pack(frames, fps={"walk": 12, "idle": 6})
    assert sheet.frame_width == 16 and sheet.frame_height == 20
    assert [a.name for a in sheet.animations] == ["walk", "idle"]
    assert sheet.animations[1].frames[0] == sheet.columns  # new row per animation
    meta = sheet.save(tmp_path / "s.png")
    data = json.loads(meta.read_text())
    assert data["animations"]["walk"]["fps"] == 12
    tres = sprite_frames_tres(sheet, "res://s.png")
    assert "[gd_resource type=\"SpriteFrames\"" in tres and "&\"walk\"" in tres and "\"speed\": 12.0" in tres


def test_prompts_use_description_everywhere():
    d = "a hooded wanderer with a gold lantern"
    for k, text in build_all(d, "http://x/sheet.png").items():
        assert d in text
    assert "--cref http://x/sheet.png" in build_prompt("front", d, "http://x/sheet.png")
    assert {k.key for k in PROMPT_KINDS} == {"sheet", "sheet4", "front", "back", "sprite", "item"}


def test_split_sheet_finds_three_views():
    fig = _random_pixel_art(4, 30, 80, 5).convert("RGBA")
    sheet = Image.new("RGB", (3 * 30 + 4 * 20, 120), (255, 255, 255))
    for i in range(3):
        sheet.paste(fig, (20 + i * 50, 20))
    views = split_sheet(sheet, expected=3)
    assert [v.name for v in views] == ["front", "side", "back"]
    assert all(v.image.size == (30, 80) for v in views)


def test_model_spec_shape():
    fig = Image.new("RGBA", (40, 100), (0, 0, 0, 0))
    px = fig.load()
    for y in range(100):
        for x in range(40):
            if (x - 20) ** 2 / 400 + (y - 50) ** 2 / 2500 <= 1:
                px[x, y] = (200, 100, 50, 255)
    spec = build_spec(fig, columns=32)
    assert spec["columns"] == 32 and spec["rows"] == 80
    assert 0 < spec["aspect"] < 1
    inside = sum(row.count("1") for row in spec["grid"])
    assert inside > 0.5 * 32 * 80 * 0.78  # ellipse fills ~78% of its box
    assert max(max(r) for r in spec["depth"]) == 1.0
