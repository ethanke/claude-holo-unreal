# claude-holo-unreal

**An Unreal Engine copilot for [Claude Code](https://claude.com/claude-code)** — packaged as a CLI, an MCP server, two Claude Code skills, and a plain Python library. Drives the *running* UE editor through its shipped `PythonScriptPlugin` for anything programmatic, and falls back to [H Company Holo3](https://hub.hcompany.ai) vision grounding for the last-mile clicks (Slate-only menus, marketplace plugin panels, modals).

> Describe a UI element in plain English — `"the Play button"`, `"Save All in the File menu"`, `"the Outliner panel title"` — and `holo-unreal` screenshots the editor window, asks Holo3 where it is, and synthesizes the click.
>
> Run `hue ue py "import unreal; ..."` to execute any Python in the running editor, or register the MCP server and let Claude Code call `ue_py`, `ue_click`, `ue_errors`, `ue_launch` directly.

Pure Win32 `ctypes` for the input layer. No `pywin32`, no `pyautogui`, no Selenium (those are *optional* extras if you also want the focus helpers).

---

## Four surfaces, one package

| Surface          | When to use                                                              | Entry point                                             |
| ---------------- | ------------------------------------------------------------------------ | ------------------------------------------------------- |
| **CLI**          | Shell scripts, ad-hoc from a terminal, quick one-shots                   | `hue …` / `holo-unreal …` / `python -m holo_unreal …`   |
| **MCP server**   | Claude Code calls tools directly (no shell round-trip), best for agents  | `claude mcp add -s user holo-unreal -- python -m holo_unreal.mcp_server` |
| **Skills**       | Claude Code discovers *when* to reach for the toolkit and how to use it  | `hue skills install`                                    |
| **Python lib**   | Automation scripts, notebooks, bench harnesses, test suites              | `from holo_unreal import UEToolkit, click_by_description` |

All four share the same backend. Pick whichever is convenient; you don't have to choose.

---

## Why

Unreal Engine's editor has deep programmatic surfaces — `PythonScriptPlugin`, Editor Utility Widgets, `AssetTools`, `EditorAssetLibrary`, `BlueprintEditorLibrary` — for anything representable as a `.uasset` mutation. You should use those when you can: they're deterministic, survive focus changes, run headless, and give you real errors.

But a chunk of day-to-day UE work lives in Slate-rendered menus, marketplace plugin settings panels, and bespoke editor sub-windows with no scripting API. For that last mile, `holo-unreal` screenshots the editor and asks a vision-language model to find what you asked for.

**The rule of thumb** `hue`'s skill files encode:

> Prefer `hue ue py "<python>"`. Fall back to `hue click "…"` only when no API path exists.

---

## Requirements

- **Windows 10 / 11** (uses `user32.dll`; Linux/macOS PRs welcome)
- **Python 3.11+** (tested 3.13)
- **Unreal Engine 5.x** installed under `C:\Program Files\Epic Games\UE_5.*` (overridable via `UE_ENGINE_BASE`)
- An **H Company API key** — generate one at [portal.hcompany.ai](https://portal.hcompany.ai) — only required for the vision side (`hue click`, `hue locate`, `hue type`, `hue double-click`, `hue right-click`). The UE toolkit (`hue ue …`) works without it.
- **Claude Code** installed, for the MCP / skill integrations. Not required for the CLI or Python library.

---

## Install

```bash
git clone https://github.com/ethanke/claude-holo-unreal
cd claude-holo-unreal

# Recommended: editable install with all extras (MCP + focus helpers).
pip install -e .[all]

# Or minimal (CLI + vision only):
pip install -e .

# Or from GitHub without cloning:
pip install "git+https://github.com/ethanke/claude-holo-unreal#egg=claude-holo-unreal[all]"

# Configure API key
cp .env.example .env
# edit .env → paste HAI_API_KEY
```

After install, these commands are on `$PATH`:

- `hue` — short alias for the main CLI
- `holo-unreal` — same CLI, long name
- `holo-unreal-mcp` — MCP stdio server (what you register with Claude Code)

---

## One-shot bootstrap

```bash
hue claude
```

That's it. `hue claude` installs the two shipped skills into `~/.claude/skills/`, registers the MCP server in `claude`'s user-scope config (if it isn't already), checks your `HAI_API_KEY`, then hands off to the `claude` CLI so you land straight in a Claude Code session with `unreal-toolkit` + `unreal-vision` + `ue_*` MCP tools ready.

Idempotent — safe to run repeatedly. Use `--force` to reinstall skills and re-register the MCP server.

```bash
hue                            # bare `hue` is aliased to `hue claude` — true one-command start
hue claude                     # explicit form
hue claude -- --continue       # pass args through to `claude`
hue claude --force             # reinstall skills, re-register MCP, then launch
hue claude --no-mcp            # skip MCP registration step
hue claude --no-skills         # skip skill install step
hue claude --scope project     # register MCP at project scope instead of user

hue setup                      # same bootstrap without launching
```

---

## Quickstart — three common flows

### 1. UE toolkit from the shell

```bash
# Diagnose setup (engine, plugins, remote-exec, log path, running pids)
hue ue doctor --project "C:/Users/you/Projects/MyGame/MyGame.uproject"

# Launch the editor, detached
hue ue launch

# Tail errors from the current session's log
hue ue errors --since-session

# One-time: enable Python remote execution + restart editor
hue ue enable-remote

# Now execute Python inside the running editor
hue ue py "import unreal; print(unreal.SystemLibrary.get_project_directory())"

# Or a whole file
hue ue pyfile examples/compile_all_blueprints.py

# Headless commandlets
hue ue fixup                                  # Fix Up Redirectors
hue ue resave --path /Game/MMO
hue ue cook --platform Windows
hue ue package --platform Win64 --config Shipping --out C:/Builds
```

Set `UE_PROJECT` in `.env` once and you can drop `--project` from every command.

### 2. Holo3 vision — Slate menus, plugin panels, modals

```bash
# Discover windows
hue list-windows

# Preview a grounding (writes an annotated PNG with a red crosshair)
hue locate "the green Play button in the main toolbar" --save preview.png

# Click it for real
hue click "the Blueprint menu in the toolbar"

# Right-click / double-click
hue right-click "the selected actor in the viewport"
hue double-click "the asset in the Content Browser"

# Click then type
hue type "the search box" "CharacterBP"

# Keyboard-only chord (no click, no grounding call)
hue press "ctrl+s"
hue press "alt+p"          # start PIE
hue press "shift+escape"   # stop PIE

# Target a non-default window
hue click "Compile" --window-title "MyProject"
```

Every vision command is JSON on stdout and prints coordinates so you can feed them into a second step.

### 3. From inside Claude Code (MCP + skills)

One command:

```bash
hue claude                     # setup + launch
```

Or manually, if you prefer step-by-step:

```bash
# Copy the shipped skills into ~/.claude/skills/
hue skills install

# Register the MCP server
claude mcp add -s user holo-unreal -- python -m holo_unreal.mcp_server

# Launch Claude Code
claude
```

Once registered, Claude Code has these MCP tools available:

| Group       | Tools                                                                          |
| ----------- | ------------------------------------------------------------------------------ |
| UE lifecycle| `ue_info`, `ue_launch`, `ue_close`, `ue_doctor`                                |
| UE log      | `ue_log`, `ue_errors`                                                          |
| UE headless | `ue_headless`, `ue_fixup`, `ue_resave`, `ue_cook`, `ue_package`                |
| UE Python   | `ue_py`, `ue_pyfile`, `ue_enable_remote`                                       |
| Vision      | `ue_focus`, `ue_list_windows`, `ue_locate`, `ue_click`, `ue_right_click`, `ue_double_click`, `ue_type`, `ue_press` |
| Meta        | `hue_info`                                                                     |

The shipped skills (`unreal-toolkit`, `unreal-vision`) tell Claude Code *when* to reach for each tool, and document the sharp edges (UE Slate menus ignore Alt+F, PIE captures the cursor, etc.).

### 4. Library usage

```python
from holo_unreal import (
    UEToolkit,
    click_by_description, type_into, press_key,
    localize_in_window, focus_ue,
)

# Bind a project once; all toolkit ops run against it.
ue = UEToolkit(project=r"C:\Projects\MyGame\MyGame.uproject")
print(ue.info())
print(ue.doctor())

# Run Python in the running editor.
ue.py("import unreal; print(len(unreal.EditorLevelLibrary.get_all_level_actors()))")

# Fall back to vision for Slate / plugin UI.
focus_ue()
click_by_description("the Blueprint menu in the toolbar")
type_into("the search box", "Paladin")
press_key("s", modifiers=["ctrl"])
```

---

## How it works

### The vision path

1. **Find window.** `user32.EnumWindows` + case-insensitive substring match on window title (default `"Unreal Editor"`, overridable via `HOLO_UNREAL_WINDOW_TITLE`).
2. **Screenshot.** `SetForegroundWindow` → 150 ms settle → `PIL.ImageGrab.grab` with the window's `GetWindowRect` bbox (`all_screens=True` for multi-monitor).
3. **Localize.** OpenAI-compatible chat completion to `api.hcompany.ai/v1/` with:
   ```python
   extra_body={
       "structured_outputs": {"json": {"type":"object","required":["x","y"],...}},
       "chat_template_kwargs": {"enable_thinking": False},
   }
   temperature=0.0, max_tokens=1024
   ```
   Holo3 returns `{x, y}` in screenshot-local pixels.
4. **Click.** `SetCursorPos(screen_x, screen_y)` → `mouse_event(LEFTDOWN|LEFTUP)`.

#### Why `extra_body`, not `response_format`

The Holo3 managed endpoint has three non-standard quirks, all handled for you:

- **`extra_body["structured_outputs"]["json"]`** instead of OpenAI-standard `response_format={"type":"json_schema", ...}`. The standard key returns a misleading `400 "you must provide a model parameter"`.
- **Flat schemas.** `$defs`/`$ref` get rejected by the validator — inline everything.
- **Disable thinking.** Holo3 defaults to hidden chain-of-thought. Without `chat_template_kwargs={"enable_thinking": False}`, small `max_tokens` budgets burn on CoT and return empty content with `finish_reason=length`.

### The toolkit path

Launch / close / log / errors use plain `subprocess` against `UnrealEditor.exe` and `UnrealEditor-Cmd.exe`, with engine auto-detected from the `.uproject`'s `EngineAssociation`. `cook` / `package` delegate to `RunUAT.bat`.

Python-in-editor uses the `remote_execution.py` module shipped inside `PythonScriptPlugin` — the same protocol UE itself uses for the *Python Interactive Console*. The toolkit imports it from the detected engine path, spins up a `RemoteExecution` client, waits for the editor to advertise a node, and executes the code with `MODE_EXEC_FILE`. Enable it once with `hue ue enable-remote` — writes `bRemoteExecution=True` into `Config/DefaultEngine.ini` under `[/Script/PythonScriptPlugin.PythonScriptPluginSettings]` **and** adds `PythonScriptPlugin` + `EditorScriptingUtilities` to the `.uproject`.

---

## UE-specific gotchas worth knowing

These are baked into the skill files so Claude Code respects them automatically; worth knowing if you drive the tool directly.

- **UE Slate menus don't honor `Alt+F`-style chords.** Use `hue click "the word 'File' in the top menu bar"` to open File, not `hue press alt+f`.
- **PIE (Play-In-Editor) captures the cursor.** Once PIE is running, `hue click` targets the game, not the editor chrome. To stop PIE robustly: `hue press f8` (eject) → `hue press shift+escape` → `hue press shift+escape`.
- **UE Slate widgets rarely expose UIA accessibility names.** If you were thinking of driving the editor through accessibility trees, use the Python API or vision instead.
- **±15 px scatter on dense toolbars.** Holo3 is a 3B-active VLM. For tight targets, give more context ("the Save All icon in the top toolbar, immediately right of the Play button") or fall back to the keyboard shortcut.
- **`SetForegroundWindow` steals focus.** Before every screenshot. If you were typing in a terminal, your keystrokes will land in UE. The `focus_ue()` helper uses the alt-key trick to satisfy Windows' recent-input-focus policy.
- **`enable-remote` needs an editor restart** for the INI change to pick up. No way around it — UE caches plugin settings at startup.
- **Redirector cleanup after pack relocations.** For folder-rename damage that duplicated `.uasset` files, `hue ue fixup` is not enough — use `CoreRedirects` in `Config/DefaultEngine.ini` (the old and new paths need to point at the *same* class, not two copies).

---

## Benchmark

`bench/bench_ue.py` runs a suite of probe tasks (locate Play, Content Drawer, Save All, Outliner/Details + one real File-menu click with before/after diff) and reports timings:

```bash
python bench/bench_ue.py                     # writes bench_out/report.md
python bench/bench_ue.py --dry-run           # localize only
python bench/bench_ue.py --tasks locate-play-button,locate-save-all
```

Typical numbers against a 2576×1048 UE editor on `holo3-35b-a3b`:

| Metric               | Value     |
| -------------------- | --------- |
| Avg localize         | ~970 ms   |
| Median localize      | ~770 ms   |
| p95 localize         | ~900 ms   |
| End-to-end per task  | ~1.5 s    |

---

## Examples

See `examples/` for worked scripts that run in the editor via `hue ue pyfile`:

- `compile_all_blueprints.py` — compile every Blueprint in the project, report failures
- `reparent_blueprint.py` — swap a Blueprint's parent class after a pack update
- `find_references.py` — dump every asset that references a target path

---

## Package layout

```
claude-holo-unreal/
├── holo_unreal/
│   ├── __init__.py          # library exports
│   ├── __main__.py          # `python -m holo_unreal`
│   ├── cli.py               # unified CLI (hue / holo-unreal)
│   ├── toolkit.py           # UE lifecycle, log, commandlets, python-in-editor
│   ├── vision.py            # Holo3 + Win32 ctypes input
│   ├── focus.py             # UE window foreground helper
│   ├── scenarios.py         # curated UE test scenarios
│   ├── mcp_server.py        # FastMCP stdio server
│   └── _env.py              # .env loader + defaults
├── holo_unreal/skills/
│   ├── unreal-toolkit/SKILL.md
│   └── unreal-vision/SKILL.md
├── examples/                # editor-side Python scripts
├── bench/bench_ue.py        # localize-latency benchmark
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Related

- [H Company Holo3 quickstart](https://hub.hcompany.ai/quickstart) — official API docs for the vision model
- [`hcompai/surfer-h-cli`](https://github.com/hcompai/surfer-h-cli) — H Company's official Holo browser agent. `claude-holo-unreal` is the UE-editor analog.
- [Unreal `PythonScriptPlugin`](https://docs.unrealengine.com/5.4/en-US/scripting-the-unreal-editor-using-python/) — prefer this for anything expressible as a `.uasset` mutation.
- [Unreal MCP bridge projects](https://github.com/ChiR24/Unreal_mcp) — alternative approach for structured actor/asset APIs.
- [Anthropic Model Context Protocol](https://modelcontextprotocol.io/) — the protocol that lets Claude Code call `ue_*` tools directly.

---

## Contributing

PRs welcome — especially for:

- Linux / macOS ports of the Win32 input layer
- Drag / hover / scroll-wheel primitives (currently only click/type/press)
- More editor scenarios under `scenarios.py`
- Worked examples under `examples/`

Open an issue first if you're unsure about scope.

---

## License

MIT — see `LICENSE`.
