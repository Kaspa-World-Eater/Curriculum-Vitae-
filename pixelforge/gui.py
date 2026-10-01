"""PixelForge Studio - the desktop app (Tkinter, ships with Python on Windows).

Everything here calls :mod:`pixelforge.api`; the window is only buttons, text
boxes and previews around those functions.
"""

from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, X, Y, BooleanVar, StringVar, Tk, Toplevel, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageTk

from . import api
from .project import STEPS, Project
from .prompts import DESCRIPTION_TIPS, EXAMPLE_DESCRIPTION
from .styles import STYLES

APP_TITLE = "PixelForge Studio"
HELP_URL = "https://github.com/Kaspa-World-Eater/Curriculum-Vitae-/blob/claude/pixel-art-generation-y6yk25/docs/GUIDE_HUMANS.md"


class Studio:
    def __init__(self, root: Tk, project_path: str | None = None):
        self.root = root
        self.project: Project | None = None
        self.char = StringVar()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False
        self._previews: list = []  # keep PhotoImage refs alive
        root.title(APP_TITLE)
        root.geometry("1180x760")
        icon = Path(__file__).resolve().parent.parent / "assets" / "pixelforge.ico"
        if icon.exists():
            try:
                root.iconbitmap(str(icon))
            except Exception:  # noqa: BLE001  (non-Windows Tk)
                pass
        root.minsize(900, 600)
        self._build()
        root.after(100, self._drain_log)
        if project_path:
            self._open(project_path)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side=TOP, fill=X)
        ttk.Button(bar, text="New project", command=self._new).pack(side=LEFT)
        ttk.Button(bar, text="Open project", command=self._open_dialog).pack(side=LEFT, padx=4)
        ttk.Label(bar, text="  Character:").pack(side=LEFT)
        self.char_box = ttk.Combobox(bar, textvariable=self.char, state="readonly", width=24)
        self.char_box.pack(side=LEFT)
        self.char_box.bind("<<ComboboxSelected>>", lambda e: self._refresh())
        ttk.Button(bar, text="+ Add character", command=self._add_character).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="Settings", command=self._settings).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="Help", command=lambda: webbrowser.open(HELP_URL)).pack(side=RIGHT)
        self.title_label = ttk.Label(bar, text="No project open", font=("Segoe UI", 10, "bold"))
        self.title_label.pack(side=RIGHT, padx=12)

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill=BOTH, expand=True)
        left = ttk.Frame(body, padding=6)
        body.add(left, weight=0)
        ttk.Label(left, text="Steps", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.step_list = ttk.Treeview(left, columns=("state",), show="tree", height=len(STEPS) + 2, selectmode="browse")
        self.step_list.column("#0", width=300)
        for i, (key, title) in enumerate(STEPS):
            self.step_list.insert("", END, iid=key, text=f"{i + 1}. {title}")
        self.step_list.insert("", END, iid="still", text="★ Quick path: sprite + animation from one image")
        self.step_list.pack(fill=Y)
        self.step_list.bind("<<TreeviewSelect>>", lambda e: self._show_step())
        ttk.Button(left, text="▶ Run all automatic steps", command=self._run_all).pack(fill=X, pady=(10, 2))
        ttk.Label(left, text="(stops at any step that needs you)", foreground="#666").pack(anchor="w")

        right = ttk.Panedwindow(body, orient="vertical")
        body.add(right, weight=1)
        self.panel = ttk.Frame(right, padding=10)
        right.add(self.panel, weight=3)
        logf = ttk.Labelframe(right, text="Log", padding=4)
        right.add(logf, weight=1)
        self.log = ScrolledText(logf, height=8, state="disabled", font=("Consolas", 9))
        self.log.pack(fill=BOTH, expand=True)
        self._show_welcome()

    def _clear_panel(self) -> None:
        for w in self.panel.winfo_children():
            w.destroy()
        self._previews.clear()

    def _show_welcome(self) -> None:
        self._clear_panel()
        ttk.Label(self.panel, text=APP_TITLE, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        text = (
            "Turn AI images into real, animated, Godot-ready pixel art.\n\n"
            "1. New project  →  2. Add a character and describe it  →  3. Copy the prompts into Midjourney\n"
            "4. Import the images  →  5. Click ▶ Run all automatic steps.\n\n"
            "The app stops and tells you when it needs you (uploading to Mixamo, or Blender missing).\n"
            "Every step is also a command line an AI can run - see Help."
        )
        ttk.Label(self.panel, text=text, justify=LEFT).pack(anchor="w", pady=10)

    # ----------------------------------------------------------------- project
    def _new(self) -> None:
        folder = filedialog.askdirectory(title="Choose an EMPTY folder for the new project")
        if not folder:
            return
        name = Path(folder).name
        try:
            api.new_project(folder, name)
        except FileExistsError:
            pass
        self._open(folder)

    def _open_dialog(self) -> None:
        folder = filedialog.askdirectory(title="Open a project folder (contains project.json)")
        if folder:
            self._open(folder)

    def _open(self, path: str) -> None:
        try:
            self.project = Project.load(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, str(e))
            return
        self.title_label.config(text=f"{self.project.name}  ·  style: {self.project.style}")
        self._log(f"Opened {self.project.file}")
        names = sorted(self.project.characters)
        self.char_box["values"] = names
        if names:
            self.char.set(names[0])
        self._refresh()

    def _add_character(self) -> None:
        if not self._need_project():
            return
        dlg = Toplevel(self.root)
        dlg.title("New character")
        ttk.Label(dlg, text="Name (e.g. lantern_wraith):").pack(anchor="w", padx=10, pady=(10, 0))
        name = ttk.Entry(dlg, width=40)
        name.pack(padx=10)
        ttk.Label(dlg, text="One-sentence description:").pack(anchor="w", padx=10, pady=(10, 0))
        ttk.Label(dlg, text=DESCRIPTION_TIPS, wraplength=420, foreground="#666").pack(anchor="w", padx=10)
        desc = ScrolledText(dlg, width=60, height=5)
        desc.insert("1.0", EXAMPLE_DESCRIPTION)
        desc.pack(padx=10, pady=4)

        def ok():
            try:
                r = api.add_character(self.project, name.get(), desc.get("1.0", END).strip())
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_TITLE, str(e))
                return
            api.set_description(self.project, r["character"], desc.get("1.0", END).strip())
            dlg.destroy()
            self._open(str(self.project.root))
            self.char.set(r["character"])
            self._refresh()
            self.step_list.selection_set("prompts")

        ttk.Button(dlg, text="Create", command=ok).pack(pady=8)

    def _settings(self) -> None:
        if not self._need_project():
            return
        p = self.project
        dlg = Toplevel(self.root)
        dlg.title("Settings")
        rows = [
            ("Quality style", "style", p.style),
            ("Blender path (blank = find automatically)", "blender", p.blender),
            ("Directions to render (4 / 8 / 16)", "directions", str(p.directions)),
            ("Render size in pixels (256 is plenty)", "render_size", str(p.render_size)),
            ("Godot res:// folder for sprites", "godot_res_dir", p.godot_res_dir),
        ]
        vars_ = {}
        for i, (label, key, val) in enumerate(rows):
            ttk.Label(dlg, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            v = StringVar(value=val)
            vars_[key] = v
            if key == "style":
                ttk.Combobox(dlg, textvariable=v, values=sorted(STYLES), state="readonly", width=12).grid(row=i, column=1, sticky="w")
            elif key == "blender":
                f = ttk.Frame(dlg)
                f.grid(row=i, column=1, sticky="w")
                ttk.Entry(f, textvariable=v, width=48).pack(side=LEFT)
                ttk.Button(f, text="Browse", command=lambda v=v: v.set(filedialog.askopenfilename(title="blender.exe") or v.get())).pack(side=LEFT)
            else:
                ttk.Entry(dlg, textvariable=v, width=40).grid(row=i, column=1, sticky="w")
        found = api.find_blender(p)
        ttk.Label(dlg, text=f"Blender found: {found or 'NO - install from blender.org'}", foreground="#060" if found else "#a00").grid(row=len(rows), column=0, columnspan=2, sticky="w", padx=8)

        def save():
            try:
                api.configure(p, **{k: v.get() for k, v in vars_.items()})
            except Exception as e:  # noqa: BLE001
                messagebox.showerror(APP_TITLE, str(e))
                return
            dlg.destroy()
            self._open(str(p.root))

        ttk.Button(dlg, text="Save", command=save).grid(row=len(rows) + 1, column=1, sticky="e", padx=8, pady=8)

    def _need_project(self) -> bool:
        if self.project is None:
            messagebox.showinfo(APP_TITLE, "Create or open a project first.")
            return False
        return True

    def _need_char(self):
        if not self._need_project():
            return None
        if not self.char.get():
            messagebox.showinfo(APP_TITLE, "Add a character first.")
            return None
        return self.project.character(self.char.get())

    def _refresh(self) -> None:
        if not self.project:
            return
        c = self.project.characters.get(self.char.get())
        for key, title in STEPS:
            mark = "✔ " if c and c.done.get(key) else "    "
            i = [k for k, _ in STEPS].index(key)
            self.step_list.item(key, text=f"{mark}{i + 1}. {title}")
        sel = self.step_list.selection()
        if sel:
            self._show_step()

    # ------------------------------------------------------------------- steps
    def _show_step(self) -> None:
        sel = self.step_list.selection()
        if not sel or not self.project:
            return
        key = sel[0]
        c = self.project.characters.get(self.char.get())
        self._clear_panel()
        if c is None:
            ttk.Label(self.panel, text="Add a character first (+ Add character).").pack(anchor="w")
            return
        getattr(self, f"_step_{key}")(c)

    def _heading(self, text: str, sub: str = "") -> None:
        ttk.Label(self.panel, text=text, font=("Segoe UI", 13, "bold")).pack(anchor="w")
        if sub:
            ttk.Label(self.panel, text=sub, wraplength=760, justify=LEFT, foreground="#444").pack(anchor="w", pady=(2, 8))

    def _step_prompts(self, c) -> None:
        self._heading("1. Midjourney prompts", "Describe the character once; the prompts below are written for you. Copy each into Midjourney.")
        ttk.Label(self.panel, text="Description:").pack(anchor="w")
        desc = ScrolledText(self.panel, height=3, width=100)
        desc.insert("1.0", c.description or EXAMPLE_DESCRIPTION)
        desc.pack(fill=X)
        ttk.Label(self.panel, text=DESCRIPTION_TIPS, foreground="#666", wraplength=760).pack(anchor="w")
        ref = StringVar(value="[SHEET IMAGE URL]")
        f = ttk.Frame(self.panel)
        f.pack(fill=X, pady=4)
        ttk.Label(f, text="Sheet image URL for the B prompts (after you made the sheet):").pack(side=LEFT)
        ttk.Entry(f, textvariable=ref, width=40).pack(side=LEFT, padx=4)
        box = ScrolledText(self.panel, height=18, font=("Consolas", 9))
        box.pack(fill=BOTH, expand=True, pady=4)

        def regen():
            r = api.set_description(self.project, c.name, desc.get("1.0", END).strip())
            r = api.get_prompts(self.project, c.name, ref.get().strip() or "[SHEET IMAGE URL]")
            box.delete("1.0", END)
            for pr in r["prompts"]:
                box.insert(END, f"{pr['title']}\n{pr['purpose']}\n\n{pr['prompt']}\n\n{'-' * 100}\n\n")
            box.insert(END, "RULES\n" + "\n".join(f"• {x}" for x in r["rules"]))
            self._refresh()

        def copy(kind):
            api.set_description(self.project, c.name, desc.get("1.0", END).strip())
            r = api.get_prompts(self.project, c.name, ref.get().strip() or "[SHEET IMAGE URL]")
            text = next(p["prompt"] for p in r["prompts"] if p["key"] == kind)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self._log(f"Copied prompt {kind.upper()} to the clipboard")

        btns = ttk.Frame(self.panel)
        btns.pack(fill=X)
        ttk.Button(btns, text="Update prompts", command=regen).pack(side=LEFT)
        for kind, label in (("sheet", "Copy A: sheet"), ("front", "Copy B1: front"), ("back", "Copy B2: back"), ("sprite", "Copy C: sprite"), ("item", "Copy D: item")):
            ttk.Button(btns, text=label, command=lambda k=kind: copy(k)).pack(side=LEFT, padx=2)
        regen()

    def _step_import(self, c) -> None:
        self._heading("2. Import the images", "Save Midjourney's upscaled PNGs, then pick them here. The sheet (A) is required for the 3D path; a style image (C) is required for the quick path and improves the palette.")
        rows = [("sheet", "A. Character sheet (front / side / back)"), ("front", "B1. Front view (optional)"), ("back", "B2. Back view (optional)"), ("side", "Side view (optional)"), ("style", "C. Pixel-style image (palette / quick path)")]
        for kind, label in rows:
            f = ttk.Frame(self.panel)
            f.pack(fill=X, pady=3)
            ttk.Label(f, text=label, width=44).pack(side=LEFT)
            state = ttk.Label(f, text=("✔ " + c.sources[kind]) if kind in c.sources else "—", foreground="#060" if kind in c.sources else "#888")
            state.pack(side=RIGHT)

            def pick(kind=kind, state=state):
                path = filedialog.askopenfilename(title=f"Choose the {kind} image", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
                if path:
                    self._run(lambda: api.import_source(self.project, c.name, kind, path), after=lambda r: self._show_step())

            ttk.Button(f, text="Choose file…", command=pick).pack(side=LEFT, padx=6)
        self._preview_row([self.project.root / p for p in c.sources.values()], 180)

    def _step_split(self, c) -> None:
        self._heading("3. Split the sheet & cut out", "Finds each figure on the sheet, removes the white background and saves front / side / back cutouts.")
        ttk.Button(self.panel, text="Run split", command=lambda: self._run(lambda: api.split(self.project, c.name), after=lambda r: self._show_step())).pack(anchor="w")
        self._preview_row(sorted(self.project.sub(c.name, "views").glob("*.png")), 260)

    def _step_palette(self, c) -> None:
        self._heading("4. Lock the palette", "Picks the colors once (from the style image and the views) so every frame of every animation uses the same set.")
        ttk.Button(self.panel, text="Build palette", command=lambda: self._run(lambda: api.make_palette(self.project, c.name), after=lambda r: self._show_step())).pack(anchor="w")
        sw = self.project.char_dir(c.name) / "palette.png"
        if sw.exists():
            self._preview_row([sw], 120)
            ttk.Label(self.panel, text=c.notes.get("palette", "")).pack(anchor="w")

    def _step_model(self, c) -> None:
        self._heading("5. Build the 3D model", "Makes an 'inflated cutout' model from the front view, paints it with the front/back art, and writes an FBX for Mixamo. Needs Blender installed (free) - nothing to model by hand.")
        found = api.find_blender(self.project)
        ttk.Label(self.panel, text=f"Blender: {found or 'not found - install from blender.org or set the path in Settings'}", foreground="#060" if found else "#a00").pack(anchor="w")
        ttk.Button(self.panel, text="Build model", command=lambda: self._run(lambda: api.build_model(self.project, c.name, log=self._log), after=self._after_model)).pack(anchor="w", pady=4)
        ttk.Label(self.panel, text=c.notes.get("model", ""), foreground="#444").pack(anchor="w")

    def _after_model(self, r) -> None:
        self._show_step()
        messagebox.showinfo("Next: Mixamo", r["instructions"])

    def _step_rig(self, c) -> None:
        mix = self.project.sub(c.name, "mixamo")
        self._heading("6. Rig + animate on Mixamo", "This is the one step that needs you, and it is free:\n"
                      f"1. Go to mixamo.com and sign in (free Adobe account).\n2. Upload  {self.project.sub(c.name, 'model') / (c.name + '.fbx')}\n"
                      "3. Place the markers on chin, wrists, elbows, knees, groin. Next.\n4. Pick animations: idle, walk, run, attack, hit, death (search the names).\n"
                      "5. Download the FIRST one as FBX 'With Skin', every other one 'Without Skin' (30 fps).\n"
                      f"6. Put all the .fbx files in:\n    {mix}\n7. Click Import below.")
        ttk.Button(self.panel, text="Open the mixamo folder", command=lambda: webbrowser.open(str(mix))).pack(anchor="w")
        ttk.Button(self.panel, text="Import Mixamo files", command=lambda: self._run(lambda: api.import_mixamo(self.project, c.name, log=self._log), after=lambda r: self._show_step())).pack(anchor="w", pady=4)
        files = sorted(mix.glob("*.fbx")) + sorted(mix.glob("*.FBX"))
        ttk.Label(self.panel, text=f"{len(files)} FBX file(s) in the folder. {c.notes.get('rig', '')}").pack(anchor="w")

    def _step_render(self, c) -> None:
        self._heading("7. Render from 8 directions", "Blender renders every animation from every direction with a Diablo-style camera. Takes a few minutes; watch the log.")
        f = ttk.Frame(self.panel)
        f.pack(anchor="w")
        step = StringVar(value="2")
        elev = StringVar(value="30")
        ttk.Label(f, text="Every Nth frame:").pack(side=LEFT)
        ttk.Entry(f, textvariable=step, width=4).pack(side=LEFT, padx=4)
        ttk.Label(f, text="Camera elevation °:").pack(side=LEFT)
        ttk.Entry(f, textvariable=elev, width=4).pack(side=LEFT, padx=4)
        ttk.Button(self.panel, text="Render", command=lambda: self._run(lambda: api.render(self.project, c.name, step=int(step.get()), elevation=float(elev.get()), log=self._log), after=lambda r: self._show_step())).pack(anchor="w", pady=4)
        ttk.Label(self.panel, text=c.notes.get("render", "")).pack(anchor="w")
        renders = self.project.sub(c.name, "renders")
        sample = sorted(renders.glob("*/S/frame_000.png"))[:1] + sorted(renders.glob("*/W/frame_000.png"))[:1]
        self._preview_row(sample, 200)

    def _step_pixelate(self, c) -> None:
        self._heading("8. Pixelate", f"Turns every rendered frame into pixel art in the '{self.project.style}' style with the locked palette. Frames stay stable between each other (no flicker).")
        outline = BooleanVar(value=False)
        ttk.Checkbutton(self.panel, text="Add a dark 1-pixel outline", variable=outline).pack(anchor="w")
        ttk.Button(self.panel, text="Pixelate all frames", command=lambda: self._run(lambda: api.pixelate_renders(self.project, c.name, outline="auto" if outline.get() else None, log=self._log), after=lambda r: self._show_step())).pack(anchor="w", pady=4)
        frames = self.project.sub(c.name, "frames")
        sample = sorted(frames.glob("*_S/frame_000.png"))[:2] + sorted(frames.glob("*_W/frame_000.png"))[:1]
        self._preview_row(sample, 200, zoom=True)

    def _step_export(self, c) -> None:
        self._heading("9. Export for Godot", "Packs every clip into one sprite sheet and writes the Godot 4 files (.tres SpriteFrames + .tscn AnimatedSprite2D).")
        ttk.Button(self.panel, text="Export", command=lambda: self._run(lambda: api.export(self.project, c.name), after=self._after_export)).pack(anchor="w")
        ttk.Label(self.panel, text=c.notes.get("export", "")).pack(anchor="w")
        sheet = self.project.sub(c.name, "export") / f"{c.name}.png"
        if sheet.exists():
            self._preview_row([sheet], 300)

    def _after_export(self, r) -> None:
        self._show_step()
        messagebox.showinfo("Exported", r["godot"])

    def _step_still(self, c) -> None:
        self._heading("★ Quick path: one image → sprite + animation", "No 3D. Uses the style image (C) or the front view. Good for bosses, portraits, items, and for judging the look.")
        view = StringVar(value="style" if "style" in c.sources else "front")
        f = ttk.Frame(self.panel)
        f.pack(anchor="w")
        ttk.Label(f, text="Image:").pack(side=LEFT)
        ttk.Combobox(f, textvariable=view, values=["style", "front", "side", "back"], state="readonly", width=8).pack(side=LEFT, padx=4)
        preset = StringVar(value="idle")
        ttk.Label(f, text="Animation:").pack(side=LEFT)
        ttk.Combobox(f, textvariable=preset, values=["idle", "cloak", "hover", "flame", "glow", "grass"], state="readonly", width=8).pack(side=LEFT, padx=4)
        ttk.Button(self.panel, text="Make sprite", command=lambda: self._run(lambda: api.pixelate_still(self.project, c.name, view.get()), after=lambda r: self._show_step())).pack(anchor="w", pady=2)
        ttk.Button(self.panel, text="Make sprite + animate + export", command=lambda: self._run(lambda: (api.animate_still(self.project, c.name, view.get(), [preset.get()]), api.export(self.project, c.name))[-1], after=self._after_export)).pack(anchor="w", pady=2)
        sprites = sorted(self.project.sub(c.name, "sprites").glob("*_x4.png"))
        self._preview_row(sprites, 300)

    # ---------------------------------------------------------------- helpers
    def _preview_row(self, paths, height: int, zoom: bool = False) -> None:
        row = ttk.Frame(self.panel)
        row.pack(anchor="w", pady=8)
        for p in paths:
            p = Path(p)
            if not p.exists():
                continue
            try:
                im = Image.open(p).convert("RGBA")
            except Exception:  # noqa: BLE001
                continue
            bg = Image.new("RGBA", im.size, (40, 40, 40, 255))
            im = Image.alpha_composite(bg, im)
            s = height / im.height
            size = (max(1, int(im.width * s)), height)
            im = im.resize(size, Image.NEAREST if (zoom or s > 1) else Image.LANCZOS)
            photo = ImageTk.PhotoImage(im)
            self._previews.append(photo)
            cell = ttk.Frame(row)
            cell.pack(side=LEFT, padx=4)
            ttk.Label(cell, image=photo).pack()
            ttk.Label(cell, text=p.name, foreground="#666").pack()

    def _run(self, fn, after=None) -> None:
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Still working on the previous step - watch the log.")
            return
        self.busy = True

        def work():
            try:
                r = fn()
                self._log("OK: " + ", ".join(f"{k}={v}" for k, v in r.items() if k in ("character", "next", "colors", "count", "clips", "animations")))
                if after:
                    self.root.after(0, lambda: after(r))
            except api.StepError as e:
                self._log("STOPPED: " + str(e))
                self.root.after(0, lambda: messagebox.showwarning(APP_TITLE, str(e)))
            except Exception as e:  # noqa: BLE001
                self._log("ERROR: " + str(e) + "\n" + traceback.format_exc())
                self.root.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))
            finally:
                self.busy = False
                self.root.after(0, self._refresh)

        threading.Thread(target=work, daemon=True).start()

    def _run_all(self) -> None:
        c = self._need_char()
        if c is None:
            return
        self._run(lambda: api.run_until_blocked(self.project, c.name, log=self._log), after=self._after_run_all)

    def _after_run_all(self, r) -> None:
        self._refresh()
        if r["blocked_at"]:
            messagebox.showinfo(APP_TITLE, f"Ran: {', '.join(r['ran']) or 'nothing'}.\n\nStopped at step '{r['blocked_at']}':\n{r['reason']}")
            self.step_list.selection_set(r["blocked_at"])
        else:
            messagebox.showinfo(APP_TITLE, f"All steps done: {', '.join(r['ran'])}")

    def _log(self, text: str) -> None:
        self.log_queue.put(text)

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log.configure(state="normal")
                self.log.insert(END, line + "\n")
                self.log.see(END)
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)


def main(project_path: str | None = None) -> None:
    root = Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:  # noqa: BLE001
        pass
    Studio(root, project_path)
    root.mainloop()


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else None)
