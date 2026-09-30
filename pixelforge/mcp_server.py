"""MCP server so Claude Desktop / Claude Code can drive a project directly.

Start it with ``pixelforge mcp`` (needs ``pip install mcp``).  Claude Desktop
config example (``claude_desktop_config.json``)::

    {"mcpServers": {"pixelforge": {"command": "pixelforge", "args": ["mcp"]}}}

Every tool mirrors a function in :mod:`pixelforge.api` and returns its dict.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import api
from .project import Project


def _project(path: str) -> Project:
    return Project.load(path)


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:  # pragma: no cover
        raise SystemExit("the MCP server needs the 'mcp' package: pip install mcp") from e

    mcp = FastMCP("pixelforge", instructions=(Path(__file__).parent.parent / "docs" / "GUIDE_AI.md").read_text(errors="replace")
                  if (Path(__file__).parent.parent / "docs" / "GUIDE_AI.md").exists() else "PixelForge pipeline tools")

    @mcp.tool()
    def new_project(folder: str, name: str, style: str = "hd") -> dict:
        """Create a project folder. style: 8bit | 16bit | snes | hd."""
        return api.new_project(folder, name, style)

    @mcp.tool()
    def status(project: str) -> dict:
        """Show characters, what is done and what the next step is."""
        return api.status(_project(project))

    @mcp.tool()
    def configure(project: str, style: str | None = None, blender: str | None = None, directions: int | None = None, render_size: int | None = None, godot_res_dir: str | None = None) -> dict:
        """Change project settings."""
        return api.configure(_project(project), style=style, blender=blender, directions=directions, render_size=render_size, godot_res_dir=godot_res_dir)

    @mcp.tool()
    def add_character(project: str, name: str, description: str) -> dict:
        """Add a character with its one-sentence description."""
        p = _project(project)
        r = api.add_character(p, name, description)
        api.set_description(p, r["character"], description)
        return r

    @mcp.tool()
    def prompts(project: str, character: str, sheet_url: str = "[SHEET IMAGE URL]") -> dict:
        """The Midjourney prompts for a character (give the person prompt A first)."""
        return api.get_prompts(_project(project), character, sheet_url)

    @mcp.tool()
    def import_image(project: str, character: str, kind: str, path: str) -> dict:
        """Import an image. kind: sheet | front | back | side | style."""
        return api.import_source(_project(project), character, kind, path)

    @mcp.tool()
    def run_step(project: str, character: str, step: str) -> dict:
        """Run one step: split | palette | model | rig | render | pixelate | export."""
        try:
            return api.run_step(_project(project), character, step)
        except api.StepError as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    def run_all(project: str, character: str) -> dict:
        """Run every remaining automatic step; stops where a person is needed."""
        return api.run_until_blocked(_project(project), character)

    @mcp.tool()
    def quick_sprite(project: str, character: str, view: str = "style", preset: str = "idle") -> dict:
        """No-3D path: one image -> sprite -> animated clip -> Godot export."""
        p = _project(project)
        api.pixelate_still(p, character, view)
        api.animate_still(p, character, view, [preset])
        return api.export(p, character)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
