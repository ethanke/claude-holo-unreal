# holo3-ue

Vision-grounded click agent for the Unreal Editor, powered by
[H Company's Holo3](https://hub.hcompany.ai/quickstart) vision-language model.

Describe a UI element in plain English — `"the Play button"`, `"Save All in
the File menu"`, `"the Outliner panel title"` — and `holo3-ue` screenshots the
editor window, asks Holo3 where it is, and synthesizes the click.

Pure Win32 `ctypes` under the hood. No `pywin32`, no `pyautogui`, no Selenium.
Two runtime deps: `openai`, `pillow`.

```bash
python holo3_ue.py "the green Play button in the main toolbar"
python holo3_ue.py "the search box" --type "CharacterBP"
python holo3_ue.py --press "ctrl+s"
```

---

## Why

Unreal Engine's editor has deep programmatic surfaces (PythonScriptPlugin,
Editor Utility Widgets, MCP automation bridges) for anything representable as
`unreal.AssetTools`, `unreal.EditorAssetLibrary`, etc. But a chunk of day-to-day
clicks lives in marketplace-plugin settings panels, modal dialogs, and bespoke
editor sub-windows that expose no scripting API.

`holo3-ue` is the last-mile for those. It's explicitly not a replacement for
Python-scripting or MCP — use those when an API path exists. Reach for vision
only when the target is *visibly* there and no other path is.

## Requirements

- Windows 10 / 11 (uses `user32.dll`; Linux/macOS ports welcome as PRs)
- Python 3.11+ (3.13 tested)
- An H Company API key — generate at [portal.hcompany.ai](https://portal.hcompany.ai)
- Unreal Editor (any 5.x) for real UE use; technically any window will do

## Install

```bash
git clone https://github.com/ethanke/holo3-ue
cd holo3-ue

# recommended: uv
uv venv --python 3.13
uv pip install -r requirements.txt

# or plain pip
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# set your key
copy .env.example .env
# edit .env → paste HAI_API_KEY
```

## Usage

### CLI

```bash
# find your editor window first
python holo3_ue.py --list-windows

# dry-run: localize + annotate screenshot, DO NOT click
python holo3_ue.py "the Play button" --dry-run --save preview.png

# real click
python holo3_ue.py "the Blueprint menu in the toolbar"

# variants
python holo3_ue.py "the context target"        --right-click
python holo3_ue.py "the file in the list"      --double-click
python holo3_ue.py "the name field"            --type "MyNewActor"
python holo3_ue.py --press "ctrl+s"              # keyboard-only, no click
python holo3_ue.py "the Save button" --press "enter"  # click then Enter

# target a different editor window
python holo3_ue.py "Compile" --window-title "MyProject"
```

### Library

```python
from holo3_ue import (
    click_by_description, right_click_by_description, type_into,
    localize_in_window, press_key, list_windows,
)

click_by_description("the Play button")
right_click_by_description("the selected actor in the viewport")
type_into("the search box", "Paladin")
press_key("s", modifiers=["ctrl"])

# returns coords without clicking — for logging, batch scripts, etc.
win_x, win_y, screen_x, screen_y = localize_in_window("Save All")
```

## Benchmark

`bench_ue.py` runs a suite of probe tasks (localize the Play button, Content
Drawer, Save All, Outliner/Details panels + one real File-menu click with
before/after screenshot diff) and reports timings:

```bash
python bench_ue.py                    # writes bench_out/report.md
python bench_ue.py --dry-run          # localize only, no clicks
python bench_ue.py --tasks locate-play-button,locate-save-all  # filter
```

Typical numbers against a 2576×1048 UE editor on `holo3-35b-a3b`:

| Metric | Value |
|---|---|
| Avg localize | ~970 ms |
| Median localize | ~770 ms |
| p95 localize | ~900 ms |
| End-to-end per task | ~1.5 s |

## How it works

1. **Find window** — `user32.EnumWindows` + case-insensitive substring match on
   window title (default: `"Unreal Editor"`).
2. **Screenshot** — `SetForegroundWindow` → 150 ms settle → `PIL.ImageGrab.grab`
   with the window's `GetWindowRect` bbox (`all_screens=True` for multi-monitor).
3. **Localize** — `openai.OpenAI` chat completion to `api.hcompany.ai/v1/` with:
   ```python
   extra_body={
       "structured_outputs": {"json": {"type":"object","required":["x","y"],...}},
       "chat_template_kwargs": {"enable_thinking": False},
   }
   temperature=0.0
   max_tokens=1024
   ```
   Holo3 returns `{x, y}` in screenshot-local pixels.
4. **Click** — `SetCursorPos(screen_x, screen_y)` + `mouse_event(LEFTDOWN|LEFTUP)`.

### Why `extra_body`, not `response_format`

Holo3's managed endpoint (`api.hcompany.ai/v1/`) has two non-standard quirks:

- **`extra_body["structured_outputs"]["json"]`** instead of OpenAI-standard
  `response_format={"type":"json_schema", ...}`. The standard key returns a
  misleading `400 "you must provide a model parameter"`.
- **Flat schemas.** `$defs`/`$ref` get rejected by Holo3's validator. Inline
  everything before sending.
- **Disable thinking.** Holo3 defaults to chain-of-thought reasoning. Without
  `chat_template_kwargs={"enable_thinking": False}`, small `max_tokens` budgets
  burn on hidden CoT and return empty `content` with `finish_reason=length`.

All three are already handled in `holo3_ue.py`. Mentioned here so anyone
extending the schema doesn't re-hit them.

## Input primitives

Library-level, all Win32 `ctypes`:

| Primitive | Function |
|---|---|
| Left click | `click_at(sx, sy)`, `click_by_description(desc)` |
| Right click | `right_click_at(sx, sy)`, `right_click_by_description(desc)` |
| Double click | `double_click_at(sx, sy)` |
| Type Unicode | `send_text("hello")`, `type_into(desc, "hello")` |
| Key / chord | `press_key("s", ["ctrl"])`, `press_key("f5")`, `press_key("enter")` |

Supported keys: `a-z`, `0-9`, `enter`, `tab`, `escape`, `space`, `backspace`,
`delete`, `insert`, `home`, `end`, `pageup`, `pagedown`, `up`, `down`, `left`,
`right`, `f1`–`f13`.
Supported modifiers: `ctrl`, `shift`, `alt`, `win`.

## Safety notes

- Default CLI behavior prints a 1-second countdown before clicking
  (`Ctrl+C` to cancel).
- `--dry-run` skips click *and* any follow-up text / key action.
- `--save <path>` writes the screenshot with a red crosshair at the predicted
  coord — inspect before committing to a live click.
- The tool uses `SetForegroundWindow` before grabbing the screenshot, so the
  target editor will steal focus.

## Known limits

- **±15 px scatter** on dense toolbars — Holo3 is a 3B-active VLM. For tight
  targets, either pre-crop with a coarser `--window-title` match, or call
  `localize` 3× and take the median.
- **No drag, no hover, no scroll-wheel** yet. `click_at` is trivially
  extensible; PRs welcome.
- **Windows-only.** Linux X11 / macOS CGWindow ports are straightforward
  replacements for the Win32 section.
- **No server-side guarantees from Holo3.** Free-tier rate limits apply; check
  [portal.hcompany.ai](https://portal.hcompany.ai).

## Related

- [hcompai/surfer-h-cli](https://github.com/hcompai/surfer-h-cli) — H Company's
  official Holo browser agent. `holo3-ue` is the UE-editor analog, scoped
  narrower (click + type) but free of the web-specific action schema.
- [Holo3 quickstart](https://hub.hcompany.ai/quickstart) — official API docs.
- [Unreal `PythonScriptPlugin`](https://docs.unrealengine.com/5.4/en-US/scripting-the-unreal-editor-using-python/)
  — prefer this for anything expressible as a `.uasset` mutation.
- [MCP Unreal bridge](https://github.com/ChiR24/Unreal_mcp) — prefer this for
  anything reachable via structured actor/asset APIs.

## License

MIT — see `LICENSE`.
