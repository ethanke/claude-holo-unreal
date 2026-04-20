"""Find every asset that references a target asset.

Handy before a rename/move to gauge blast radius.

    hue ue pyfile examples/find_references.py
"""
import unreal  # noqa: E402

TARGET = "/Game/Data/MyStruct"

reg = unreal.AssetRegistryHelpers.get_asset_registry()
refs = reg.get_referencers(TARGET, unreal.AssetRegistryDependencyOptions())

unreal.log(f"{len(refs)} asset(s) reference {TARGET}:")
for r in sorted(refs):
    unreal.log(f"  {r}")
