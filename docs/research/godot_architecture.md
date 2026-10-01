# Research: Godot 4 isometric ARPG architecture for Godmarrow (2026-10-01)

## Templates / demos

- Official `godot-demo-projects/2d/isometric` (MIT): Y-sorted iso level,
  colliders at object bases, blob shadows, PointLight2D shadows. The reference
  for sorting + collider conventions (migrate TileMap -> TileMapLayer).
- nezvers/Godot-GameTemplate (MIT code, CC-BY assets): menus, input rebinding,
  scene transitions, pooling, enemy A* AI, wave spawning, saving. Best
  whole-game scaffolding.
- MichaelTen/Godot-8-Direction-TileMapLayer-Script (MIT): tiny 8-direction +
  right-click-move example; read, don't adopt.
- No maintained open-source Godot 4 "Diablo clone" exists. Write the
  character/direction code ourselves (it is small).
- Click-to-move: NavigationRegion2D baked from the TileMapLayer +
  NavigationAgent2D, or AStarGrid2D over the iso sub-tile grid (D2 style).

## Importers

- godot-aseprite-wizard (MIT): EditorImportPlugin pattern, one AtlasTexture per
  frame over one sheet, tag -> animation.
- DRS90/dot-aseprite-importer (MIT): facing grid -> `idle_left_up`-style names
  and AnimationPlayer sync. Same naming idea as our `<anim>_<dir>`.
- Our pipeline already writes `.tres`/`.tscn`; Godot's EditorFileSystem picks
  them up. An importer addon (`sheet.json` -> SpriteFrames, `AtlasTexture.margin`
  for trimmed frames) is optional polish. Minimal addon skeleton is in the
  original report (plugin.cfg + EditorPlugin + EditorImportPlugin).

## Crisp pixel art settings (project.godot)

- `rendering/textures/canvas_textures/default_texture_filter = Nearest`
- stretch `mode = canvas_items`, `scale_mode = integer`, `aspect = expand`
  (HD-pixel with 224 px characters at 1080p = 1:1; 4K = 2x)
- `rendering/2d/snap/snap_2d_transforms_to_pixel = true`; no Camera2D
  smoothing (or snap it)
- MSAA 2D off; PNG imports lossless, no mipmaps
- Iso TileMapLayer: `tile_shape = Isometric`, `tile_layout = Diamond Down`,
  `tile_size = (W, W/2)`; tall tiles use `texture_origin` and `y_sort_origin`
- Y-sort: Ground layer sorted alone; a `World` Node2D (y_sort) holding wall
  layers, props and actors as siblings; actor origin at the feet.
- Lighting: PointLight2D + LightOccluder2D at wall bases for torches/fog on the
  *environment*; keep characters palette-locked (no normal maps, or a quantize
  post-shader). Palette-swap LUT shaders (KoBeWi, CONDUIT, MIT) give D2-style
  gear recolors for free.

## Tile size / resolution proposal

- Base viewport 1920x1080, 1 texel = 1 pixel. Hero (~224 px) ~ 1/4.8 of screen.
- Floor tile 256x128 (2:1, power of two). Nav grid 64x32 or 32x16.
- Blender camera for *tiles*: elevation atan(0.5) = 26.57° (true 2:1). Our
  character render default is 30°; switch to 26.57° so feet ellipses match
  tile diamonds (Diablo 2 was ~26.57° too).
- D2 reference: 160x80 floor tiles, 5x5 subtiles of 32x16; characters
  ~70-110 px tall at 640x480.

## License-clean building blocks (MIT)

- Inventory/loot: expressobits/inventory-system, peter-kish/gloot, SELODev loot.
- Stats/abilities: OctoD/godot_gameplay_attributes (+ abilities).
- FSM: maindtim/state-machine-lite. Dialogue: nathanhoad/godot_dialogue_manager.
- Save: youssof20/savestate. Fog of war: TABmk/godot-4-fog-of-war.
- Procgen: AlexeyBond/godot-constraint-solving (WFC over TileMapLayer),
  apples/dungeon-gen-bsp. Pathfinding: built-in AStarGrid2D / NavigationServer2D.

## Recommended architecture

```
Level (Node2D)
├─ Ground (TileMapLayer, y_sort, 256x128 iso Diamond Down)
├─ World (Node2D, y_sort)
│   ├─ Walls (TileMapLayer, y_sort, LightOccluder2D at bases)
│   ├─ Props
│   └─ Actor instances
├─ NavigationRegion2D / AStarGrid2D
├─ Lights (PointLight2D torches, mask: ground only)
└─ CanvasModulate + fog CanvasLayer

Actor (CharacterBody2D, origin at feet)
├─ CollisionShape2D (feet)
├─ Shadow (Sprite2D blob, z_index -1)
├─ Sprite (AnimatedSprite2D, SpriteFrames .tres from PixelForge)
├─ AnimationPlayer (events: hit frames, SFX, hitboxes)
├─ NavigationAgent2D
├─ StateMachine (Idle/Walk/Attack/Cast/Hit/Die)
└─ Stats (AttributeContainer)
```

Direction from velocity (screen space already projected):
`facing = wrapi(roundi(velocity.angle() / (PI/4)), 0, 8)`; play
`"%s_%s" % [anim, DIRS[facing]]`; keep `$Sprite.frame` across direction
changes so the cycle does not restart.

Pipeline contract: per character `sheet.png` (+ per-anim sheets if large),
`sheet.json` (cell size, fps, loop, pivot, palette), `SpriteFrames.tres`,
`<name>.tscn`, palette LUT `.png`.
