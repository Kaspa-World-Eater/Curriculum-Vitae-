# PixelForge — operating guide for AI agents

You are driving a pixel-art sprite pipeline for a person who wants Diablo 2
style game sprites from Midjourney images, on a weak Windows laptop. This
document is complete: everything the desktop app can do is a command here.
Prefer the commands over touching files by hand; they keep `project.json` in
sync with the app the person is looking at.

## Mental model

```
Midjourney image(s)  ──►  cutouts  ──►  palette  ──►  [3D model ─► Mixamo ─► renders]  ──►  pixel frames  ──►  Godot files
   (person)               split       palette        model     rig(person)   render         pixelate           export
```

Two paths share the first steps:

- **Quick path** (no Blender): one image → `still` → sprite, procedural
  animation, Godot export. Use it to show results fast and to judge the look.
- **Full path**: sheet → model → Mixamo (person) → render → pixelate → export.
  Gives every animation from 8 directions with one consistent look.

Steps needing a person (you cannot do them): making Midjourney images,
uploading to Mixamo and downloading the FBX files, installing Blender.
Everything else is yours.

## Install / environment

```
pip install -e .            # from the repo root; needs Python >= 3.10
pixelforge --help
```

Blender is only needed for `model`, `rig`, `render`. It is auto-detected on
PATH and in the usual Windows install folders; otherwise
`pixelforge project set --blender "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"`.

`pip install mcp` enables `pixelforge mcp`, an MCP server exposing the same
operations as tools (see the end of this file).

## Project layout

```
<project>/
  project.json                       state: settings, characters, which steps are done
  characters/<name>/
    source/  sheet.png front.png back.png side.png style.png   imported originals (PNG copies)
    views/   front.png side.png back.png                       tight cutouts, transparent background
    palette.hex / palette.png                                  locked palette
    model/   <name>_spec.json <name>.blend <name>.fbx          3D stage (fbx goes to Mixamo)
    mixamo/  *.fbx                                             person drops Mixamo downloads here
    model/   <name>_rigged.blend                               after `rig`
    renders/ manifest.json <action>/<dir>/frame_NNN.png        Blender output, RGBA, render_size px
    frames/  animations.json <action>_<dir>/frame_NNN.png      pixel art frames (sprite size)
    sprites/ <view>.png <view>_x4.png                          quick-path stills
    anim/    <preset>/frame_NNN.png preview.gif                quick-path procedural clips
    export/  <name>.png .json .tres .tscn                      Godot 4 files
```

Directions (8): `S SW W NW N NE E SE` = where the character faces on screen.
Clips are named `<action>_<direction>`, e.g. `walk_SW`.

## Commands

All `project` commands accept `--project <folder>` (or run inside the folder)
and `--json` for machine-readable output. Non-zero exit + `{"ok": false,
"error": ...}` means the step needs something; the error text says what.

```
pixelforge project new <folder> [--name N] [--style hd|snes|16bit|8bit]
pixelforge project status --json
pixelforge project set [--style S] [--blender PATH] [--directions 8] [--render-size 256] [--godot-res-dir res://sprites]

pixelforge project add <character> --describe "<one sentence>"
pixelforge project describe <character> "<one sentence>"
pixelforge project prompts <character> [--reference <sheet image url>] --json
pixelforge project import <character> sheet|front|back|side|style <file>

pixelforge project run <character> split
pixelforge project run <character> palette
pixelforge project run <character> model          # needs Blender; writes model/<name>.fbx for Mixamo
pixelforge project run <character> rig            # needs mixamo/*.fbx from the person
pixelforge project run <character> render [--frame-step 2] [--elevation 30]
pixelforge project run <character> pixelate
pixelforge project run <character> export
pixelforge project run-all <character>            # runs the remaining automatic steps, stops where blocked

pixelforge project still <character> [--view style|front|side|back] [--animate idle glow ...] [--export]
```

Lower-level tools (work on plain files, no project):

```
pixelforge pixelate <images> -o out [--style hd] [--remove-bg --crop --outline auto] [--palette p.hex]
pixelforge frames <frame files> -o dir [--palette p.hex] [--gif]        # consistent animation pixelation
pixelforge animate sprite.png -o dir --preset idle [--effect "sway:amplitude=2,anchor=bottom"] [--gif]
pixelforge rotate sprite.png -o out.png --angle 30 | --flip h | --turn 1 | --spin 12 --gif
pixelforge palette <images> -o p.hex --colors 96
pixelforge pack --anim "walk=dir/*.png@12" -o sheet.png
pixelforge godot --anim "walk=dir/*.png@12" --name hero --out <godot>/sprites/hero --res-dir res://sprites/hero
pixelforge prompt --describe "<sentence>" [--kind sheet|front|back|sprite|item]
```

## The standard procedure

1. `status --json`. Read `characters.<name>.next` and `done`.
2. If there is no character: ask the person for a one-sentence description
   (silhouette, materials, colors, 3–5 signature details) or write one from
   their reference image, then `add`.
3. `prompts <name> --json`. Give the person **prompt A** (sheet) and **prompt C**
   (sprite) verbatim, plus the rules. Ask for the upscaled PNGs.
4. `import <name> sheet <file>` and `import <name> style <file>` (any others they made).
5. `still <name> --view style --animate idle --export` — show them the result
   immediately (`sprites/style_x4.png`, `anim/idle/preview.gif`). Adjust the
   style tier if they want chunkier/finer (`set --style ...`, rerun).
6. `run-all <name>`. It runs split → palette → model, then stops with the
   Mixamo instructions. Relay them to the person exactly as printed
   (upload `model/<name>.fbx`, place markers, pick animations, first download
   *With Skin*, the rest *Without Skin*, 30 fps, save to `mixamo/`).
7. When the FBX files are in place: `run-all <name>` again → rig → render →
   pixelate → export. Rendering prints `PF_PROGRESS` lines; it takes minutes.
8. Tell the person where the Godot files are (`export/`) and how to use them
   (copy the folder to `res://sprites/<name>/`, instance `<name>.tscn`).

## Checking quality (do this, don't assume)

- After `split`: open `views/front.png`; it must be a single figure, tightly
  cropped, transparent background. If it contains two figures or is cut off,
  the sheet had a busy background or touching figures → ask for a re-roll or
  a separate front image (prompt B1) and `import ... front`.
- After `palette`: `palette.png` should contain the accent colors (glow, gold).
  If not, `--colors` higher or import a better style image.
- After `pixelate`: look at `frames/walk_S/frame_000.png` and one `_W`. Check
  the size is the same for every clip (it is by construction) and the
  silhouette reads at 1x. Flicker between frames is prevented by the shared
  palette + stabilization; if a glow pulses badly, that's the source render.
- Every rendered character in a project shares one pixels-per-unit scale
  (`settings.ppu` in project.json) so they are the right size relative to each
  other. To change the global scale, delete `ppu` from every character and
  re-render.

## Failure messages and what to do

| message | action |
|---|---|
| `Blender was not found` | ask the person to install Blender or give the path; `set --blender` |
| `no .fbx files in .../mixamo` | the person hasn't done the Mixamo step yet |
| `none of the FBX files carried a mesh` | one download must be *With Skin* |
| `could not identify a front view` | import a separate front image (prompt B1) |
| `no reliable pixel grid` (note, not an error) | expected for AI images; the style tier decides the size |
| `--ppu ... clips this character` (render warning) | this character is bigger than the shared scale allows; re-render with `--frame-step` unchanged after deleting `ppu` from the *smaller* characters, or accept |
| `Blender failed (exit N)` | read the last lines printed; usually a missing image path or an FBX that isn't from Mixamo |

## What the 3D step actually does (so you can explain it)

`model` builds an "inflated cutout": the front-view silhouette is put on a
grid, each cell's distance from the edge decides how much it bulges forward and
backward, and the front/back images are camera-projected onto the surface as
its texture. Crude up close; convincing at sprite scale. Mixamo auto-rigs it
because it is a humanoid silhouette. `render` circles an orthographic camera
30° above the ground around the animated model, framing every frame of every
action identically. `pixelate` then converts each render with the locked
palette and a fixed scale so all frames match.

## MCP server

`pixelforge mcp` runs an MCP server (stdio) with tools `new_project`, `status`,
`configure`, `add_character`, `prompts`, `import_image`, `run_step`, `run_all`,
`quick_sprite`. Claude Desktop config:

```json
{"mcpServers": {"pixelforge": {"command": "pixelforge", "args": ["mcp"]}}}
```

## Don'ts

- Don't edit `project.json` by hand while the app is open; use the commands.
- Don't put "pixel art" into prompts A/B (texture noise); do keep the same
  description sentence in every prompt.
- Don't re-run `render` for a tweak that `pixelate` can do (style, outline).
- Don't promise animation from Midjourney alone: frame-to-frame consistency
  needs the 3D path.
