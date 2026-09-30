"""Shared helpers for the scripts that run *inside* Blender (``blender --python``).

Keep this file dependency-free: Blender's Python has numpy but not Pillow.
"""

from __future__ import annotations

import argparse
import math
import sys

import bpy  # type: ignore

UV_FRONT = "proj_front"
UV_BACK = "proj_back"


def script_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    """Parse the arguments after ``--`` on Blender's command line."""
    argv = sys.argv
    rest = argv[argv.index("--") + 1 :] if "--" in argv else []
    return parser.parse_args(rest)


def eevee_engine_id() -> str:
    ids = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in ids else "BLENDER_EEVEE"


def load_image(path: str):
    img = bpy.data.images.load(path, check_existing=True)
    img.alpha_mode = "STRAIGHT"
    return img


def make_ortho_camera(name: str, location, rotation, ortho_scale: float):
    cam_data = bpy.data.cameras.new(name)
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start = 0.01
    cam_data.clip_end = 1000
    cam = bpy.data.objects.new(name, cam_data)
    cam.location = location
    cam.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(cam)
    return cam


def project_image_onto(obj, image, uv_name: str, camera) -> None:
    """Bake ``image``'s camera projection into a UV map called ``uv_name``.

    The modifier's aspect must be the image's pixel aspect (verified: with
    aspect 1:1 a portrait image only covers the middle of its width).  The
    camera's ``ortho_scale`` spans the image's *larger* side.
    """
    if uv_name not in obj.data.uv_layers:
        obj.data.uv_layers.new(name=uv_name)
    mod = obj.modifiers.new(name=f"pf_{uv_name}", type="UV_PROJECT")
    mod.uv_layer = uv_name
    mod.projector_count = 1
    mod.projectors[0].object = camera
    mod.aspect_x, mod.aspect_y = image.size
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def ortho_scale_for_height(image, height: float) -> float:
    """ortho_scale so the image's frame is exactly ``height`` tall."""
    iw, ih = image.size
    return height if ih >= iw else height * iw / ih


def build_projection_material(name: str, front_img, back_img=None, blend: float = 0.15):
    """Unlit material showing the front image on front-facing parts, back on the rest."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

    tex_front = nt.nodes.new("ShaderNodeTexImage")
    tex_front.image = front_img
    tex_front.interpolation = "Closest" if max(front_img.size) < 600 else "Linear"
    tex_front.extension = "EXTEND"
    uv_front = nt.nodes.new("ShaderNodeUVMap")
    uv_front.uv_map = UV_FRONT
    nt.links.new(uv_front.outputs["UV"], tex_front.inputs["Vector"])
    mat.node_tree.nodes.active = tex_front

    if back_img is None:
        nt.links.new(tex_front.outputs["Color"], emit.inputs["Color"])
        return mat

    tex_back = nt.nodes.new("ShaderNodeTexImage")
    tex_back.image = back_img
    tex_back.extension = "EXTEND"
    uv_back = nt.nodes.new("ShaderNodeUVMap")
    uv_back.uv_map = UV_BACK
    nt.links.new(uv_back.outputs["UV"], tex_back.inputs["Vector"])

    # facing = normal . (0, -1, 0): +1 straight at the front camera, -1 at the back
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.0, -1.0, 0.0)
    nt.links.new(geo.outputs["Normal"], dot.inputs[0])
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = -blend
    ramp.inputs["From Max"].default_value = blend
    ramp.clamp = True
    nt.links.new(dot.outputs["Value"], ramp.inputs["Value"])

    try:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(ramp.outputs["Result"], mix.inputs[0])
        nt.links.new(tex_back.outputs["Color"], mix.inputs[6])  # A: factor 0 = back
        nt.links.new(tex_front.outputs["Color"], mix.inputs[7])  # B: factor 1 = front
        nt.links.new(mix.outputs[2], emit.inputs["Color"])
    except (RuntimeError, KeyError, IndexError):
        mix = nt.nodes.new("ShaderNodeMixRGB")
        nt.links.new(ramp.outputs["Result"], mix.inputs["Fac"])
        nt.links.new(tex_back.outputs["Color"], mix.inputs["Color1"])
        nt.links.new(tex_front.outputs["Color"], mix.inputs["Color2"])
        nt.links.new(mix.outputs["Color"], emit.inputs["Color"])
    return mat


def assign_material(obj, mat) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def bbox_world(obj):
    """(min, max) corners of an object's evaluated bounding box in world space."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    pts = [ev.matrix_world @ mathutils_vector(c) for c in ev.bound_box]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi


def mathutils_vector(c):
    from mathutils import Vector  # type: ignore

    return Vector(c)


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def armature_objects():
    return [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]


def deg(x: float) -> float:
    return math.radians(x)
