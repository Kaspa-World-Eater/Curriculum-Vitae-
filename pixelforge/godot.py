"""Godot 4 export: SpriteFrames (.tres) resources and AnimatedSprite2D scenes (.tscn).

The files are plain-text Godot resources, so they can be generated without
Godot installed and are diff-friendly in git.  Godot creates the ``.import``
file for the PNG the first time the editor sees it.
"""

from __future__ import annotations

from pathlib import Path

from .spritesheet import SpriteSheet


def _res_path(res_dir: str, filename: str) -> str:
    res_dir = res_dir.rstrip("/")
    if not res_dir.startswith("res://"):
        raise ValueError(f"res_dir must start with res:// (got {res_dir!r})")
    return f"{res_dir}/{filename}" if res_dir != "res:" else f"res://{filename}"


def sprite_frames_tres(sheet: SpriteSheet, texture_res_path: str) -> str:
    return sprite_frames_tres_multi([(sheet, texture_res_path)])


def sprite_frames_tres_multi(sheets: list[tuple[SpriteSheet, str]]) -> str:
    """One SpriteFrames resource over several sheet textures."""
    ext_lines, sub_lines, anim_blocks = [], [], []
    n_sub = 0
    for si, (sheet, tex_path) in enumerate(sheets):
        ext_id = f"{si + 1}_sheet"
        ext_lines.append(f'[ext_resource type="Texture2D" path="{tex_path}" id="{ext_id}"]')
        used = sorted({i for a in sheet.animations for i in a.frames})
        sub_ids = {i: f"AtlasTexture_{si}_{i}" for i in used}
        for i in used:
            x, y, w, h = sheet.rect(i)
            sub_lines += [
                f'[sub_resource type="AtlasTexture" id="{sub_ids[i]}"]',
                f'atlas = ExtResource("{ext_id}")',
                f"region = Rect2({x}, {y}, {w}, {h})",
                "",
            ]
            n_sub += 1
        for a in sheet.animations:
            frames = ", ".join(
                '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % sub_ids[i] for i in a.frames
            )
            anim_blocks.append(
                '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
                % (frames, "true" if a.loop else "false", a.name, float(a.fps))
            )
    lines = [f'[gd_resource type="SpriteFrames" load_steps={n_sub + len(sheets) + 1} format=3]', ""]
    lines += ext_lines + [""] + sub_lines
    lines += ["[resource]", "animations = [" + ", ".join(anim_blocks) + "]", ""]
    return "\n".join(lines)


def scene_tscn(node_name: str, frames_res_path: str, default_animation: str) -> str:
    return "\n".join(
        [
            "[gd_scene load_steps=2 format=3]",
            "",
            f'[ext_resource type="SpriteFrames" path="{frames_res_path}" id="1_frames"]',
            "",
            f'[node name="{node_name}" type="AnimatedSprite2D"]',
            "texture_filter = 1",  # CanvasItem.TEXTURE_FILTER_NEAREST: no blur
            'sprite_frames = ExtResource("1_frames")',
            f'animation = &"{default_animation}"',
            f'autoplay = "{default_animation}"',
            "",
        ]
    )


def export(sheet: SpriteSheet, out_dir: str | Path, name: str, res_dir: str) -> dict[str, Path]:
    """Write ``name.png``, ``name.json``, ``name.tres`` and ``name.tscn`` into ``out_dir``."""
    return export_multi({name: sheet}, out_dir, name, res_dir)


def export_multi(sheets: dict[str, SpriteSheet], out_dir: str | Path, name: str, res_dir: str) -> dict[str, Path]:
    """Several sheets (e.g. one per action, each under Godot's texture limit)
    -> one ``name.tres`` SpriteFrames + ``name.tscn`` + a ``name.json`` index.

    ``res_dir`` is the ``res://`` path that ``out_dir`` corresponds to inside the
    Godot project, e.g. ``res://sprites/knight``.
    """
    import json

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pairs, index = [], {"sheets": {}, "animations": {}}
    files: dict[str, Path] = {}
    for sheet_name, sheet in sheets.items():
        png = out / f"{sheet_name}.png"
        sheet.save(png)
        files[f"png:{sheet_name}"] = png
        pairs.append((sheet, _res_path(res_dir, png.name)))
        meta = sheet.metadata(png.name)
        index["sheets"][sheet_name] = {k: meta[k] for k in ("image", "frame_width", "frame_height", "columns")}
        for anim, data in meta["animations"].items():
            index["animations"][anim] = {"sheet": sheet_name, **data}
    tres = out / f"{name}.tres"
    tres.write_text(sprite_frames_tres_multi(pairs))
    tscn = out / f"{name}.tscn"
    first = next((a for s in sheets.values() for a in s.animations), None)
    default = first.name if first else "default"
    node = "".join(p.capitalize() for p in name.replace("-", "_").split("_"))
    tscn.write_text(scene_tscn(node, _res_path(res_dir, tres.name), default))
    meta_path = out / f"{name}.json"
    meta_path.write_text(json.dumps(index, indent=2) + "\n")
    files.update({"json": meta_path, "tres": tres, "tscn": tscn, "png": files.get(f"png:{name}", next(iter(files.values())))})
    return files
