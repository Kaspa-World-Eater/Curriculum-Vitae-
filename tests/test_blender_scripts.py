"""Runs the Blender-side scripts when the ``bpy`` module is importable
(``pip install bpy``).  Rendering itself needs a display, so the render call is
mocked; everything around it (framing, camera orbit, manifest) is exercised."""

import json
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

bpy = pytest.importorskip("bpy")

from pixelforge.model_spec import build_spec, write_spec  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "pixelforge" / "blender"


def _ellipse_cutout(w=40, h=100, color=(200, 100, 50)):
    fig = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = fig.load()
    for y in range(h):
        for x in range(w):
            if (x - w / 2) ** 2 / (w / 2) ** 2 + (y - h / 2) ** 2 / (h / 2) ** 2 <= 1:
                px[x, y] = (*color, 255)
    return fig


def _run(script: str, args: list[str]) -> None:
    sys.argv = ["blender", "--", *map(str, args)]
    runpy.run_path(str(SCRIPTS / script), run_name="__main__")


@pytest.fixture
def model(tmp_path):
    front = _ellipse_cutout()
    back = _ellipse_cutout(color=(50, 100, 200))
    front.save(tmp_path / "front.png")
    back.save(tmp_path / "back.png")
    spec = write_spec(build_spec(front, columns=24), tmp_path / "spec.json")
    blend, fbx = tmp_path / "m.blend", tmp_path / "m.fbx"
    _run("build_mesh.py", ["--spec", spec, "--front", tmp_path / "front.png", "--back", tmp_path / "back.png", "--out", blend, "--fbx", fbx, "--name", "Ellipse"])
    return blend, fbx


def test_build_mesh_geometry_and_uvs(model):
    blend, fbx = model
    assert blend.exists() and fbx.exists() and fbx.stat().st_size > 1000
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    obj = bpy.data.objects["Ellipse"]
    lo, hi = obj.bound_box[0], obj.bound_box[6]
    assert abs(hi[2] - lo[2] - 1.8) < 0.05  # height
    assert 0.6 < hi[0] - lo[0] < 0.8  # width = 1.8 * 0.4
    assert 0.2 < hi[1] - lo[1] < 0.6  # inflated thickness
    for name in ("proj_front", "proj_back"):
        uv = obj.data.uv_layers[name].data
        us = np.array([d.uv[0] for d in uv])
        vs = np.array([d.uv[1] for d in uv])
        assert us.min() < 0.05 and us.max() > 0.95, name  # full image width used
        assert vs.min() < 0.05 and vs.max() > 0.95, name
    assert obj.data.materials[0].use_nodes


def test_render_script_framing_and_manifest(model, tmp_path, monkeypatch):
    blend, _ = model
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    monkeypatch.setenv("PF_FAKE_RENDER", "1")  # no display here: write blank frames
    out = tmp_path / "renders"
    _run("render_sprites.py", ["--out", out, "--directions", "8", "--size", "64", "--elevation", "30"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["directions"] == ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
    assert manifest["actions"] == {"still": {"frames": 1, "source_frames": [1]}}
    written = sorted(out.glob("still/*/frame_000.png"))
    assert len(written) == 8 and Image.open(out / "still" / "SW" / "frame_000.png").size == (64, 64)
    # the whole 1.8-unit figure fits in the frame with a small margin
    assert 1.8 < manifest["ortho_scale"] < 2.6
    cam = bpy.context.scene.camera
    assert cam.data.type == "ORTHO" and abs(cam.data.ortho_scale - manifest["ortho_scale"]) < 1e-6
