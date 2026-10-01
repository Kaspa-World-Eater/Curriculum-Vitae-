# Animation library

`quaternius_ual_standard.glb` — Quaternius *Universal Animation Library*
(Standard tier), **CC0 1.0** (see `LICENSE_quaternius_ual.txt`). 46 humanoid
clips on a Rigify-named skeleton (`DEF-*`). PixelForge retargets them onto the
generated `mixamorig:*` rig headlessly (`pixelforge/blender/rig_character.py`),
so characters get real motion without Mixamo. Source:
https://quaternius.com/packs/universalanimationlibrary.html

Default clip mapping (override with `--clip name=Source_Clip`):

| PixelForge clip | library clip | loop |
|---|---|---|
| idle | Idle_Loop | yes |
| walk | Walk_Loop | yes |
| run | Jog_Fwd_Loop | yes |
| attack | Sword_Attack | no |
| hit | Hit_Chest | no |
| death | Death01 | no |
| cast | Spell_Simple_Shoot | no |
