# Research: tiles, props, VFX, UI for Godmarrow (2026-10-01)

Scope: Midjourney is the only generator; everything else is numpy/Pillow
post-processing inside PixelForge.

## 1. Isometric tilesets from AI images

- Midjourney `--tile` makes a *square* image wrap at its edges (V6+, V7, V8;
  not Niji; upscaling breaks the seam). It cannot be trusted to output a
  correctly aligned 2:1 diamond. Prompt for a top-down, orthographic, flat-lit
  material texture (`top-down view, flat lighting, no perspective, seamless
  texture of cracked basalt flagstones, dark fantasy, muted teal and gold
  --tile --style raw --no shadow, vignette`) and make the diamond ourselves.
- Square -> 2:1 diamond: rotate 45°, scale Y by 0.5, crop a 2W x W diamond.
  Because the source wraps, every diamond edge matches. Seam QA: wrap-offset by
  half and measure OKLab delta across the seam, feather a few px if needed.
- Variation: 3-4 textures per material (`--c 20`, seeds), one diamond each,
  plus X flips. Random placement hides repetition.
- Transitions: Godot 4 terrains ("corners and sides") need the 47-tile blob
  set. Isometric works: `tile_shape = Isometric`, `tile_layout = Diamond Down`,
  peering bits on iso sides+corners. Free MIT 47-blob isometric example pack:
  https://github.com/leobaray/blobsmith-autotile-wirer (autotile wirer plugin).
  Generation: composite material A/B through the 47 corner/side masks with a
  dithered, palette-locked boundary. Alternative: dual-grid, only 16 tiles
  (https://github.com/pablogila/TileMapDual).
- How references did it: Diablo 2 = 3D scenes rendered to 160x80 diamond floor
  tiles + 160-wide wall tiles (DT1); Project Zomboid = painted faked-iso tiles;
  Hades = hand-painted plates; Stoneshard = hand-drawn 1:1 tiles.
  Takeaway: floors = cut diamonds; walls/set pieces = pre-rendered via our
  Blender step or cut from MJ as props, not as tiles.
- No open-source tool cuts a painted iso scene into diamond tiles; a diamond
  cutter + duplicate hashing is a small module to write.

## 2. Props / objects / items

- Prompting: single object, "isometric view" (D2 camera is ~26.57° dimetric),
  `isolated on plain white background, centered, no ground shadow, no text`,
  `--ar 1:1`, one `--sref` for the whole project, `--style raw`. Ask for 2x2
  sheets ("four variations of a broken barrel") and split with `sheet.py`.
- CC0 sources usable as blockout/filler after OKLab palette-mapping: Kenney
  Isometric Miniature Dungeon / Isometric Dungeon Tiles / Tiny Dungeon (CC0),
  OpenGameArt "CC0 Isometric" collection, "Pixel dungeon ISO tileset",
  "Dark Fantasy Isometric Tiles" (CC-BY 4.0), itch.io CC0 isometric tag.

## 3. VFX

- Procedural: Doom-fire cellular automaton (trivial to port; palette-indexed by
  construction), PythonFireFx. CC0/CC-BY sheets on OpenGameArt as fallback.
- Godot 4: GPUParticles2D jitters with "Snap 2D Transforms to Pixel" when the
  emitter moves; use the standard pixel setup (stretch viewport, integer scale,
  nearest filter) so native-res particles get snapped by the viewport, 1-4 px
  palette-colored particle textures, discrete frame-swap instead of scale/alpha
  curves. We can emit those textures + a ParticleProcessMaterial `.tres`.
- Shaders: CONDUIT (14 MIT canvas_item shaders: dissolve, outline, hit flash,
  palette swap, gradient map, glow); godotshaders.com pixel-perfect outline and
  pixel dissolve. Outline shaders clip at texture edges -> pad cutouts by 2 px.
  Palette-swap/gradient-map shaders take a 1D LUT PNG that `palette.py` can
  export.

## 4. UI

- Kits: RUNEWARD dark-fantasy pixel UI (paid, free 77-piece sampler), Kenney
  Pixel UI Pack (CC0, 30 9-slice PNGs), Veyroa fantasy minimal GUI (CC0).
- Fonts (commercial OK): m5x7 / m3x6 / m6x11 (Daniel Linssen, free), Press
  Start 2P (OFL), Pixel Operator (CC0), Kenney Fonts (CC0).
- 9-slice from MJ: prompt an empty ornate frame on plain black, cutout,
  quantize, auto-detect margins by scanning for the first periodic/constant run
  from each edge, validate by stretch-compare in OKLab; Godot NinePatchRect
  takes the margins directly.

## 5. Tools to integrate or imitate

- Aseprite CLI (source-available, not redistributable); LibreSprite (GPL-2,
  CLI); Pixelorama (MIT, Godot-based editor, `--headless --export` CLI,
  Lospec palettes) = good hand-fix editor for our sheets.
- PixelOver (commercial 3D-to-pixel) = imitate, don't integrate.
- pyxelate (MIT): edge-aware (HOG) downsampling + GMM palette; worth porting
  the downsample into `pixelate.py`. SLK_img2pixel (CC0 C) for reference.
- pixel-art-scaler (Python) overlaps `grid.py`; py-super-xbr for upscaling.
- Lospec API: `https://lospec.com/palette-list/{slug}.json`.

## Recommended plan (priority order)

1. `tiles.py: make_floor_tile` - MJ `--tile` square -> seam check -> 2:1 diamond
   (64x32 / 128x64 configurable) -> palette-lock -> N variants + flips -> atlas.
2. `tiles.py: make_blob_terrain` - 47-tile blob set from two materials with a
   dithered boundary; write a wired isometric TileSet `.tres`.
3. `props.py: make_prop` - sheet -> split -> cutout -> edge-aware downsample ->
   quantize -> outline -> 2 px pad -> footprint/origin JSON for Y-sort.
4. `palette.py: fetch_lospec + export_lut` - Lospec palettes, 1D LUT PNG for shaders.
5. `vfx.py` - Doom-fire/smoke/sparks/magic rings rendered in palette indices to
   sheets; particle textures + ParticleProcessMaterial preset.
6. `ui.py: make_nine_slice` - frame cutout, margin detection, NinePatchRect JSON;
   font import presets.
7. `recolor.py: palette_map` - OKLab hue remap of CC0 packs onto the palette.
8. `godot_export.py` - TileSet/atlas/NinePatch resources + Pixelorama-compatible
   sheet+JSON.
