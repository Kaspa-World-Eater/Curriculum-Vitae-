# pixelforge

Research and tools for making dark-fantasy pixel art sprites and animations for
games, with first-class Godot 4 export. Work in progress — see `docs/` for the
research notes and `training/` for the model fine-tuning pipeline.

```sh
pip install -e .
pixelforge pixelate render.webp -o sprite.png --remove-bg --crop --outline auto
pixelforge animate sprite.png -o frames --preset idle --preset glow --gif
pixelforge godot --anim "idle=frames/anim_*.png@8" --name wraith --out my_game/sprites/wraith --res-dir res://sprites/wraith
```
