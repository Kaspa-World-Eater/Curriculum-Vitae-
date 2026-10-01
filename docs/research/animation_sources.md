# Research: free animation sources + headless retargeting (2026-10-01)

## Sources (verified)

| Source | License | Format / skeleton | Verdict |
|---|---|---|---|
| **Quaternius Universal Animation Library** (free Standard tier; Pro $10 = 120+ clips) https://quaternius.com/packs/universalanimationlibrary.html | **CC0** | single GLB, Rigify `DEF-*` names, 46 clips incl. Idle_Loop, Walk_Loop, Jog_Fwd_Loop, Sprint_Loop, Sword_Attack, Hit_Chest/Head, Death01, Spell_Simple_* , Roll, Crouch, Jump | **Adopted.** Vendored at `assets/animations/`. |
| CMU mocap (cgspeed BVH; mirrors github.com/una-dinosauria/cmu-mocap, HF gbionics/cmu-fbx) | free for commercial use, credit CMU, don't resell raw data | BVH/FBX, MotionBuilder names (≈ Mixamo without prefix) | Secondary: bulk variety (falls, stagger); raw, needs cleanup. |
| 100STYLE (Zenodo 8127870) | CC BY 4.0 | BVH, 28 bones; 100 locomotion styles (zombie, drunk, heavy…) | Later: monster/NPC walk variety. No attacks. |
| Bandai Namco motion dataset | CC BY-**NC** | — | **No** (non-commercial). |
| Ubisoft LaFAN1 | CC BY-NC-ND | — | No. |
| SFU mocap, AMASS | research only | — | No. |
| Rokoko free packs (263 clips, Mixamo skeleton) | commercial OK, form-gated download, redistribution unclear | FBX | Manual one-off only; don't commit. |
| Mixamo packs on GitHub | Adobe ToS forbids redistribution | — | Avoid in an open repo. |

## Retargeting (headless `blender -b --python`)

- All of `import_anim.bvh`, `import_scene.gltf`, constraints and
  `nla.bake(visual_keying=True)` work in background mode; avoid operators that
  need a VIEW_3D context.
- BacteriaJun/BVH-Motion-Retargeter (MIT, active): `core/retarget_engine.py`
  `transfer_animation()` is a plain-argument engine (COPY_ROTATION + hips
  COPY_LOCATION + bake), with a Mixamo profile. Good reference.
- Rokoko Studio Live addon (LGPL) works but is GUI/props heavy. Expy Kit has no
  license file. Keemap/ReNim stale or node-based. ARP batch needs paid ARP.
- PixelForge's own approach (implemented in `rig_character.py`): per frame,
  per bone, apply the source bone's *world-space rotation delta from rest* to
  our bone's rest, after aligning rest directions (handles T-pose source vs
  A-pose target). Hips translation copied, scaled by hip height. ~150 lines,
  no add-on.

## Related projects

- Make-It-Animatable (MIT, CVPR'25): learned auto-rig to the Mixamo skeleton,
  GPU needed — candidate replacement for the hand-built rig later.
- UniRig (MIT) free-form skeletons; autorig-workbench (GPL, alpha).
- Blender sprite renderers: SpriteSheetMaker (MIT, active; alpha stepping),
  blender-spritesheets (MIT; JSON sidecar + Godot importer),
  DirectionalSpriteBatchRender (GPL, dead). Little to reuse beyond ideas.
- pixel-2d-game-art (no license) tried SD/AnimateDiff for frames and pivoted
  to 3D + retarget — the same conclusion we reached.
