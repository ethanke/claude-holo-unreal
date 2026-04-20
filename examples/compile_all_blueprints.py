"""Compile every Blueprint in the project and report failures.

Runs inside the editor via `hue ue pyfile`. Requires remote execution enabled
(`hue ue enable-remote` once, then restart the editor).

Usage:
    hue ue pyfile examples/compile_all_blueprints.py
"""
import unreal  # noqa: E402  (provided by the UE python runtime)

reg = unreal.AssetRegistryHelpers.get_asset_registry()
assets = reg.get_assets_by_class("/Script/Engine.Blueprint", True)
unreal.log(f"compiling {len(assets)} Blueprints...")

failed: list[str] = []
for a in assets:
    bp = a.get_asset()
    try:
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    except Exception as exc:  # noqa: BLE001
        failed.append(f"{a.package_name}: {exc}")

unreal.log(f"done. failed={len(failed)}")
for f in failed:
    unreal.log_warning(f)
