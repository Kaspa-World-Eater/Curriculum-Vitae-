"""Estimate a humanoid skeleton from the front silhouette.

Mixamo asks a person to drag markers onto the chin, wrists, elbows, knees and
groin.  We place the same landmarks automatically from canonical human
proportions, then snap the horizontal positions to the silhouette (shoulders
to the body's width, hands to the outermost pixels at hand height).  The
result is a JSON spec of joints the Blender script turns into an armature.

Coordinates: x in [-0.5, 0.5] of the silhouette width (left = character's
right), z in [0, 1] of the height (0 = feet).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# canonical heights (fraction of total height) for a standing adult
CANON = {
    "head_top": 1.0,
    "head": 0.935,
    "neck": 0.87,
    "shoulder": 0.815,
    "chest": 0.72,
    "spine": 0.62,
    "hips": 0.53,
    "elbow": 0.63,
    "wrist": 0.46,
    "hand_tip": 0.40,
    "knee": 0.28,
    "ankle": 0.05,
    "toe": 0.0,
}


def _mask(image: Image.Image) -> np.ndarray:
    a = np.asarray(image.convert("RGBA"))[..., 3] > 127
    ys, xs = np.nonzero(a)
    return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _row(mask: np.ndarray, z: float) -> np.ndarray:
    h = mask.shape[0]
    r = int(round((1 - z) * (h - 1)))
    return mask[min(max(r, 0), h - 1)]


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    out, x, n = [], 0, len(row)
    while x < n:
        if row[x]:
            s = x
            while x < n and row[x]:
                x += 1
            out.append((s, x))
        else:
            x += 1
    return out


def estimate_skeleton(front: Image.Image) -> dict:
    m = _mask(front)
    h, w = m.shape

    def nx(px: float) -> float:  # pixel column -> normalised x
        return (px / (w - 1)) - 0.5

    def body_extent(z: float) -> tuple[float, float]:
        """x range of the widest run at height z (the torso, not an arm)."""
        runs = _runs(_row(m, z))
        if not runs:
            return (-0.1, 0.1)
        x0, x1 = max(runs, key=lambda r: r[1] - r[0])
        return nx(x0), nx(x1 - 1)

    def outer_extent(z: float) -> tuple[float, float]:
        runs = _runs(_row(m, z))
        if not runs:
            return (-0.2, 0.2)
        return nx(runs[0][0]), nx(runs[-1][1] - 1)

    sl, sr = body_extent(CANON["shoulder"])
    shoulder_half = max((sr - sl) * 0.42, 0.06)
    hl, hr = outer_extent(CANON["wrist"])
    # hands: outermost pixels at wrist height, pulled slightly inward
    hand_l = min(hl + 0.03, -shoulder_half)
    hand_r = max(hr - 0.03, shoulder_half)
    hip_l, hip_r = body_extent(CANON["hips"])
    hip_half = max((hip_r - hip_l) * 0.22, 0.05)
    cx = 0.0

    joints = {
        "hips": (cx, CANON["hips"]),
        "spine": (cx, CANON["spine"]),
        "chest": (cx, CANON["chest"]),
        "neck": (cx, CANON["neck"]),
        "head": (cx, CANON["head"]),
        "head_top": (cx, CANON["head_top"]),
        "shoulder_L": (shoulder_half, CANON["shoulder"]),
        "shoulder_R": (-shoulder_half, CANON["shoulder"]),
        "elbow_L": ((shoulder_half + hand_r) / 2, CANON["elbow"]),
        "elbow_R": ((-shoulder_half + hand_l) / 2, CANON["elbow"]),
        "wrist_L": (hand_r, CANON["wrist"]),
        "wrist_R": (hand_l, CANON["wrist"]),
        "hand_L": (hand_r, CANON["hand_tip"]),
        "hand_R": (hand_l, CANON["hand_tip"]),
        "hip_L": (hip_half, CANON["hips"] - 0.02),
        "hip_R": (-hip_half, CANON["hips"] - 0.02),
        "knee_L": (hip_half, CANON["knee"]),
        "knee_R": (-hip_half, CANON["knee"]),
        "ankle_L": (hip_half, CANON["ankle"]),
        "ankle_R": (-hip_half, CANON["ankle"]),
        "toe_L": (hip_half, CANON["toe"]),
        "toe_R": (-hip_half, CANON["toe"]),
    }
    return {"version": 1, "aspect": float(w / h), "joints": {k: [float(x), float(z)] for k, (x, z) in joints.items()}}


def write_skeleton(spec: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=1) + "\n")
    return path
