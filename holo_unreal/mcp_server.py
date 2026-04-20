"""FastMCP server exposing holo-unreal to Claude Code.

Registers as an MCP server so Claude Code can call these tools directly
instead of shelling out to the CLI. Install once via:

    claude mcp add -s user holo-unreal -- python -m holo_unreal.mcp_server

Then restart Claude Code. Tools show up as `ue_*` (toolkit) and `hue_*`
(vision).

Stdio transport only — the FastMCP default. Requires the `mcp` extra:
`pip install claude-holo-unreal[mcp]`.
"""
from __future__ import annotations

import sys

# Force UTF-8 so any window title with a non-cp1252 character won't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "MCP SDK not installed. Run: pip install claude-holo-unreal[mcp]"
    ) from exc

from . import __version__
from ._env import hai_api_key
from .toolkit import (
    close_editor,
    collect_errors,
    cook,
    doctor,
    enable_remote_execution,
    fixup_redirectors,
    launch_editor,
    package,
    project_info,
    py_file_in_editor,
    py_in_editor,
    read_log,
    resave_packages,
    run_commandlet,
)

mcp = FastMCP("holo-unreal")


# -------------------------------------------------------- meta / info

@mcp.tool()
def hue_info() -> dict:
    """Report holo-unreal version and which backends are configured."""
    return {
        "ok": True,
        "version": __version__,
        "hai_api_key_set": bool(hai_api_key()),
    }


# -------------------------------------------------------------- UE toolkit

@mcp.tool()
def ue_info(project: str | None = None) -> dict:
    """Project + engine + running state."""
    return project_info(project)


@mcp.tool()
def ue_launch(project: str | None = None) -> dict:
    """Spawn UnrealEditor.exe with the project (detached)."""
    return launch_editor(project)


@mcp.tool()
def ue_close(force: bool = False) -> dict:
    """Close every running UnrealEditor.exe (WM_CLOSE; set force=True for taskkill /F)."""
    return close_editor(force=force)


@mcp.tool()
def ue_log(
    project: str | None = None,
    grep: str | None = None,
    tail: int = 200,
) -> dict:
    """Read the project log. `grep` is a case-insensitive regex."""
    return read_log(project, grep=grep, tail=tail)


@mcp.tool()
def ue_errors(
    project: str | None = None,
    since_session: bool = False,
    top_n: int = 25,
) -> dict:
    """Aggregate + dedupe error-level lines from the project log."""
    return collect_errors(project, since_session=since_session, top_n=top_n)


@mcp.tool()
def ue_headless(commandlet: str, extra: list[str] | None = None, project: str | None = None) -> dict:
    """Run `UnrealEditor-Cmd.exe <uproject> -run=<commandlet> [extra...]`."""
    return run_commandlet(commandlet, *(extra or []), project=project)


@mcp.tool()
def ue_fixup(project: str | None = None) -> dict:
    """Fix Up Redirectors across /Game (headless)."""
    return fixup_redirectors(project)


@mcp.tool()
def ue_resave(path: str = "", project: str | None = None) -> dict:
    """Run ResavePackages, optionally scoped to a /Game subfolder."""
    return resave_packages(project, path=path)


@mcp.tool()
def ue_py(code: str, project: str | None = None, timeout: float = 30.0) -> dict:
    """Exec Python in the running editor (requires `ue_enable_remote` + restart)."""
    return py_in_editor(code, project=project, timeout=timeout)


@mcp.tool()
def ue_pyfile(path: str, project: str | None = None, timeout: float = 60.0) -> dict:
    """Exec a Python file in the running editor."""
    return py_file_in_editor(path, project=project, timeout=timeout)


@mcp.tool()
def ue_cook(platform: str = "Windows", project: str | None = None) -> dict:
    """Cook content for a platform."""
    return cook(project, platform=platform)


@mcp.tool()
def ue_package(
    platform: str = "Win64",
    config: str = "Development",
    out: str = r"C:\UE_Builds",
    project: str | None = None,
) -> dict:
    """Full BuildCookRun via RunUAT."""
    return package(project, platform=platform, config=config, out=out)


@mcp.tool()
def ue_enable_remote(project: str | None = None) -> dict:
    """Enable Python remote execution in the project's DefaultEngine.ini + plugins."""
    return enable_remote_execution(project)


@mcp.tool()
def ue_doctor(project: str | None = None) -> dict:
    """Run all setup prereq checks. Returns ok=False if anything is missing."""
    return doctor(project)


# --------------------------------------------------------- Holo3 vision

@mcp.tool()
def ue_focus() -> dict:
    """Bring the Unreal Engine editor window to the foreground."""
    from .focus import focus_ue

    return {"ok": focus_ue()}


@mcp.tool()
def ue_list_windows() -> dict:
    """List visible top-level windows (useful for finding the UE title)."""
    from .vision import list_windows

    return {"ok": True, "windows": [{"hwnd": h, "title": t} for h, t in list_windows()]}


@mcp.tool()
def ue_locate(
    description: str,
    window_title: str | None = None,
    save: str | None = None,
) -> dict:
    """Dry-run: ask Holo3 where an element is. Optionally save an annotated PNG."""
    from PIL import ImageDraw

    from ._env import default_window_title, hai_model
    from .vision import _make_client, capture, find_window, localize

    title = window_title or default_window_title()
    hwnd, found_title = find_window(title)
    image, (left, top) = capture(hwnd)
    client = _make_client()
    x, y = localize(client, hai_model(), image, description)
    result: dict = {
        "ok": True,
        "window": found_title,
        "window_origin": [left, top],
        "image": [image.width, image.height],
        "window_xy": [x, y],
        "screen_xy": [left + x, top + y],
    }
    if save:
        annotated = image.copy()
        d = ImageDraw.Draw(annotated)
        d.line([(x - 15, y), (x + 15, y)], fill="red", width=3)
        d.line([(x, y - 15), (x, y + 15)], fill="red", width=3)
        d.ellipse([x - 10, y - 10, x + 10, y + 10], outline="red", width=2)
        annotated.save(save)
        result["saved"] = save
    return result


@mcp.tool()
def ue_click(description: str, window_title: str | None = None, dry_run: bool = False) -> dict:
    """Holo3-grounded left click inside the UE editor window."""
    from .vision import click_by_description

    sx, sy = click_by_description(
        description, window_title=window_title, dry_run=dry_run,
    )
    return {"ok": True, "screen_xy": [sx, sy], "dry_run": dry_run}


@mcp.tool()
def ue_right_click(
    description: str,
    window_title: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Holo3-grounded right click."""
    from .vision import right_click_by_description

    sx, sy = right_click_by_description(
        description, window_title=window_title, dry_run=dry_run,
    )
    return {"ok": True, "screen_xy": [sx, sy], "dry_run": dry_run}


@mcp.tool()
def ue_double_click(
    description: str,
    window_title: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Holo3-grounded double click."""
    from .vision import double_click_by_description

    sx, sy = double_click_by_description(
        description, window_title=window_title, dry_run=dry_run,
    )
    return {"ok": True, "screen_xy": [sx, sy], "dry_run": dry_run}


@mcp.tool()
def ue_type(
    description: str,
    text: str,
    window_title: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Click the described field to focus it, then type."""
    from .vision import type_into

    sx, sy = type_into(
        description, text, window_title=window_title, dry_run=dry_run,
    )
    return {"ok": True, "screen_xy": [sx, sy], "typed": len(text), "dry_run": dry_run}


@mcp.tool()
def ue_press(combo: str) -> dict:
    """Press a key chord, e.g. 'ctrl+s', 'f5', 'alt+p'."""
    from .vision import press_chord

    press_chord(combo)
    return {"ok": True, "combo": combo}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
