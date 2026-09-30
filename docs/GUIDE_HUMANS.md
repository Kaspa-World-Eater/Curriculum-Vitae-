# PixelForge Studio — the short guide

Turn Midjourney pictures into real pixel-art sprites, animated, ready for Godot.
Runs on any Windows laptop. No graphics card needed.

## Install (once)

1. Install **Python 3.11 or newer** from python.org. Tick **"Add Python to PATH"**.
2. Download this repository (green *Code* button → *Download ZIP*) and unzip it.
3. Double-click **`install.bat`**. It sets everything up.
4. Double-click **`PixelForge Studio.bat`** to open the app.

Optional, only for the 3D/animation path:
- **Blender** (free, blender.org). Install it normally; the app finds it.
- A free **Mixamo** account (mixamo.com) for rigging and animations.

## The two paths

**Quick path — one picture → one sprite.** Good for bosses, portraits, items,
and for deciding whether you like the look. No Blender.

**Full path — one character → every animation from 8 directions.** This is the
Diablo 2 way: a rough 3D model is used *behind the scenes* to render frames,
and the app turns those frames into pixel art. You never see the 3D model in
the game.

## Quick path, step by step

1. **New project** → pick an empty folder.
2. **+ Add character** → name it, write one sentence describing it.
3. Step **1. Prompts** → click **Copy C: sprite** → paste into Midjourney.
4. Save the upscaled PNG. Step **2. Import** → *C. Pixel-style image* → choose it.
5. Click **★ Quick path** in the step list → **Make sprite + animate + export**.
6. Your files are in `characters/<name>/export/`. Copy that folder into your
   Godot project and drop the `.tscn` into a scene.

## Full path, step by step

1. Same as above, but at step 3 use **Copy A: sheet**. Midjourney gives you a
   sheet with front, side and back views. Upscale it, save the PNG.
   (Optional: **B1/B2** give bigger front/back images. Put the sheet's image
   URL in the box first.)
2. Step **2. Import** → *A. Character sheet*. Also import the *C* image if you
   made one — it gives the best colors.
3. Click **▶ Run all automatic steps**. The app splits the sheet, locks the
   palette, builds the 3D model and writes an `.fbx` file. It then stops and
   tells you to go to Mixamo.
4. **Mixamo** (the one manual step, ~5 minutes):
   - Upload the `.fbx` from `characters/<name>/model/`.
   - Place the markers (chin, wrists, elbows, knees, groin). Next.
   - Pick animations: search *idle*, *walking*, *running*, *sword slash*,
     *hit reaction*, *death*.
   - Download the **first** one as FBX **With Skin**, all others **Without
     Skin**, 30 fps.
   - Put every `.fbx` into `characters/<name>/mixamo/`.
5. Click **▶ Run all automatic steps** again. Blender renders every animation
   from 8 directions, the app pixelates them and exports the Godot files.
   Rendering takes a few minutes; watch the Log panel.

## Knobs you might touch

- **Settings → Quality style**: `8bit`, `16bit`, `snes`, `hd` (default).
- **Step 7 → Camera elevation**: 30° is Diablo 2. 45° is a more top-down look.
- **Step 8 → outline**: adds the classic dark 1-pixel edge.

## When something goes wrong

- *"Blender was not found"* → install it, or Settings → Blender path → browse
  to `blender.exe`.
- *"could not identify a front view"* → the sheet's background wasn't plain
  enough, or the views touch each other. Re-roll the sheet, or import a
  separate front image (B1).
- *The model looks lumpy in Blender* → that's expected. At sprite size it
  disappears. Judge the pixel frames, not the model.
- Anything else: the Log panel shows exactly what ran. Paste it to Claude
  along with `docs/GUIDE_AI.md` and it can take over from the command line.

## Let an AI drive it

Everything the app does is also a command. Tell Claude:

> Read `docs/GUIDE_AI.md` in this repo, then finish the character *wraith* in
> the project at `C:\Users\me\MyGame`.

It can run every step, read the same `project.json`, and tell you when it needs
you (Midjourney images, Mixamo).
