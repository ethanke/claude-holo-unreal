---
name: unreal-toolkit
description: Operate an Unreal Engine project from the CLI — launch/close editor, tail logs, extract compile/runtime errors, run headless commandlets (Fix Up Redirectors, resave, cook, package), execute Python in the running editor. Use this whenever the user asks you to build, debug, inspect, or automate anything inside a UE project; prefer this over driving the editor via screenshots.
---

# Unreal Engine toolkit — `hue ue`

All subcommands run as `hue ue <subcommand>` (aliased to `holo-unreal ue ...`).
Every subcommand prints a single JSON line on stdout.

Default project resolution order:
1. `--project <path.uproject>` flag
2. `$UE_PROJECT` environment variable
3. Error (no default in the shipped package — set one in `.env`)

## When to reach for this vs. driving the editor via screenshots

**Prefer the toolkit for:**
- Launching / closing the editor
- Reading / filtering the log (compile errors, runtime warnings, crash traces)
- Running commandlets (Fix Up Redirectors, ResavePackages, cook, full package)
- Any editor operation that can be expressed in Python — `hue ue py "<code>"` runs any Python in the **running** editor with full `unreal` module access.

**Fall back to the vision clicker (`hue click`) only for:**
- Marketplace plugin settings panels with no Python API
- Bespoke editor sub-windows / modal dialogs
- Visual sanity checks ("did it render the character?")

## Essential commands

### Inspection
```
hue ue info                         — engine, project, log, running pids
hue ue doctor                       — diagnose all prerequisites
hue ue log --grep "Error" --tail 50 — filter the current project log
hue ue errors --since-session       — aggregated, deduped error report
```

### Lifecycle
```
hue ue launch                       — spawn UnrealEditor.exe (detached)
hue ue close                        — graceful WM_CLOSE
hue ue close --force                — taskkill /F
```

### Headless commandlets (no GUI needed)
```
hue ue fixup                        — Fix Up Redirectors in /Game
hue ue resave --path /Game/Foo      — resave subset
hue ue headless <Commandlet> [args] — generic commandlet runner
hue ue cook --platform Windows
hue ue package --platform Win64 --config Shipping --out C:\Builds
```

### Python in the running editor (requires remote exec enabled once)
```
hue ue enable-remote                — one-time: writes config + enables plugins, restart editor
hue ue py "import unreal; print(unreal.SystemLibrary.get_project_directory())"
hue ue pyfile scripts/place_actor.py
```

Once remote exec is live, most editor actions become Python one-liners:

```python
# Compile every Blueprint in the project
import unreal
reg = unreal.AssetRegistryHelpers.get_asset_registry()
for a in reg.get_assets_by_class("/Script/Engine.Blueprint", True):
    bp = a.get_asset()
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
```

```python
# Find all assets referencing a given asset
import unreal
refs = unreal.AssetRegistryHelpers.get_asset_registry().get_referencers(
    "/Game/Foo/MyAsset", unreal.AssetRegistryDependencyOptions())
print(refs)
```

See `examples/` in the repo for longer scripts (compile-all, reparent, reference-audit).

## Workflow tips

- **Start every UE session with `hue ue doctor`** — catches missing engine, stale configs, unexpected state fast.
- **`hue ue errors --since-session`** before asking the user anything — the answer is usually in the log.
- **`hue ue fixup` is the one-shot for redirector issues.** For pack-folder relocations where files were copied (not just redirected), prefer `CoreRedirects` in `Config/DefaultEngine.ini` over a second `fixup` run.
- **Cook/package in the background** (`run_in_background: true`) — they take minutes. Poll with `hue ue log --tail 20`.
- **Prefer headless commandlets over driving the editor UI.** They survive focus changes and don't need visual verification.

## Extensibility

The toolkit is a library first; the CLI wraps it. To add a new op, extend
`holo_unreal/toolkit.py` (function returning `{"ok": bool, ...}`) and register
a subcommand in `holo_unreal/cli.py`. Add an MCP tool in `mcp_server.py` if
Claude Code should call it directly.
