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

from pf_common import UV_BACK, UV_FRONT, UV_SIDE, assign_material, build_projection_material, load_image, script_args  # noqa: E402


def smooth_weights(mesh, passes: int) -> None:
    """Laplacian-smooth every vertex group so a robe swings instead of folding
    sharply around the leg bones (Mixamo's auto-weights are tight)."""
    import numpy as np

    me = mesh.data
    n = len(me.vertices)
    groups = list(mesh.vertex_groups)
    if not groups or n == 0:
        return
    edges = np.array([[e.vertices[0], e.vertices[1]] for e in me.edges], dtype=np.int64)
    weights = np.zeros((n, len(groups)))
    for v in me.vertices:
        for g in v.groups:
            weights[v.index, g.group] = g.weight
    deg = np.bincount(edges.ravel(), minlength=n).astype(np.float64)
    deg[deg == 0] = 1
    for _ in range(passes):
        acc = np.zeros_like(weights)
        np.add.at(acc, edges[:, 0], weights[edges[:, 1]])
        np.add.at(acc, edges[:, 1], weights[edges[:, 0]])
        weights = 0.5 * weights + 0.5 * acc / deg[:, None]
    total = weights.sum(1, keepdims=True)
    total[total == 0] = 1
    weights /= total
    all_idx = list(range(n))
    for gi, g in enumerate(groups):
        g.remove(all_idx)
        for vi in np.nonzero(weights[:, gi] > 1e-4)[0]:
            g.add([int(vi)], float(weights[vi, gi]), "REPLACE")


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
    p.add_argument("--side")
    p.add_argument("--out", required=True)
    p.add_argument("--smooth-weights", type=int, default=4, help="Laplacian passes over bone weights (0 = off)")
    p.add_argument("--depth-scale", type=float, default=1.0, help="thin the mesh front-to-back (bones stay put)")
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

    if a.depth_scale != 1.0:
        from mathutils import Vector  # type: ignore

        for mesh in character_meshes:
            mw = mesh.matrix_world
            inv = mw.inverted()
            ys = [(mw @ v.co).y for v in mesh.data.vertices]
            mid = (min(ys) + max(ys)) / 2
            for v in mesh.data.vertices:
                w = mw @ v.co
                w.y = mid + (w.y - mid) * a.depth_scale
                v.co = inv @ w
        print(f"PF_INFO depth scaled by {a.depth_scale}")

    front = load_image(os.path.abspath(a.front))
    back = load_image(os.path.abspath(a.back)) if a.back else None
    side = load_image(os.path.abspath(a.side)) if a.side else None
    for img in (front, back, side):
        if img is not None:
            img.pack()
    for mesh in character_meshes:
        uvs = mesh.data.uv_layers
        if UV_FRONT not in uvs and len(uvs):
            uvs[0].name = UV_FRONT  # Mixamo kept the coordinates but not the name
        has_back = back is not None and UV_BACK in uvs
        has_side = side is not None and UV_SIDE in uvs
        mat = build_projection_material(f"{mesh.name}_paint", front, back if has_back else None, side if has_side else None)
        assign_material(mesh, mat)
        if back is not None and not has_back:
            print("PF_WARN back UV map missing after Mixamo; using the front image only")
        if a.smooth_weights > 0 and character_arm is not None:
            smooth_weights(mesh, a.smooth_weights)

    actions = sorted(act.name for act in bpy.data.actions)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"PF_OK blend={out} actions={','.join(actions)}")


if __name__ == "__main__":
    main()
