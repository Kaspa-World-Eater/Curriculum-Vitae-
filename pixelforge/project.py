"""Project files: one folder per game, one sub-folder per character.

Both the desktop app and the command line work on the same ``project.json``, so
a person can click through a step and an AI can run the next one from a shell
and they never disagree about the state of things.

Layout::

    MyGame/
      project.json
      characters/<name>/
        source/     sheet.png  front.png  back.png  style.png   (what you import)
        views/      front.png  side.png  back.png              (cutouts from the sheet)
        palette.hex
        model/      <name>_spec.json  <name>.blend  <name>.fbx  (3D stage)
        mixamo/     *.fbx                                       (animations you download)
        renders/    <action>/<direction>/frame_000.png          (Blender output)
        frames/     <action>_<direction>/frame_000.png          (pixelated)
        anim/       <preset>/...                                (procedural, from a still)
        export/     <name>.png .json .tres .tscn                (Godot)
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_FILE = "project.json"
SOURCE_KINDS = ("sheet", "front", "back", "side", "quarter", "style")
DIRECTIONS_8 = ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
STEPS = [
    ("prompts", "Write the Midjourney prompts"),
    ("import", "Import the images"),
    ("split", "Split the sheet into views and cut out the background"),
    ("palette", "Lock the color palette"),
    ("model", "Build the 3D model (Blender)"),
    ("rig", "Rig + animate on Mixamo, import the FBX files"),
    ("render", "Render every animation from 8 directions (Blender)"),
    ("pixelate", "Turn the renders into pixel art"),
    ("export", "Export sprite sheets + Godot files"),
]


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not s:
        raise ValueError("name must contain letters or digits")
    return s


@dataclass
class Character:
    name: str
    description: str = ""
    sources: dict[str, str] = field(default_factory=dict)  # kind -> relative path
    done: dict[str, bool] = field(default_factory=dict)  # step key -> finished
    notes: dict[str, str] = field(default_factory=dict)  # step key -> last message
    settings: dict = field(default_factory=dict)  # per-character overrides


@dataclass
class Project:
    name: str
    root: Path
    style: str = "hd"
    blender: str = ""  # path to blender executable, "" = look on PATH
    directions: int = 8
    render_size: int = 256
    godot_res_dir: str = "res://sprites"
    characters: dict[str, Character] = field(default_factory=dict)

    # ---------------------------------------------------------------- paths
    @property
    def file(self) -> Path:
        return self.root / PROJECT_FILE

    def char_dir(self, name: str) -> Path:
        return self.root / "characters" / name

    def sub(self, name: str, part: str) -> Path:
        p = self.char_dir(name) / part
        p.mkdir(parents=True, exist_ok=True)
        return p

    def character(self, name: str) -> Character:
        key = slugify(name)
        if key not in self.characters:
            raise KeyError(f"no character {name!r}; have {sorted(self.characters)}")
        return self.characters[key]

    # ------------------------------------------------------------ persistence
    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "name": self.name,
            "style": self.style,
            "blender": self.blender,
            "directions": self.directions,
            "render_size": self.render_size,
            "godot_res_dir": self.godot_res_dir,
            "characters": {k: asdict(c) for k, c in self.characters.items()},
        }
        self.file.write_text(json.dumps(data, indent=2) + "\n")
        return self.file

    @classmethod
    def create(cls, root: str | Path, name: str, **kw) -> "Project":
        root = Path(root)
        if (root / PROJECT_FILE).exists():
            raise FileExistsError(f"{root / PROJECT_FILE} already exists; open it instead")
        p = cls(name=name, root=root, **kw)
        p.save()
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        path = Path(path)
        file = path if path.name == PROJECT_FILE else path / PROJECT_FILE
        if not file.exists():
            raise FileNotFoundError(f"no {PROJECT_FILE} in {file.parent}")
        data = json.loads(file.read_text())
        chars = {k: Character(**c) for k, c in data.get("characters", {}).items()}
        return cls(
            name=data["name"],
            root=file.parent,
            style=data.get("style", "hd"),
            blender=data.get("blender", ""),
            directions=int(data.get("directions", 8)),
            render_size=int(data.get("render_size", 256)),
            godot_res_dir=data.get("godot_res_dir", "res://sprites"),
            characters=chars,
        )

    @classmethod
    def find(cls, start: str | Path = ".") -> "Project":
        """Load the project in ``start`` or the nearest parent folder."""
        p = Path(start).resolve()
        for candidate in [p, *p.parents]:
            if (candidate / PROJECT_FILE).exists():
                return cls.load(candidate)
        raise FileNotFoundError(f"no {PROJECT_FILE} found in {p} or its parents")

    def summary(self) -> dict:
        return {
            "name": self.name,
            "root": str(self.root),
            "style": self.style,
            "blender": self.blender,
            "directions": self.directions,
            "render_size": self.render_size,
            "godot_res_dir": self.godot_res_dir,
            "steps": [{"key": k, "title": t} for k, t in STEPS],
            "characters": {
                k: {
                    "description": c.description,
                    "sources": c.sources,
                    "done": [s for s, _ in STEPS if c.done.get(s)],
                    "next": next((s for s, _ in STEPS if not c.done.get(s)), None),
                    "notes": c.notes,
                }
                for k, c in self.characters.items()
            },
        }
