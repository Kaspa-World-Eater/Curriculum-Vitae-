"""Rig a character model and give it a library of animations - no Mixamo.

Run inside Blender::

    blender -b model.blend --python rig_character.py -- --skeleton skel.json \
        --out model_rigged.blend [--clips idle,walk,run,attack,hit,death] [--fps 30]

* Builds a Mixamo-named humanoid armature from the skeleton spec (so the
  render script's hips lookup and any Mixamo FBX stay compatible).
* Skins the mesh with Blender's automatic (heat) weights, then smooths them.
* Generates procedural, in-place, loopable actions.  They are not motion
  capture; they are clean and consistent, which at sprite size is what reads.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

from pf_common import mesh_objects, script_args  # noqa: E402

R = "mixamorig:"
# bone: (head joint, tail joint, parent bone)
BONES = [
    ("Hips", "hips", "spine", None),
    ("Spine", "spine", "chest", "Hips"),
    ("Spine1", "chest", "neck", "Spine"),
    ("Neck", "neck", "head", "Spine1"),
    ("Head", "head", "head_top", "Neck"),
    ("LeftShoulder", "neck", "shoulder_L", "Spine1"),
    ("LeftArm", "shoulder_L", "elbow_L", "LeftShoulder"),
    ("LeftForeArm", "elbow_L", "wrist_L", "LeftArm"),
    ("LeftHand", "wrist_L", "hand_L", "LeftForeArm"),
    ("RightShoulder", "neck", "shoulder_R", "Spine1"),
    ("RightArm", "shoulder_R", "elbow_R", "RightShoulder"),
    ("RightForeArm", "elbow_R", "wrist_R", "RightArm"),
    ("RightHand", "wrist_R", "hand_R", "RightForeArm"),
    ("LeftUpLeg", "hip_L", "knee_L", "Hips"),
    ("LeftLeg", "knee_L", "ankle_L", "LeftUpLeg"),
    ("LeftFoot", "ankle_L", "toe_L", "LeftLeg"),
    ("RightUpLeg", "hip_R", "knee_R", "Hips"),
    ("RightLeg", "knee_R", "ankle_R", "RightUpLeg"),
    ("RightFoot", "ankle_R", "toe_R", "RightLeg"),
]


def build_armature(spec: dict, height: float, width: float):
    j = {k: Vector((x * width, 0.0, z * height)) for k, (x, z) in spec["joints"].items()}
    # give the limb chains a little depth so bones are not perfectly colinear
    for k in ("knee_L", "knee_R"):
        j[k].y -= 0.02 * height
    for k in ("elbow_L", "elbow_R"):
        j[k].y += 0.02 * height
    arm_data = bpy.data.armatures.new("CharacterRig")
    arm = bpy.data.objects.new("Character", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in BONES:
        b = arm_data.edit_bones.new(R + name)
        b.head, b.tail = j[head], j[tail]
        if (b.tail - b.head).length < 1e-4:
            b.tail = b.head + Vector((0, 0, 0.02 * height))
        b.roll = 0.0
        if parent:
            b.parent = arm_data.edit_bones[R + parent]
            b.use_connect = parent not in ("Hips", "Spine1") or name in ("Spine", "Neck")
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def skin(arm, meshes, smooth_passes: int) -> None:
    import numpy as np

    for m in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        m.select_set(True)
        arm.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        # Laplacian smoothing of the weights so cloth-like bodies bend softly
        me = m.data
        groups = list(m.vertex_groups)
        n = len(me.vertices)
        if not groups or smooth_passes <= 0:
            continue
        edges = np.array([[e.vertices[0], e.vertices[1]] for e in me.edges], dtype=np.int64)
        wts = np.zeros((n, len(groups)))
        for v in me.vertices:
            for g in v.groups:
                wts[v.index, g.group] = g.weight
        deg = np.bincount(edges.ravel(), minlength=n).astype(float)
        deg[deg == 0] = 1
        for _ in range(smooth_passes):
            acc = np.zeros_like(wts)
            np.add.at(acc, edges[:, 0], wts[edges[:, 1]])
            np.add.at(acc, edges[:, 1], wts[edges[:, 0]])
            wts = 0.5 * wts + 0.5 * acc / deg[:, None]
        tot = wts.sum(1, keepdims=True)
        tot[tot == 0] = 1
        wts /= tot
        idx_all = list(range(n))
        for gi, g in enumerate(groups):
            g.remove(idx_all)
            for vi in np.nonzero(wts[:, gi] > 1e-4)[0]:
                g.add([int(vi)], float(wts[vi, gi]), "REPLACE")


# ------------------------------------------------------------------ clips
def _deg(*v):
    return tuple(math.radians(x) for x in v)


def _ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * t)


class Clip:
    """A procedural action: ``pose(t)`` returns {bone: (rx, ry, rz) degrees,
    "root": (dx, dy, dz)} for phase t in [0, 1)."""

    def __init__(self, name: str, frames: int, loop: bool, pose):
        self.name, self.frames, self.loop, self.pose = name, frames, loop, pose


def walk_pose(t, stride=28.0, arm=18.0, bob=0.012):
    s = math.sin(2 * math.pi * t)
    c = math.cos(2 * math.pi * t)
    lift = max(0.0, math.sin(2 * math.pi * t))
    lift2 = max(0.0, -math.sin(2 * math.pi * t))
    return {
        "LeftUpLeg": (-stride * s, 0, 0),
        "RightUpLeg": (stride * s, 0, 0),
        "LeftLeg": (35 * lift2, 0, 0),
        "RightLeg": (35 * lift, 0, 0),
        "LeftArm": (arm * s, 0, 0),
        "RightArm": (-arm * s, 0, 0),
        "LeftForeArm": (-8 - 8 * lift, 0, 0),
        "RightForeArm": (-8 - 8 * lift2, 0, 0),
        "Spine": (4, 0, 3 * s),
        "Hips": (0, 0, -3 * s),
        "Head": (-3, 0, -2 * s),
        "root": (0, 0, -bob * abs(c)),
    }


def idle_pose(t):
    b = math.sin(2 * math.pi * t)
    return {
        "Spine": (1.5 * b, 0, 0),
        "Spine1": (1.5 * b, 0, 0),
        "Head": (-1.5 * b, 0, 1.0 * math.sin(2 * math.pi * t + 1)),
        "LeftArm": (0, 0, 2 * b),
        "RightArm": (0, 0, -2 * b),
        "root": (0, 0, 0.004 * b),
    }


def attack_pose(t):
    # wind up (0-0.35), strike (0.35-0.6), recover (0.6-1)
    if t < 0.35:
        k = _ease(t / 0.35)
        raise_, twist = -110 * k, 25 * k
    elif t < 0.6:
        k = _ease((t - 0.35) / 0.25)
        raise_, twist = -110 + 170 * k, 25 - 55 * k
    else:
        k = _ease((t - 0.6) / 0.4)
        raise_, twist = 60 - 60 * k, -30 + 30 * k
    return {
        "RightArm": (raise_, 0, -20 * (1 - abs(raise_) / 110)),
        "RightForeArm": (-25 - 10 * max(0.0, raise_ / 60), 0, 0),
        "LeftArm": (-raise_ * 0.25, 0, 10),
        "Spine": (8 * (1 if t > 0.35 else 0), 0, twist),
        "Spine1": (0, 0, twist * 0.6),
        "Hips": (0, 0, -twist * 0.4),
        "LeftUpLeg": (-15 if t > 0.35 else 0, 0, 0),
        "RightUpLeg": (12 if t > 0.35 else 0, 0, 0),
        "Head": (0, 0, -twist * 0.5),
    }


def hit_pose(t):
    k = math.sin(math.pi * min(t * 1.4, 1.0)) if t < 1 / 1.4 else 0.0
    return {
        "Spine": (-18 * k, 0, 0),
        "Spine1": (-10 * k, 0, 0),
        "Head": (-15 * k, 0, 0),
        "LeftArm": (-25 * k, 0, 20 * k),
        "RightArm": (-25 * k, 0, -20 * k),
        "root": (0, 0.05 * k, 0),
    }


def death_pose(t):
    k = _ease(min(t / 0.7, 1.0))
    sag = _ease(min(t / 0.3, 1.0))
    return {
        "Hips": (-85 * k, 0, 0),
        "Spine": (-10 * sag + 8 * k, 0, 0),
        "Head": (-20 * sag + 25 * k, 0, 0),
        "LeftUpLeg": (20 * k, 0, 0),
        "RightUpLeg": (10 * k, 0, 0),
        "LeftLeg": (30 * k, 0, 0),
        "RightLeg": (40 * k, 0, 0),
        "LeftArm": (-40 * k, 0, 45 * k),
        "RightArm": (-40 * k, 0, -45 * k),
        "root": (0, 0.15 * k, -0.48 * k),
    }


CLIPS = {
    "idle": Clip("idle", 48, True, idle_pose),
    "walk": Clip("walk", 24, True, walk_pose),
    "run": Clip("run", 16, True, lambda t: walk_pose(t, stride=42, arm=35, bob=0.03)),
    "attack": Clip("attack", 20, False, attack_pose),
    "hit": Clip("hit", 12, False, hit_pose),
    "death": Clip("death", 24, False, death_pose),
}


def action_fcurves(action):
    """F-curves of an action on Blender 4 (flat) and 5 (layered) alike."""
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    out = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                out.extend(bag.fcurves)
    return out


def bake_clip(arm, clip: Clip, height: float):
    action = bpy.data.actions.new(clip.name)
    action.use_fake_user = True
    arm.animation_data_create()
    arm.animation_data.action = action
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    hips = arm.pose.bones[R + "Hips"]
    n = clip.frames
    for f in range(n + (1 if clip.loop else 0)):
        t = (f % n) / n if clip.loop else f / max(n - 1, 1)
        pose = clip.pose(t)
        for pb in arm.pose.bones:
            short = pb.name[len(R):]
            rx, ry, rz = pose.get(short, (0, 0, 0))
            pb.rotation_euler = _deg(rx, ry, rz)
            pb.keyframe_insert("rotation_euler", frame=f + 1)
        dx, dy, dz = pose.get("root", (0, 0, 0))
        hips.location = Vector((dx, dy, dz)) * height
        hips.keyframe_insert("location", frame=f + 1)
    for fc in action_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
    arm.animation_data.action = None
    return action


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--skeleton", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--clips", default="idle,walk,run,attack,hit,death")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--smooth-weights", type=int, default=3)
    a = script_args(p)

    meshes = mesh_objects()
    if not meshes:
        raise SystemExit("no mesh in the .blend; run the model step first")
    spec = json.load(open(a.skeleton))
    lo = [min(min((m.matrix_world @ v.co)[i] for v in m.data.vertices) for m in meshes) for i in range(3)]
    hi = [max(max((m.matrix_world @ v.co)[i] for v in m.data.vertices) for m in meshes) for i in range(3)]
    height, width = hi[2] - lo[2], hi[0] - lo[0]
    # existing rig (e.g. a re-run): drop it
    for o in list(bpy.context.scene.objects):
        if o.type == "ARMATURE":
            bpy.data.objects.remove(o, do_unlink=True)
    for m in meshes:
        for mod in list(m.modifiers):
            if mod.type == "ARMATURE":
                m.modifiers.remove(mod)
    arm = build_armature(spec, height, width)
    arm.location = (0, 0, lo[2])
    skin(arm, meshes, a.smooth_weights)
    bpy.context.scene.render.fps = a.fps
    names = [c.strip() for c in a.clips.split(",") if c.strip()]
    made = []
    for name in names:
        if name not in CLIPS:
            print(f"PF_WARN unknown clip {name}; choose from {sorted(CLIPS)}")
            continue
        bake_clip(arm, CLIPS[name], height)
        made.append(name)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"PF_OK blend={out} actions={','.join(made)} bones={len(arm.data.bones)}")


if __name__ == "__main__":
    main()
