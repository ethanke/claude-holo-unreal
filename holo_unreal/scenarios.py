"""Curated Unreal Engine editor scenarios — useful as smoke tests, benchmark
probes, and as worked examples of Holo3 + UE interaction patterns.

Each scenario is a (name, goal, assertions) tuple. The `bench/` directory
consumes these to produce timing + success reports; harness integrations
elsewhere (e.g. winact) can re-use the same definitions.

Patterns worth noting:
  • Keyboard shortcuts are strictly preferred to Holo3 clicks for any mode
    that captures cursor input (PIE, console, immersive).
  • UE's Slate menus don't honor Alt+F-style chords — click the menu text
    via Holo3 instead.
  • Input-capturing modes need deterministic escape sequences (F8 → Shift+
    Escape for PIE).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass
class Step:
    """One deterministic setup/cleanup action."""
    kind: Literal["click", "key", "type", "wait"]
    args: dict


@dataclass
class Scenario:
    """Natural-language task for an agent to drive against a live UE editor."""
    name: str
    goal: str
    assertions: list[str]
    setup: list[Step] = field(default_factory=list)
    cleanup: list[Step] = field(default_factory=list)
    precondition: Callable[[], bool] | None = None
    skip_setup_if_precondition: bool = False
    max_steps: int = 6
    settle_before_judge_s: float = 0.5


S_FOCUS = Scenario(
    name="ue_focus_editor",
    goal=(
        "Confirm the Unreal Engine editor window is in the foreground. If it "
        "IS, emit done immediately. Otherwise press alt+tab once then emit done."
    ),
    assertions=[
        "The Unreal Engine editor is the visible foreground application.",
    ],
    max_steps=3,
)

S_OUTPUT_LOG = Scenario(
    name="ue_open_output_log",
    goal=(
        "Open the Output Log panel. Preferred: press ctrl+shift+o. Fallback: "
        "Window menu > Developer Tools > Output Log. Emit done when an Output "
        "Log panel with log text lines is visible."
    ),
    assertions=[
        "The Output Log panel is visibly open, showing actual log text lines.",
    ],
    max_steps=6,
    settle_before_judge_s=0.8,
)

S_CONTENT_BROWSER = Scenario(
    name="ue_content_browser_game",
    goal=(
        "Focus the Content Browser and navigate to /Game (Content) root. "
        "Click the 'Content' item in the left tree. Emit done when the "
        "breadcrumb shows 'All > Content' or similar."
    ),
    assertions=[
        "The Content Browser is displaying the /Game root directory.",
    ],
    max_steps=6,
)

S_START_PIE = Scenario(
    name="ue_start_pie",
    goal=(
        "Start Play-In-Editor. Press alt+p, wait 2s for PIE to initialize, "
        "then emit done. Do not click the play button (it may be obscured)."
    ),
    assertions=[
        "The editor is in PIE mode: viewport rendering a running game world, "
        "toolbar shows PIE chrome such as a red Stop button.",
    ],
    max_steps=5,
    settle_before_judge_s=1.5,
)

S_STOP_PIE = Scenario(
    name="ue_stop_pie",
    goal=(
        "PIE stop has been attempted via setup (F8 eject, multiple shift+escape "
        "presses). If the normal editor viewport is visible, emit done. "
        "Otherwise press shift+escape once more."
    ),
    setup=[
        Step(kind="key", args={"combo": "f8"}),
        Step(kind="wait", args={"seconds": 0.4}),
        Step(kind="key", args={"combo": "shift+escape"}),
        Step(kind="wait", args={"seconds": 0.6}),
        Step(kind="key", args={"combo": "shift+escape"}),
        Step(kind="wait", args={"seconds": 0.6}),
        Step(kind="key", args={"combo": "escape"}),
        Step(kind="wait", args={"seconds": 0.6}),
    ],
    assertions=[
        "PIE is stopped. No red Stop chrome, no in-game HUD, no PIE toolbar.",
    ],
    max_steps=3,
    settle_before_judge_s=1.5,
)

S_FILE_MENU = Scenario(
    name="ue_open_file_menu",
    goal=(
        "Open the File menu in the main menu bar. UE Slate menus don't honor "
        "Alt+F — click the word 'File' at the top of the editor window. Emit "
        "done once a dropdown with items like 'New Level' appears."
    ),
    assertions=[
        "The File dropdown menu is open, showing items like 'New Level', "
        "'Open Level', 'Save All', or 'Recent Projects'.",
    ],
    max_steps=4,
)

S_CLOSE_MENU = Scenario(
    name="ue_close_menu",
    goal=(
        "Close any open dropdown/modal/popup. Press escape. If no menu is "
        "open, emit done immediately."
    ),
    assertions=[
        "No dropdown menu, modal dialog, or transient popup is open.",
    ],
    max_steps=3,
)

S_SAVE_ALL = Scenario(
    name="ue_save_all",
    goal=(
        "Save all dirty assets. Press ctrl+shift+s. If a Save dialog appears, "
        "click Save. Emit done when no Save dialog remains."
    ),
    assertions=[
        "No Save Content / Save Level modal dialog is currently open.",
    ],
    max_steps=5,
    settle_before_judge_s=0.8,
)


SCENARIOS: list[Scenario] = [
    S_FOCUS,
    S_OUTPUT_LOG,
    S_CONTENT_BROWSER,
    S_START_PIE,
    S_STOP_PIE,
    S_FILE_MENU,
    S_CLOSE_MENU,
    S_SAVE_ALL,
]


def by_name(name: str) -> Scenario:
    for s in SCENARIOS:
        if s.name == name:
            return s
    raise KeyError(f"no scenario named {name!r}")


__all__ = [
    "Scenario",
    "Step",
    "SCENARIOS",
    "by_name",
    "S_FOCUS",
    "S_OUTPUT_LOG",
    "S_CONTENT_BROWSER",
    "S_START_PIE",
    "S_STOP_PIE",
    "S_FILE_MENU",
    "S_CLOSE_MENU",
    "S_SAVE_ALL",
]
