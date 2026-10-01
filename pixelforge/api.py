"""The pipeline as plain functions.

Every function takes a :class:`Project` (+ a character name), does one step,
records the result in ``project.json`` and returns a JSON-serialisable dict.
The desktop app, the ``pixelforge project`` commands and the MCP server are all
thin wrappers over this module, so anything a person can click, an AI can run.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from . import cleanup
from . import godot as godot_export
from .animate import PRESETS, animate
from .model_spec import build_spec, write_spec
from .palette import Palette
from .pixelate import PixelateOptions, pixelate, pixelate_frames
from .project import DIRECTIONS_8, SOURCE_KINDS, Character, Project, slugify
from .prompts import PROMPT_KINDS, RULES, build_all
from .sheet import cutout, normalize_heights, split_sheet
from .spritesheet import pack, save_gif
from .styles import get_style

BLENDER_DIR = Path(__file__).parent / "blender"


class StepError(RuntimeError):
    """A step could not run; the message tells the person/AI what to do."""


# ------------------------------------------------------------------ projects
def new_project(root: str | Path, name: str, style: str = "hd") -> dict:
    get_style(style)
    p = Project.create(root, name, style=style)
    return {"ok": True, "project": str(p.file), **p.summary()}


def open_project(path: str | Path) -> Project:
    return Project.load(path)


def status(project: Project) -> dict:
    return {"ok": True, **project.summary(), "blender_found": find_blender(project) is not None}


def configure(project: Project, **fields) -> dict:
    for k, v in fields.items():
        if v is None:
            continue
        if not hasattr(project, k) or k in ("characters", "root"):
            raise StepError(f"unknown setting {k!r}")
        if k == "style":
            get_style(v)
        setattr(project, k, type(getattr(project, k))(v))
    project.save()
    return status(project)


# ---------------------------------------------------------------- characters
def add_character(project: Project, name: str, description: str = "") -> dict:
    key = slugify(name)
    if key in project.characters:
        raise StepError(f"character {key!r} already exists")
    project.characters[key] = Character(name=key, description=description)
    project.sub(key, "source")
    project.save()
    return {"ok": True, "character": key, "next": "prompts"}


def set_description(project: Project, name: str, description: str) -> dict:
    c = project.character(name)
    c.description = description.strip()
    c.done["prompts"] = bool(c.description)
    project.save()
    return get_prompts(project, name)


def get_prompts(project: Project, name: str, reference: str = "[SHEET IMAGE URL]") -> dict:
    c = project.character(name)
    prompts = build_all(c.description, reference)
    return {
        "ok": True,
        "character": c.name,
        "description": c.description,
        "prompts": [
            {"key": k.key, "title": k.title, "purpose": k.purpose, "prompt": prompts[k.key], "needs_reference": k.needs_reference}
            for k in PROMPT_KINDS
        ],
        "rules": RULES,
        "next": "import",
    }


def import_source(project: Project, name: str, kind: str, path: str | Path) -> dict:
    if kind not in SOURCE_KINDS:
        raise StepError(f"kind must be one of {SOURCE_KINDS}")
    c = project.character(name)
    src = Path(path)
    if not src.exists():
        raise StepError(f"file not found: {src}")
    dest = project.sub(c.name, "source") / f"{kind}.png"
    Image.open(src).convert("RGBA").save(dest)
    c.sources[kind] = str(dest.relative_to(project.root)).replace(os.sep, "/")
    c.done["import"] = "sheet" in c.sources or "front" in c.sources or "style" in c.sources
    project.save()
    return {"ok": True, "character": c.name, "kind": kind, "saved": str(dest), "sources": c.sources, "next": "split"}


def _source(project: Project, c: Character, kind: str) -> Path | None:
    rel = c.sources.get(kind)
    return project.root / rel if rel else None


# --------------------------------------------------------------------- split
def split(project: Project, name: str, tolerance: float = 0.08) -> dict:
    """Cut the sheet (or the single front/back/side images) into view cutouts."""
    c = project.character(name)
    views_dir = project.sub(c.name, "views")
    made: dict[str, str] = {}
    sheet = _source(project, c, "sheet")
    if sheet is not None:
        views = normalize_heights(split_sheet(Image.open(sheet), tolerance=tolerance, expected=3))
        if not views:
            raise StepError("no figures found on the sheet; is the background plain?")
        for v in views:
            out = views_dir / f"{v.name}.png"
            v.image.save(out)
            made[v.name] = str(out)
    # single views override the sheet's crops when supplied (they are higher-res)
    for kind in ("front", "back", "side"):
        single = _source(project, c, kind)
        if single is not None:
            rgba = cutout(Image.open(single), tolerance)
            ys, xs = np.nonzero(rgba[..., 3])
            if len(ys):
                rgba = rgba[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
            out = views_dir / f"{kind}.png"
            Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(out)
            made[kind] = str(out)
    if not made:
        raise StepError("import a sheet or a front image first")
    if "front" not in made:
        raise StepError(f"could not identify a front view (found {sorted(made)}); import a front image")
    c.done["split"] = True
    c.notes["split"] = f"views: {', '.join(sorted(made))}"
    project.save()
    return {"ok": True, "character": c.name, "views": made, "next": "palette"}


# ------------------------------------------------------------------- palette
def make_palette(project: Project, name: str, colors: int | None = None) -> dict:
    c = project.character(name)
    st = get_style(c.settings.get("style", project.style))
    n = colors or st.colors
    style_img = _source(project, c, "style")
    sources = []
    if style_img is not None:
        sources.append(np.asarray(Image.open(style_img).convert("RGBA")))
    for v in sorted(project.sub(c.name, "views").glob("*.png")):
        sources.append(np.asarray(Image.open(v).convert("RGBA")))
    if not sources:
        raise StepError("nothing to build a palette from; import a style image or run split")
    px = np.concatenate([s.reshape(-1, 4) for s in sources])
    px = px[px[:, 3] > 127][:, :3]
    pal = Palette.from_image(px[None], n_colors=n)
    out = project.char_dir(c.name) / "palette.hex"
    pal.save(out)
    pal.swatch(16).save(out.with_suffix(".png"))
    c.done["palette"] = True
    c.notes["palette"] = f"{len(pal)} colors from {'style image + ' if style_img else ''}views"
    project.save()
    return {"ok": True, "character": c.name, "palette": str(out), "colors": len(pal), "next": "model"}


# ------------------------------------------------------------------- blender
WINDOWS_BLENDER_GLOBS = [
    r"C:\Program Files\Blender Foundation\Blender *\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender\blender.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Blender Foundation\Blender *\blender.exe"),
    r"C:\Program Files\WindowsApps\BlenderFoundation.Blender*\Blender\blender.exe",
]


def find_blender(project: Project | None = None) -> str | None:
    if project and project.blender and Path(project.blender).exists():
        return project.blender
    for cand in ("blender", "blender.exe"):
        found = shutil.which(cand)
        if found:
            return found
    for pattern in WINDOWS_BLENDER_GLOBS:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    for mac in ("/Applications/Blender.app/Contents/MacOS/Blender",):
        if Path(mac).exists():
            return mac
    return None


def run_blender(project: Project, script: str, args: list[str], blend: str | None = None, log=None) -> str:
    exe = find_blender(project)
    if exe is None:
        raise StepError(
            "Blender was not found. Install it from blender.org, or set the path in Settings "
            "(`pixelforge project set --blender \"C:\\...\\blender.exe\"`)."
        )
    cmd = [exe, "-b"]
    if blend:
        cmd.append(str(blend))
    cmd += ["--python", str(BLENDER_DIR / script), "--", *map(str, args)]
    if log:
        log("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    lines = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        lines.append(line)
        if log and (line.startswith("PF_") or "Error" in line or "Traceback" in line):
            log(line)
    proc.wait()
    ok = [l for l in lines if l.startswith("PF_OK")]
    if proc.returncode != 0 or not ok:
        tail = "\n".join(lines[-25:])
        raise StepError(f"Blender failed (exit {proc.returncode}):\n{tail}")
    return ok[-1]


def model_textures(project: Project, c: Character) -> dict[str, Path]:
    """Edge-padded copies of the view cutouts, for use as 3D textures."""
    views = project.sub(c.name, "views")
    out = {}
    for kind in ("front", "back"):
        src = views / f"{kind}.png"
        if src.exists():
            tex = project.sub(c.name, "model") / f"tex_{kind}.png"
            if not tex.exists() or tex.stat().st_mtime < src.stat().st_mtime:
                rgba = cleanup.bleed_edges(np.asarray(Image.open(src).convert("RGBA")))
                Image.fromarray(rgba, "RGBA").save(tex)
            out[kind] = tex
    return out


def build_model(project: Project, name: str, height: float = 1.8, columns: int = 64, thickness: float | None = None, log=None) -> dict:
    """Front (+side) cutout -> inflated-cutout mesh painted with the art -> .blend + .fbx."""
    c = project.character(name)
    views = project.sub(c.name, "views")
    front = views / "front.png"
    if not front.exists():
        raise StepError("run split first (no views/front.png)")
    side = views / "side.png"
    spec = build_spec(Image.open(front), Image.open(side) if side.exists() else None, columns=columns, thickness=thickness)
    # a side view includes the cloak's flare; the body itself is thinner
    spec["thickness"] = float(min(spec["thickness"] * 0.6, 0.3))
    model_dir = project.sub(c.name, "model")
    spec_path = write_spec(spec, model_dir / f"{c.name}_spec.json")
    blend = model_dir / f"{c.name}.blend"
    fbx = model_dir / f"{c.name}.fbx"
    tex = model_textures(project, c)
    args = ["--spec", spec_path, "--front", tex["front"], "--height", height, "--name", c.name, "--out", blend, "--fbx", fbx]
    if "back" in tex:
        args += ["--back", tex["back"]]
    result = run_blender(project, "build_mesh.py", args, log=log)
    c.done["model"] = True
    c.notes["model"] = result
    project.save()
    return {
        "ok": True,
        "character": c.name,
        "spec": str(spec_path),
        "blend": str(blend),
        "fbx": str(fbx),
        "next": "rig",
        "instructions": (
            f"Upload {fbx.name} to mixamo.com (free). Place the markers on the chin, wrists, elbows, "
            f"knees and groin. Pick animations (idle, walk, run, attack, hit, death). Download the first "
            f"one as FBX 'with skin', the others 'without skin', 24 or 30 fps, and put them all in "
            f"{project.sub(c.name, 'mixamo')}. Then run the rig step."
        ),
    }


def import_mixamo(project: Project, name: str, depth_scale: float | None = None, log=None) -> dict:
    c = project.character(name)
    mix = project.sub(c.name, "mixamo")
    files = sorted(mix.glob("*.fbx")) + sorted(mix.glob("*.FBX"))
    if not files:
        raise StepError(f"no .fbx files in {mix}; download them from Mixamo first")
    tex = model_textures(project, c)
    if "front" not in tex:
        raise StepError("run split first (no views/front.png)")
    out = project.sub(c.name, "model") / f"{c.name}_rigged.blend"
    args = ["--fbx", *files, "--front", tex["front"], "--out", out]
    if "back" in tex:
        args += ["--back", tex["back"]]
    if depth_scale:
        args += ["--depth-scale", depth_scale]
    result = run_blender(project, "import_animations.py", args, log=log)
    actions = result.split("actions=")[-1].split(",") if "actions=" in result else []
    c.done["rig"] = True
    c.notes["rig"] = f"{len(actions)} animations: {', '.join(actions)}"
    project.save()
    return {"ok": True, "character": c.name, "blend": str(out), "animations": actions, "next": "render"}


def render(project: Project, name: str, actions: list[str] | None = None, step: int = 2, elevation: float = 30.0, ppu: float | None = None, log=None) -> dict:
    c = project.character(name)
    model = project.sub(c.name, "model")
    blend = model / f"{c.name}_rigged.blend"
    if not blend.exists():
        blend = model / f"{c.name}.blend"
        if not blend.exists():
            raise StepError("no model yet; run the model step (and the rig step for animations)")
    out = project.sub(c.name, "renders")
    args = ["--out", out, "--directions", project.directions, "--size", project.render_size, "--elevation", elevation, "--step", step]
    if actions:
        args += ["--actions", ",".join(actions)]
    ppu = ppu or c.settings.get("ppu") or _shared_ppu(project)
    if ppu:
        args += ["--ppu", ppu]
    result = run_blender(project, "render_sprites.py", args, blend=blend, log=log)
    manifest = json.loads((out / "manifest.json").read_text())
    c.settings["ppu"] = manifest["ppu"]
    c.done["render"] = True
    c.notes["render"] = f"{sum(a['frames'] for a in manifest['actions'].values())} frames x {len(manifest['directions'])} directions"
    project.save()
    return {"ok": True, "character": c.name, "renders": str(out), "manifest": manifest, "next": "pixelate"}


def _shared_ppu(project: Project) -> float | None:
    """Pixels-per-unit already used by another character, so all share one scale."""
    for other in project.characters.values():
        if other.settings.get("ppu"):
            return float(other.settings["ppu"])
    return None


# ------------------------------------------------------------------ pixelate
def _options_for(project: Project, c: Character, **overrides) -> PixelateOptions:
    st = get_style(c.settings.get("style", project.style))
    pal_file = project.char_dir(c.name) / "palette.hex"
    return PixelateOptions(
        max_size=overrides.get("max_size", st.max_size),
        colors=overrides.get("colors", st.colors),
        palette=Palette.load(pal_file) if pal_file.exists() else None,
        dither=overrides.get("dither", st.dither),
        remove_background=overrides.get("remove_background", False),
        outline=overrides.get("outline"),
    )


def pixelate_renders(project: Project, name: str, outline: str | None = None, log=None) -> dict:
    c = project.character(name)
    renders = project.sub(c.name, "renders")
    manifest_file = renders / "manifest.json"
    if not manifest_file.exists():
        raise StepError("no renders yet; run the render step")
    manifest = json.loads(manifest_file.read_text())
    st = get_style(c.settings.get("style", project.style))
    scale = manifest["size"] / st.max_size  # source px per sprite px, same for every frame
    frames_dir = project.sub(c.name, "frames")
    opts = _options_for(project, c, outline=outline)
    opts.scale = scale
    made = {}
    for action in manifest["actions"]:
        for d in manifest["directions"]:
            src = sorted((renders / action / d).glob("frame_*.png"))
            if not src:
                continue
            results = pixelate_frames([Image.open(p) for p in src], opts)
            out = frames_dir / f"{action}_{d}"
            out.mkdir(parents=True, exist_ok=True)
            for old in out.glob("frame_*.png"):
                old.unlink()
            for i, r in enumerate(results):
                r.image.save(out / f"frame_{i:03d}.png")
            made[f"{action}_{d}"] = len(results)
            if log:
                log(f"{action}/{d}: {len(results)} frames -> {results[0].image.width}x{results[0].image.height}")
    if not made:
        raise StepError("renders folder is empty")
    fps = manifest.get("fps", 12)
    (frames_dir / "animations.json").write_text(json.dumps({"fps": fps, "clips": made}, indent=2) + "\n")
    c.done["pixelate"] = True
    c.notes["pixelate"] = f"{len(made)} clips"
    project.save()
    return {"ok": True, "character": c.name, "frames": str(frames_dir), "clips": made, "fps": fps, "next": "export"}


def pixelate_still(project: Project, name: str, view: str = "front", outline: str | None = "auto", **overrides) -> dict:
    """Direct path: one imported image (style or a view) -> one sprite."""
    c = project.character(name)
    src = project.sub(c.name, "views") / f"{view}.png"
    if view == "style":
        src = _source(project, c, "style") or src
    if not src.exists():
        raise StepError(f"no image for view {view!r}; run split or import a style image")
    opts = _options_for(project, c, outline=outline, remove_background=(view == "style"), **overrides)
    opts.crop = True
    r = pixelate(Image.open(src), opts)
    out = project.sub(c.name, "sprites") / f"{view}.png"
    r.image.save(out)
    r.preview(4).save(out.with_name(f"{view}_x4.png"))
    return {"ok": True, "character": c.name, "sprite": str(out), "size": list(r.image.size), "colors": len(r.palette), "notes": r.notes}


def animate_still(project: Project, name: str, view: str = "front", presets: list[str] | None = None, frames: int = 8, fps: float = 8) -> dict:
    import copy

    c = project.character(name)
    sprite = project.sub(c.name, "sprites") / f"{view}.png"
    if not sprite.exists():
        pixelate_still(project, name, view)
    presets = presets or ["idle"]
    effects = [e for p in presets for e in copy.deepcopy(PRESETS[p])]
    out_frames = animate(np.asarray(Image.open(sprite).convert("RGBA")), effects, frames)
    out = project.sub(c.name, "anim") / "_".join(presets)
    out.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(out_frames):
        Image.fromarray(f, "RGBA").save(out / f"frame_{i:03d}.png")
    save_gif(out_frames, out / "preview.gif", fps=fps, zoom=3)
    return {"ok": True, "character": c.name, "frames": str(out), "gif": str(out / "preview.gif"), "count": len(out_frames)}


# -------------------------------------------------------------------- export
def export(project: Project, name: str, fps: float | None = None) -> dict:
    c = project.character(name)
    frames_dir = project.sub(c.name, "frames")
    clips = {}
    meta = frames_dir / "animations.json"
    clip_fps = fps or (json.loads(meta.read_text())["fps"] if meta.exists() else 8)
    for clip in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
        files = sorted(clip.glob("frame_*.png"))
        if files:
            clips[clip.name] = [Image.open(f) for f in files]
    for anim in sorted(project.sub(c.name, "anim").glob("*/")):
        files = sorted(anim.glob("frame_*.png"))
        if files:
            clips[f"still_{anim.name}"] = [Image.open(f) for f in files]
    if not clips:
        raise StepError("nothing to export; run pixelate (3D path) or animate (still path) first")
    sheet = pack(clips, fps=clip_fps)
    out = project.sub(c.name, "export")
    files = godot_export.export(sheet, out, c.name, f"{project.godot_res_dir.rstrip('/')}/{c.name}")
    c.done["export"] = True
    c.notes["export"] = f"{len(clips)} clips, sheet {sheet.image.width}x{sheet.image.height}"
    project.save()
    return {
        "ok": True,
        "character": c.name,
        "files": {k: str(v) for k, v in files.items()},
        "clips": {k: len(v) for k, v in clips.items()},
        "godot": f"Copy the export folder into your Godot project at {project.godot_res_dir}/{c.name}/ and drop {c.name}.tscn into a scene.",
    }


# ------------------------------------------------------------------- run-all
STEP_FUNCS = {
    "split": split,
    "palette": make_palette,
    "model": build_model,
    "rig": import_mixamo,
    "render": render,
    "pixelate": pixelate_renders,
    "export": export,
}


def run_step(project: Project, name: str, step: str, log=None, **kw) -> dict:
    if step not in STEP_FUNCS:
        raise StepError(f"unknown step {step!r}; choose from {list(STEP_FUNCS)}")
    fn = STEP_FUNCS[step]
    if "log" in fn.__code__.co_varnames:
        kw["log"] = log
    return fn(project, name, **kw)


def run_until_blocked(project: Project, name: str, log=None) -> dict:
    """Run every remaining automatic step; stop at the first that needs a person."""
    c = project.character(name)
    done = []
    for step in ("split", "palette", "model", "rig", "render", "pixelate", "export"):
        if c.done.get(step):
            continue
        try:
            run_step(project, name, step, log=log)
            done.append(step)
        except StepError as e:
            return {"ok": False, "ran": done, "blocked_at": step, "reason": str(e)}
    return {"ok": True, "ran": done, "blocked_at": None}


def which_python() -> str:
    return sys.executable
