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
    used = sorted({i for a in sheet.animations for i in a.frames})
    sub_ids = {i: f"AtlasTexture_{i}" for i in used}
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={len(used) + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{texture_res_path}" id="1_sheet"]',
        "",
    ]
    for i in used:
        x, y, w, h = sheet.rect(i)
        lines += [
            f'[sub_resource type="AtlasTexture" id="{sub_ids[i]}"]',
            'atlas = ExtResource("1_sheet")',
            f"region = Rect2({x}, {y}, {w}, {h})",
            "",
        ]
    anim_blocks = []
    for a in sheet.animations:
        frames = ", ".join(
            '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % sub_ids[i] for i in a.frames
        )
        anim_blocks.append(
            '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
            % (frames, "true" if a.loop else "false", a.name, float(a.fps))
        )
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
    """Write ``name.png``, ``name.json``, ``name.tres`` and ``name.tscn`` into ``out_dir``.

    ``res_dir`` is the ``res://`` path that ``out_dir`` corresponds to inside the
    Godot project, e.g. ``res://sprites/knight``.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{name}.png"
    meta = sheet.save(png)
    tres = out / f"{name}.tres"
    tres.write_text(sprite_frames_tres(sheet, _res_path(res_dir, png.name)))
    tscn = out / f"{name}.tscn"
    default = sheet.animations[0].name if sheet.animations else "default"
    node = "".join(p.capitalize() for p in name.replace("-", "_").split("_"))
    tscn.write_text(scene_tscn(node, _res_path(res_dir, tres.name), default))
    return {"png": png, "json": meta, "tres": tres, "tscn": tscn}
