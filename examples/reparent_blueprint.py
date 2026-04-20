"""Reparent a Blueprint to a different C++ or Blueprint parent class.

Useful after a pack update overwrote your custom reparenting. Edit the two
paths below, then:

    hue ue pyfile examples/reparent_blueprint.py
"""
import unreal  # noqa: E402

BLUEPRINT_PATH = "/Game/Characters/BP_MyCharacter"
NEW_PARENT_CLASS_PATH = "/Script/MyGameModule.MyCharacterBase"

bp = unreal.EditorAssetLibrary.load_asset(BLUEPRINT_PATH)
if bp is None:
    raise RuntimeError(f"couldn't load Blueprint: {BLUEPRINT_PATH}")

new_cls = unreal.load_class(None, NEW_PARENT_CLASS_PATH)
if new_cls is None:
    raise RuntimeError(f"couldn't load parent class: {NEW_PARENT_CLASS_PATH}")

unreal.BlueprintEditorLibrary.reparent_blueprint(bp, new_cls)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_asset(BLUEPRINT_PATH)
unreal.log(f"reparented {BLUEPRINT_PATH} -> {NEW_PARENT_CLASS_PATH}")
