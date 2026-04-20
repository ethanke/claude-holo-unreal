"""claude-holo-unreal — Unreal Engine copilot for Claude Code.

Four surfaces, one package:

  • CLI        — `holo-unreal` / `hue` (see `holo_unreal.cli`)
  • MCP server — `holo-unreal-mcp` (see `holo_unreal.mcp_server`)
  • Skills     — `skills/` directory, install with `hue skills install`
  • Library    — import from `holo_unreal` directly (below)

Library surface:
    from holo_unreal import (
        # UE toolkit
        UEToolkit, project_info, launch_editor, close_editor,
        read_log, collect_errors, run_commandlet, fixup_redirectors,
        py_in_editor, cook, package, enable_remote_execution, doctor,

        # Holo3 vision clicker
        click_by_description, right_click_by_description, double_click_by_description,
        type_into, press_key, send_text, localize_in_window, list_windows,

        # Focus + low-level
        focus_ue, capture_window, click_at, right_click_at, double_click_at,
    )
"""
from __future__ import annotations

__version__ = "0.2.0"

from .toolkit import (
    UEToolkit,
    close_editor,
    collect_errors,
    cook,
    doctor,
    enable_remote_execution,
    fixup_redirectors,
    launch_editor,
    package,
    project_info,
    py_in_editor,
    py_file_in_editor,
    read_log,
    resave_packages,
    run_commandlet,
)
from .vision import (
    click_at,
    click_by_description,
    double_click_at,
    double_click_by_description,
    list_windows,
    localize_in_window,
    press_key,
    right_click_at,
    right_click_by_description,
    send_text,
    type_into,
)
from .focus import capture_window, focus_ue

__all__ = [
    "__version__",
    # toolkit
    "UEToolkit",
    "project_info",
    "launch_editor",
    "close_editor",
    "read_log",
    "collect_errors",
    "run_commandlet",
    "fixup_redirectors",
    "resave_packages",
    "py_in_editor",
    "py_file_in_editor",
    "cook",
    "package",
    "enable_remote_execution",
    "doctor",
    # vision
    "click_by_description",
    "right_click_by_description",
    "double_click_by_description",
    "type_into",
    "press_key",
    "send_text",
    "localize_in_window",
    "list_windows",
    # focus + low-level
    "focus_ue",
    "capture_window",
    "click_at",
    "right_click_at",
    "double_click_at",
]
