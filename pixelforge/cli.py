"""Command-line interface: ``pixelforge <command> ...`` (see ``--help``)."""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

from PIL import Image

from . import godot
from .animate import PRESETS, animate, parse_effect
from .palette import Palette
from .pixelate import PixelateOptions, pixelate, pixelate_frames
from .quantize import DITHER_MODES
from .spritesheet import pack, save_gif, slice_sheet
from .styles import DEFAULT_STYLE, STYLES, get_style
from .transform import flip, rotate, spin_frames, turn

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        path = Path(p)
        if path.is_dir():
            out += sorted(q for q in path.iterdir() if q.suffix.lower() in IMAGE_EXTS)
        else:
            matches = sorted(glob.glob(p))
            if not matches:
                raise SystemExit(f"no files match {p!r}")
            out += [Path(m) for m in matches]
    return out


def _parse_anim(spec: str) -> tuple[str, list[Path], float]:
    """``name=glob[@fps]``"""
    name, _, rest = spec.partition("=")
    if not rest:
        raise SystemExit(f"--anim expects name=glob[@fps], got {spec!r}")
    pattern, _, fps = rest.rpartition("@") if "@" in rest else (rest, "", "8")
    return name, _expand([pattern]), float(fps)


def _add_pixelate_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("pixelation")
    styles = ", ".join(f"{k} ({v.max_size}px/{v.colors} colors)" for k, v in STYLES.items())
    g.add_argument("--style", choices=sorted(STYLES), default=DEFAULT_STYLE, help=f"quality tier: {styles}")
    g.add_argument("--scale", default="auto", help="logical pixel size in source pixels, or 'auto' (default)")
    g.add_argument("--max-size", type=int, help="fallback longest side when no grid is detected (default: from --style)")
    g.add_argument("--width", type=int, help="force sprite width in pixels")
    g.add_argument("--height", type=int, help="force sprite height in pixels")
    g.add_argument("--colors", type=int, help="palette size when extracting (default: from --style)")
    g.add_argument("--palette", help="use a fixed palette (.hex, .gpl or .png)")
    g.add_argument("--dither", choices=DITHER_MODES, help="default: from --style")
    g.add_argument("--dither-strength", type=float, default=0.6)
    g.add_argument("--remove-bg", action="store_true", help="flood-remove the background from the borders")
    g.add_argument("--bg-tolerance", type=float, default=0.03, help="OKLab distance for --remove-bg")
    g.add_argument("--outline", help="'auto' (darkest palette color) or a hex color")
    g.add_argument("--crop", action="store_true", help="crop to the opaque content")
    g.add_argument("--no-despeckle", action="store_true")


def _options(a) -> PixelateOptions:
    style = get_style(a.style)
    return PixelateOptions(
        scale=a.scale if a.scale == "auto" else float(a.scale),
        max_size=a.max_size or style.max_size,
        width=a.width,
        height=a.height,
        colors=a.colors or style.colors,
        palette=Palette.load(a.palette) if a.palette else None,
        dither=a.dither or style.dither,
        dither_strength=a.dither_strength,
        remove_background=a.remove_bg,
        bg_tolerance=a.bg_tolerance,
        despeckle=not a.no_despeckle,
        outline=a.outline,
        crop=a.crop,
    )


def cmd_pixelate(a) -> None:
    for src in _expand(a.inputs):
        result = pixelate(Image.open(src), _options(a))
        out = Path(a.output) if a.output and len(a.inputs) == 1 and not Path(a.output).is_dir() else None
        if out is None:
            out_dir = Path(a.output or ".")
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / f"{src.stem}_px.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        result.image.save(out)
        if a.preview:
            result.preview(a.preview).save(out.with_name(out.stem + f"_x{a.preview}.png"))
        if a.save_palette:
            result.palette.save(a.save_palette)
        for n in result.notes:
            print(f"  {src.name}: {n}")
        print(f"{src} -> {out} ({result.image.width}x{result.image.height}, {len(result.palette)} colors)")


def cmd_palette(a) -> None:
    images = [Image.open(p).convert("RGBA") for p in _expand(a.inputs)]
    import numpy as np

    px = np.concatenate([np.asarray(im).reshape(-1, 4) for im in images])
    px = px[px[:, 3] > 127][:, :3]
    palette = Palette.from_image(px[None], n_colors=a.colors, accent_boost=a.accent_boost)
    palette.save(a.output)
    if a.swatch:
        palette.swatch(cell=16).save(a.swatch)
    print(f"{len(palette)} colors -> {a.output}")


def cmd_frames(a) -> None:
    paths = _expand(a.inputs)
    results = pixelate_frames([Image.open(p) for p in paths], _options(a), stabilize=a.stabilize)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(results):
        r.image.save(out / f"frame_{i:03d}.png")
    results[0].palette.save(out / "palette.hex")
    if a.gif:
        save_gif([r.image for r in results], out / "preview.gif", fps=a.fps, zoom=a.zoom)
    for n in results[0].notes:
        print(f"  {n}")
    print(f"{len(results)} frames -> {out}")


def cmd_animate(a) -> None:
    import numpy as np

    sprite = np.asarray(Image.open(a.sprite).convert("RGBA"))
    effects = [e for name in a.preset for e in _fresh_preset(name)]
    effects += [parse_effect(s) for s in a.effect]
    if not effects:
        raise SystemExit("choose at least one --preset or --effect")
    palette = Palette.load(a.palette) if a.palette else None
    if a.flip:
        sprite = flip(sprite)
    frames = animate(sprite, effects, a.frames, palette=palette)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        Image.fromarray(f, "RGBA").save(out / f"{a.name}_{i:03d}.png")
    if a.gif:
        save_gif(frames, out / f"{a.name}.gif", fps=a.fps, zoom=a.zoom)
    print(f"{len(frames)} frames ({frames[0].shape[1]}x{frames[0].shape[0]}) -> {out}")


def _fresh_preset(name: str) -> list:
    import copy

    if name not in PRESETS:
        raise SystemExit(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    return copy.deepcopy(PRESETS[name])


def _sheet_from_args(a):
    anims, fps = {}, {}
    for spec in a.anim:
        name, paths, rate = _parse_anim(spec)
        anims[name] = [Image.open(p) for p in paths]
        fps[name] = rate
    return pack(anims, fps=fps, columns=a.columns)


def cmd_pack(a) -> None:
    sheet = _sheet_from_args(a)
    meta = sheet.save(a.output)
    print(f"{sheet.frame_count} cells {sheet.frame_width}x{sheet.frame_height} -> {a.output} + {meta.name}")


def cmd_godot(a) -> None:
    sheet = _sheet_from_args(a)
    files = godot.export(sheet, a.out, a.name, a.res_dir)
    for kind, path in files.items():
        print(f"{kind:5s} {path}")


def cmd_rotate(a) -> None:
    import numpy as np

    sprite = np.asarray(Image.open(a.sprite).convert("RGBA"))
    out = Path(a.output)
    stem = Path(a.sprite).stem
    if a.spin:
        out.mkdir(parents=True, exist_ok=True)
        frames = spin_frames(sprite, a.spin, clockwise=not a.ccw)
        for i, f in enumerate(frames):
            Image.fromarray(f, "RGBA").save(out / f"{stem}_spin_{i:03d}.png")
        if a.gif:
            save_gif(frames, out / f"{stem}_spin.gif", fps=a.fps, zoom=a.zoom)
        print(f"{len(frames)} spin frames ({frames[0].shape[1]}x{frames[0].shape[0]}) -> {out}")
        return
    result = sprite
    if a.flip:
        result = flip(result, horizontal=a.flip == "h")
    if a.turn:
        result = turn(result, a.turn)
    if a.angle:
        result = rotate(result, a.angle)
    if out.suffix.lower() != ".png":
        out.mkdir(parents=True, exist_ok=True)
        out = out / f"{stem}_rot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(result), "RGBA").save(out)
    print(f"{a.sprite} -> {out} ({result.shape[1]}x{result.shape[0]})")


def cmd_slice(a) -> None:
    w, _, h = a.frame.partition("x")
    frames = slice_sheet(Image.open(a.sheet), int(w), int(h), a.count)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(out / f"frame_{i:03d}.png")
    print(f"{len(frames)} frames -> {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pixelforge", description="Pixel-art sprite tools for games and Godot.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("pixelate", help="convert images (AI renders, fake pixel art) into clean sprites")
    s.add_argument("inputs", nargs="+")
    s.add_argument("-o", "--output", help="output file (single input) or directory")
    s.add_argument("--preview", type=int, metavar="ZOOM", help="also save an upscaled preview")
    s.add_argument("--save-palette", help="write the palette used (.hex/.gpl/.png)")
    _add_pixelate_args(s)
    s.set_defaults(func=cmd_pixelate)

    s = sub.add_parser("palette", help="extract a palette from one or more images")
    s.add_argument("inputs", nargs="+")
    s.add_argument("-o", "--output", required=True, help=".hex, .gpl or .png")
    s.add_argument("--colors", type=int, default=96)
    s.add_argument("--accent-boost", type=float, default=0.5, help="<1 keeps rare accent colors")
    s.add_argument("--swatch", help="also save an enlarged swatch image")
    s.set_defaults(func=cmd_palette)

    s = sub.add_parser("frames", help="pixelate an animation consistently (shared grid + palette)")
    s.add_argument("inputs", nargs="+", help="frame files, globs, or a directory")
    s.add_argument("-o", "--output", required=True, help="output directory")
    s.add_argument("--stabilize", type=float, default=0.04, help="OKLab drift below which pixels hold still")
    s.add_argument("--gif", action="store_true")
    s.add_argument("--fps", type=float, default=8)
    s.add_argument("--zoom", type=int, default=4)
    _add_pixelate_args(s)
    s.set_defaults(func=cmd_frames)

    s = sub.add_parser("animate", help="procedurally animate a still sprite")
    s.add_argument("sprite")
    s.add_argument("-o", "--output", required=True, help="output directory")
    s.add_argument("--preset", action="append", default=[], help=f"one of {sorted(PRESETS)} (repeatable)")
    s.add_argument("--effect", action="append", default=[], help="e.g. 'sway:amplitude=2,anchor=bottom,box=0;0.6;1;1'")
    s.add_argument("--frames", type=int, default=8)
    s.add_argument("--fps", type=float, default=8)
    s.add_argument("--name", default="anim", help="frame file prefix")
    s.add_argument("--palette", help="palette for flicker (default: the sprite's own colors)")
    s.add_argument("--flip", action="store_true", help="mirror first, e.g. to make the left-facing set")
    s.add_argument("--gif", action="store_true")
    s.add_argument("--zoom", type=int, default=4)
    s.set_defaults(func=cmd_animate)

    for name, func, helptext in (
        ("pack", cmd_pack, "pack frames into a sprite sheet + JSON"),
        ("godot", cmd_godot, "export a Godot 4 SpriteFrames (.tres) + AnimatedSprite2D scene (.tscn)"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--anim", action="append", required=True, help="name=glob[@fps], repeatable")
        s.add_argument("--columns", type=int)
        if name == "pack":
            s.add_argument("-o", "--output", required=True, help="sheet .png")
        else:
            s.add_argument("--name", required=True, help="base file name, e.g. knight")
            s.add_argument("--out", required=True, help="directory inside your Godot project")
            s.add_argument("--res-dir", required=True, help="res:// path of --out, e.g. res://sprites/knight")
        s.set_defaults(func=func)

    s = sub.add_parser("rotate", help="flip, turn or rotate a sprite without blurring it (RotSprite)")
    s.add_argument("sprite")
    s.add_argument("-o", "--output", required=True, help="output .png, or a directory for --spin")
    s.add_argument("--angle", type=float, default=0.0, help="degrees counter-clockwise, any value")
    s.add_argument("--turn", type=int, default=0, help="exact quarter turns counter-clockwise (1 = 90 degrees)")
    s.add_argument("--flip", choices=["h", "v"], help="mirror horizontally (face the other way) or vertically")
    s.add_argument("--spin", type=int, metavar="N", help="make an N-frame full-rotation animation instead")
    s.add_argument("--ccw", action="store_true", help="spin counter-clockwise")
    s.add_argument("--gif", action="store_true")
    s.add_argument("--fps", type=float, default=12)
    s.add_argument("--zoom", type=int, default=4)
    s.set_defaults(func=cmd_rotate)

    s = sub.add_parser("slice", help="cut a grid sprite sheet into frames")
    s.add_argument("sheet")
    s.add_argument("--frame", required=True, help="WxH, e.g. 64x64")
    s.add_argument("--count", type=int)
    s.add_argument("-o", "--output", required=True)
    s.set_defaults(func=cmd_slice)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
