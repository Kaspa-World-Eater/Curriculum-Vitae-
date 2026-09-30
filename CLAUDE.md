# PixelForge

Pixel-art sprite pipeline (Midjourney image → cutouts → optional 3D via
Blender + Mixamo → 8-direction renders → palette-locked pixel frames → Godot).

- **Operating the pipeline for a user:** read `docs/GUIDE_AI.md` first. It has
  every command, the project layout, the standard procedure and the failure
  table. The person-facing version is `docs/GUIDE_HUMANS.md`.
- **Code map:** `pixelforge/api.py` is the pipeline (one function per step);
  `gui.py` (Tkinter app), `cli.py` and `mcp_server.py` are wrappers over it.
  Image algorithms: `grid.py` (pixel-grid detection), `palette.py` (OKLab
  k-means), `quantize.py`, `cleanup.py`, `pixelate.py`, `animate.py`
  (procedural effects), `transform.py` (RotSprite), `sheet.py` (split
  turnaround sheets), `model_spec.py` (inflated-cutout spec). Scripts that run
  inside Blender live in `pixelforge/blender/` and must stay free of Pillow.
- **Tests:** `pytest`. Blender scripts are only import-safe under Blender;
  `tests/test_blender_scripts.py` runs them when the `bpy` module is available.
- **Style:** OKLab for all color distance; never introduce colors outside a
  sprite's palette in a transform; every step returns a JSON-serializable dict.
