import json

import numpy as np
import pytest
from PIL import Image

from pixelforge import api
from pixelforge.project import Project


def _figure(seed, w=30, h=80):
    rng = np.random.default_rng(seed)
    pal = rng.integers(40, 255, (6, 3)).astype(np.uint8)
    return Image.fromarray(pal[rng.integers(0, 6, (h, w))]).convert("RGBA")


@pytest.fixture
def project(tmp_path):
    api.new_project(tmp_path / "game", "Game", "16bit")
    p = Project.load(tmp_path / "game")
    api.add_character(p, "Test Hero", "a hero with a lantern")
    api.set_description(p, "test_hero", "a hero with a lantern")
    fig = _figure(1)
    sheet = Image.new("RGB", (3 * 30 + 4 * 20, 120), (255, 255, 255))
    for i in range(3):
        sheet.paste(fig, (20 + i * 50, 20))
    sheet.save(tmp_path / "sheet.png")
    style = Image.new("RGB", (100, 200), (0, 0, 0))
    style.paste(fig.resize((60, 160), Image.NEAREST).convert("RGB"), (20, 20))
    style.save(tmp_path / "style.png")
    api.import_source(p, "test_hero", "sheet", tmp_path / "sheet.png")
    api.import_source(p, "test_hero", "style", tmp_path / "style.png")
    return Project.load(tmp_path / "game")


def test_project_roundtrip_and_status(project):
    s = api.status(project)
    c = s["characters"]["test_hero"]
    assert c["next"] == "split" and "import" in c["done"]
    assert set(c["sources"]) == {"sheet", "style"}
    prompts = api.get_prompts(project, "test_hero")
    assert all("a hero with a lantern" in p["prompt"] for p in prompts["prompts"])


def test_split_palette_still_export(project):
    r = api.split(project, "test_hero")
    assert set(r["views"]) == {"front", "side", "back"}
    r = api.make_palette(project, "test_hero")
    assert r["colors"] <= 32  # 16bit style
    r = api.pixelate_still(project, "test_hero", "style")
    assert Image.open(r["sprite"]).mode == "RGBA"
    r = api.animate_still(project, "test_hero", "style", ["idle"], frames=4)
    assert r["count"] == 4
    r = api.export(project, "test_hero")
    assert r["clips"] == {"still_idle": 4}
    files = r["files"]
    assert all(files[k].endswith(ext) for k, ext in (("png", ".png"), ("tres", ".tres"), ("tscn", ".tscn")))
    meta = json.loads(open(files["json"]).read())
    assert "still_idle" in meta["animations"]
    reloaded = Project.load(project.root)
    assert reloaded.characters["test_hero"].done["export"]


def test_run_all_stops_at_blender(project, monkeypatch):
    monkeypatch.setattr(api, "find_blender", lambda p=None: None)
    r = api.run_until_blocked(project, "test_hero")
    assert r["ran"] == ["split", "palette"]
    assert r["blocked_at"] == "model" and "Blender" in r["reason"]


def test_pixelate_renders_from_fake_manifest(project):
    api.split(project, "test_hero")
    api.make_palette(project, "test_hero")
    renders = project.sub("test_hero", "renders")
    manifest = {"directions": ["S", "W"], "size": 128, "fps": 15, "actions": {"walk": {"frames": 3}}}
    (renders / "manifest.json").write_text(json.dumps(manifest))
    for d in manifest["directions"]:
        for i in range(3):
            out = renders / "walk" / d
            out.mkdir(parents=True, exist_ok=True)
            frame = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            frame.paste(_figure(i, 40, 90), (44 + i, 19))
            frame.save(out / f"frame_{i:03d}.png")
    r = api.pixelate_renders(project, "test_hero")
    assert r["clips"] == {"walk_S": 3, "walk_W": 3}
    first = Image.open(project.sub("test_hero", "frames") / "walk_S" / "frame_000.png")
    assert first.size == (128, 128)  # 16bit style: 128 px sprites
    r = api.export(project, "test_hero")
    assert set(r["clips"]) == {"walk_S", "walk_W"}
