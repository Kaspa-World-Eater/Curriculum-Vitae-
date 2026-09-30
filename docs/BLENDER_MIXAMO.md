# The 3D step, explained (and how to do it by hand if you want)

You never need to open Blender. This is what the app runs, in case you want
to improve a model yourself or understand what's going on.

## 1. Model (`pixelforge/blender/build_mesh.py`)

Input: `views/front.png` (+ `side.png` for thickness, `back.png` for the back
texture) and `model/<name>_spec.json`.

- The front silhouette is sampled on a 64-column grid.
- Each grid cell gets a **depth**: 0 at the edge, 1 at the middle, from the
  distance to the nearest edge. Wide areas (torso, hood) bulge; thin areas
  (arms, chains) stay thin.
- Two sheets of quads (front and back) are displaced by ±depth × thickness and
  joined at the edge → a rounded, inflated body. Subdivision smooths it.
- Two orthographic cameras stamp the front/back images onto it (UV Project,
  then applied so the UVs are fixed). An unlit **Emission** material mixes the
  two images by which way the surface faces.
- Saves `<name>.blend` and exports `<name>.fbx` (textures embedded).

Improving it by hand: open the `.blend`, sculpt with *Grab* / *Inflate* in
Sculpt mode, or add a separate object (a weapon). Keep the UV maps named
`proj_front` / `proj_back`. Re-export FBX (`File → Export → FBX`, *Selected
Objects*, *Path Mode: Copy*, *Embed Textures*).

## 2. Mixamo

1. mixamo.com → *Upload character* → the `.fbx`.
2. Auto-rigger: drag the markers to chin, wrists, elbows, knees, groin.
   Use *Standard skeleton*, 65 bones or fewer is fine.
3. Search animations. Good Diablo set: `Idle`, `Walking`, `Running`,
   `Sword And Shield Slash` / `Standing Melee Attack`, `Hit Reaction`, `Death`.
   Tick **In Place** for walk/run.
4. Download: Format **FBX Binary**, Skin **With Skin** for the *first*
   animation only, **Without Skin** for the rest, 30 fps, no keyframe reduction.
5. Save all files to `characters/<name>/mixamo/`.

## 3. Rig import (`import_animations.py`)

Imports every FBX, keeps one mesh + armature, turns each file into an action
named after the file, rebuilds the paint material on the imported mesh, saves
`<name>_rigged.blend`.

## 4. Render (`render_sprites.py`)

- Orthographic camera, 30° above the ground (Diablo 2), orbiting in 8 steps.
- Framing pass: samples every action to find the character's largest extent,
  so every frame of every action gets the same framing. `--ppu` (pixels per
  Blender unit) is stored per project and reused, so all characters share one
  scale.
- Eevee, film transparent, 256×256 RGBA PNGs, every 2nd frame (15 fps from a
  30 fps source), `Standard` view transform so the painted colors are exact.
- Writes `renders/manifest.json`.

Hand-run example:

```
blender -b characters\wraith\model\wraith_rigged.blend --python pixelforge\blender\render_sprites.py -- --out characters\wraith\renders --directions 8 --size 256 --elevation 30 --step 2
```

## Why not a "real" model?

You can use one. Any rigged FBX/GLB (Mixamo characters, Sketchfab CC0, your
own) works: drop the animation FBXs into `mixamo/`, skip `model`, and run
`rig` → `render`. The inflated cutout exists so the pipeline works with
nothing but a Midjourney picture.
