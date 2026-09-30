"""Import the rigged model + animations downloaded from Mixamo into one .blend.

Run inside Blender::

    blender -b --python import_animations.py -- --fbx mixamo/*.fbx --front front.png \
        [--back back.png] --out wraith_rigged.blend

Mixamo gives one FBX per animation.  Download the first one *with skin* (it
carries the mesh) and the rest *without skin* (just the motion).  Every
animation becomes a Blender action named after its file, ready for
``render_sprites.py``.  The paint material is rebuilt on the imported mesh,
using the UV maps Mixamo preserved.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from pf_common import UV_BACK, UV_FRONT, assign_material, build_projection_material, load_image, script_args  # noqa: E402


def clean_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    for junk in (" (1)", "_with_skin", "_without_skin", "Mixamo", "mixamo"):
        stem = stem.replace(junk, "")
    return stem.strip(" _-") or "anim"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--fbx", nargs="+", required=True)
    p.add_argument("--front", required=True)
    p.add_argument("--back")
    p.add_argument("--out", required=True)
    a = script_args(p)

    files = sorted({f for pat in a.fbx for f in glob.glob(pat)})
    if not files:
        raise SystemExit(f"no FBX files match {a.fbx}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    character_arm = None
    character_meshes: list = []
    for path in files:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True, ignore_leaf_bones=True)
        new = [o for o in bpy.data.objects if o not in before]
        arms = [o for o in new if o.type == "ARMATURE"]
        meshes = [o for o in new if o.type == "MESH"]
        name = clean_name(path)
        for arm in arms:
            if arm.animation_data and arm.animation_data.action:
                act = arm.animation_data.action
                act.name = name
                act.use_fake_user = True
        if meshes and not character_meshes:
            character_meshes = meshes
            if arms:
                character_arm = arms[0]
                character_arm.name = "Character"
        else:
            # motion-only file: keep the action, drop the objects
            for o in new:
                bpy.data.objects.remove(o, do_unlink=True)
    if not character_meshes:
        raise SystemExit("none of the FBX files carried a mesh: download one animation 'with skin'")
    if character_arm is None:
        print("PF_WARN no armature found: the model is not rigged, only a still can be rendered")

    front = load_image(os.path.abspath(a.front))
    back = load_image(os.path.abspath(a.back)) if a.back else None
    for img in (front, back):
        if img is not None:
            img.pack()
    for mesh in character_meshes:
        uvs = mesh.data.uv_layers
        if UV_FRONT not in uvs and len(uvs):
            uvs[0].name = UV_FRONT  # Mixamo kept the coordinates but not the name
        has_back = back is not None and UV_BACK in uvs
        mat = build_projection_material(f"{mesh.name}_paint", front, back if has_back else None)
        assign_material(mesh, mat)
        if back is not None and not has_back:
            print("PF_WARN back UV map missing after Mixamo; using the front image only")

    actions = sorted(act.name for act in bpy.data.actions)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"PF_OK blend={out} actions={','.join(actions)}")


if __name__ == "__main__":
    main()
