"""Build an inflated-cutout character model and paint it with the front/back art.

Run inside Blender (the app and ``pixelforge project model`` do this for you)::

    blender -b --python build_mesh.py -- --spec wraith_spec.json --front front.png \
        [--back back.png] --height 1.8 --out wraith.blend --fbx wraith.fbx

Output: a ``.blend`` with the painted model and an ``.fbx`` you upload to Mixamo
for rigging + animations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore

from pf_common import (  # noqa: E402
    UV_BACK,
    UV_FRONT,
    UV_SIDE,
    assign_material,
    build_projection_material,
    deg,
    load_image,
    make_ortho_camera,
    ortho_scale_for_height,
    project_image_onto,
    script_args,
)


def build_mesh_from_spec(spec: dict, height: float, name: str):
    cols, rows = spec["columns"], spec["rows"]
    width = height * spec["aspect"]
    half_thick = 0.5 * spec["thickness"] * height
    inside = [[ch == "1" for ch in row] for row in spec["grid"]]
    depth = spec["depth"]
    cx, cz = width / cols, height / rows

    def cell_depth(i, j):
        if 0 <= j < rows and 0 <= i < cols and inside[j][i]:
            return depth[j][i]
        return 0.0

    verts, faces = [], []
    index = {}

    def vid(i, j, side):
        key = (i, j, side)
        if key not in index:
            d = min(cell_depth(i - 1, j - 1), cell_depth(i, j - 1), cell_depth(i - 1, j), cell_depth(i, j))
            x = -width / 2 + i * cx
            z = height - j * cz
            y = -half_thick * d if side == 0 else half_thick * d
            index[key] = len(verts)
            verts.append((x, y, z))
        return index[key]

    for j in range(rows):
        for i in range(cols):
            if not inside[j][i]:
                continue
            a, b, c, d = (i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)
            # front sheet faces -Y: winding so the normal points to -Y
            faces.append([vid(*a, 0), vid(*d, 0), vid(*c, 0), vid(*b, 0)])
            faces.append([vid(*a, 1), vid(*b, 1), vid(*c, 1), vid(*d, 1)])

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    # merge the coincident boundary vertices of the two sheets, smooth the result
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj, width


def build_hull_from_spec(spec: dict, height: float, name: str):
    """Voxel visual hull -> boundary quads -> merged, smoothed mesh."""
    import numpy as np

    rows, dcols, cols = spec["rows"], spec["depth_columns"], spec["columns"]
    vox = np.array([[[c == "1" for c in row] for row in layer] for layer in spec["voxels"]], dtype=bool)  # z, y, x
    width = height * spec["aspect"]
    depth = height * spec["thickness"]
    cx, cy, cz = width / cols, depth / dcols, height / rows
    pad = np.pad(vox, 1)
    verts: list = []
    faces: list = []
    index: dict = {}

    def vid(i, j, k):  # grid corner -> vertex (x = i, y = j, z = k)
        key = (i, j, k)
        if key not in index:
            index[key] = len(verts)
            verts.append((-width / 2 + i * cx, -depth / 2 + j * cy, height - k * cz))
        return index[key]

    # for each filled voxel, emit the faces whose neighbour is empty
    zs, ys, xs = np.nonzero(vox)
    for z, y, x in zip(zs, ys, xs):
        pz, py, px = z + 1, y + 1, x + 1
        if not pad[pz, py - 1, px]:  # -y (front)
            faces.append([vid(x, y, z), vid(x, y, z + 1), vid(x + 1, y, z + 1), vid(x + 1, y, z)])
        if not pad[pz, py + 1, px]:  # +y (back)
            faces.append([vid(x, y + 1, z), vid(x + 1, y + 1, z), vid(x + 1, y + 1, z + 1), vid(x, y + 1, z + 1)])
        if not pad[pz, py, px - 1]:  # -x
            faces.append([vid(x, y, z), vid(x, y + 1, z), vid(x, y + 1, z + 1), vid(x, y, z + 1)])
        if not pad[pz, py, px + 1]:  # +x
            faces.append([vid(x + 1, y, z), vid(x + 1, y, z + 1), vid(x + 1, y + 1, z + 1), vid(x + 1, y + 1, z)])
        if not pad[pz - 1, py, px]:  # top (z index smaller = higher)
            faces.append([vid(x, y, z), vid(x + 1, y, z), vid(x + 1, y + 1, z), vid(x, y + 1, z)])
        if not pad[pz + 1, py, px]:  # bottom
            faces.append([vid(x, y, z + 1), vid(x, y + 1, z + 1), vid(x + 1, y + 1, z + 1), vid(x + 1, y, z + 1)])

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    # round off the voxel steps, then bake so Mixamo gets the smooth shape
    sm = obj.modifiers.new("pf_round", "SMOOTH")
    sm.factor = 1.0
    sm.iterations = 6
    bpy.ops.object.modifier_apply(modifier=sm.name)
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj, width


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True)
    p.add_argument("--front", required=True)
    p.add_argument("--back")
    p.add_argument("--side", help="side view image, painted onto the sides (hull models)")
    p.add_argument("--height", type=float, default=1.8, help="character height in metres")
    p.add_argument("--name", default="Character")
    p.add_argument("--smooth", type=int, default=1, help="subdivision levels (0 = blocky)")
    p.add_argument("--out", required=True, help=".blend to write")
    p.add_argument("--fbx", help=".fbx to write for Mixamo")
    a = script_args(p)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    spec = json.load(open(a.spec))
    if spec.get("mode") == "hull":
        obj, _width = build_hull_from_spec(spec, a.height, a.name)
    else:
        obj, _width = build_mesh_from_spec(spec, a.height, a.name)

    front = load_image(os.path.abspath(a.front))
    back = load_image(os.path.abspath(a.back)) if a.back else None
    side = load_image(os.path.abspath(a.side)) if a.side else None

    # cameras framing the silhouette exactly: the cutouts are tight-cropped, and
    # the mesh spans the same box, so the image maps onto the body 1:1 (fitted
    # by height and centred, which also handles a back image of another width).
    cam_f = make_ortho_camera("pf_cam_front", (0, -10, a.height / 2), (deg(90), 0, 0), ortho_scale_for_height(front, a.height))
    project_image_onto(obj, front, UV_FRONT, cam_f)
    if back is not None:
        cam_b = make_ortho_camera("pf_cam_back", (0, 10, a.height / 2), (deg(90), 0, deg(180)), ortho_scale_for_height(back, a.height))
        project_image_onto(obj, back, UV_BACK, cam_b)
    if side is not None:
        # from +X looking -X the character's front (-Y) is on the image's left,
        # matching a side view that faces left; the projection goes through the
        # body so the -X side receives the same (correct) mapping.
        cam_s = make_ortho_camera("pf_cam_side", (10, 0, a.height / 2), (deg(90), 0, deg(90)), ortho_scale_for_height(side, a.height))
        project_image_onto(obj, side, UV_SIDE, cam_s)

    mat = build_projection_material(f"{a.name}_paint", front, back, side)
    assign_material(obj, mat)

    if a.smooth > 0:
        sub = obj.modifiers.new("pf_smooth", "SUBSURF")
        sub.levels = sub.render_levels = a.smooth

    for img in (front, back, side):
        if img is not None:
            img.pack()

    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    if a.fbx:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.export_scene.fbx(
            filepath=os.path.abspath(a.fbx),
            use_selection=True,
            apply_scale_options="FBX_SCALE_ALL",
            path_mode="COPY",
            embed_textures=True,
            mesh_smooth_type="FACE",
        )
    print(f"PF_OK blend={out} fbx={a.fbx or ''} verts={len(obj.data.vertices)}")


if __name__ == "__main__":
    main()
