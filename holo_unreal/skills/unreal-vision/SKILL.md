---
name: unreal-vision
description: Click, type, and press keys inside the Unreal Engine editor by describing elements in plain English — powered by H Company's Holo3 vision-language model. Use this only when a Python/toolkit path doesn't exist (marketplace plugin panels, bespoke modals, Slate-only UI); prefer `unreal-toolkit` otherwise.
---

# Unreal vision clicker — `hue click`

Holo3 sees the UE editor window and returns pixel coordinates for a plain-English
description. `holo-unreal` then synthesizes the click (or type, or chord).

## When to use

**Reach for vision only when:**
- The target is a marketplace plugin settings panel with no Python API
- The target is a modal dialog / transient popup not exposed through `unreal.*`
- You need a one-shot click in a Slate-only menu bar (Alt+F doesn't open UE's File menu)

**Never use vision when a toolkit / Python path exists** — it's slower, non-deterministic on dense toolbars (±15 px scatter on 3B-active VLMs), and the UE editor has deep programmatic surfaces via `PythonScriptPlugin`.

## Commands

```
# Localize + annotate screenshot (no click) — inspect before committing:
hue locate "the green Play button in the main toolbar" --save preview.png

# Real clicks
hue click "the Blueprint menu in the toolbar"
hue right-click "the selected actor in the viewport"
hue double-click "the asset file in the Content Browser"

# Click a field, then type
hue type "the search box" "CharacterBP"

# Keyboard only, no click
hue press "ctrl+s"
hue press "alt+p"           # start PIE
hue press "shift+escape"    # stop PIE (keyboard-only — PIE captures cursor)

# Target a different UE window
hue click "Compile" --window-title "MyProject"
```

Every command prints a single JSON line on stdout with the clicked screen pixel.

## Critical UE quirks

- **PIE captures input.** Once PIE is running, `hue click` targets the game, not the editor. Use `hue press shift+escape` to stop PIE, or run `hue press f8` first to eject the cursor.
- **Slate menus ignore Alt+F.** Open the File menu with `hue click "the word 'File' in the top menu bar"`, not `hue press "alt+f"`.
- **±15 px scatter on dense toolbars.** For tight targets, either ask for more context ("the Save All icon in the top toolbar, immediately right of the Play button") or fall back to a keyboard shortcut.
- **`SetForegroundWindow` steals focus.** The tool foregrounds the UE editor before every screenshot. If you were typing in a terminal, your keystrokes will land in UE.

## Always start with `locate --save`

When grounding a new target for the first time, run `hue locate "..." --save preview.png` and inspect the red crosshair. Saves re-runs (and money on Holo3 calls) when the description doesn't match what you expect.

## Python API

For scripts and notebooks:

```python
from holo_unreal import (
    click_by_description, right_click_by_description,
    type_into, press_key, localize_in_window, list_windows,
)

click_by_description("the Play button")
x, y, sx, sy = localize_in_window("Save All")   # dry-run, returns coords
type_into("the search box", "Paladin")
press_key("s", modifiers=["ctrl"])
```

## Environment

Set `HAI_API_KEY` (H Company portal at https://portal.hcompany.ai). The tool also reads `HAI_MODEL_NAME` (default `holo3-35b-a3b`) and `HOLO_UNREAL_WINDOW_TITLE` (default `Unreal Editor`).
