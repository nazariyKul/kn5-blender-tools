"""Folder import operators and the Assetto Corsa car sidebar."""

from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .ac_folders import car_lods, car_skins, track_layouts
from .kn5 import parse
from .organize import find_import_collection
from .scene import build, import_transaction
from .skins import apply_skin, prepare_car
from .tracks import import_track

_enum_cache = {}


def _stable_items(items):
    # Menu buttons pass enum values through float32: large CRCs get rounded.
    # Persist identifiers in the get/set callbacks, never these menu indices.
    items = tuple((*item, 0, number) for number, item in enumerate(items))
    # Blender retains callback strings; keep every returned tuple alive across redraws.
    return _enum_cache.setdefault(items, items)


def _car_items(_self, _context):
    items = tuple((c.name, c.name, "Imported Assetto Corsa car")
                  for c in bpy.data.collections if c.get("ac_kind") == "CAR")
    return _stable_items(items or (("NONE", "No imported cars", ""),))


def _get_car_choice(scene):
    selected = scene.get("ac_car_choice_id", "NONE")
    return next((item[4] for item in _car_items(scene, None) if item[0] == selected), 0)


def _set_car_choice(scene, value):
    scene["ac_car_choice_id"] = next(item[0] for item in _car_items(scene, None) if item[4] == value)


def _skin_items(collection, _context):
    folder = collection.get("ac_source_folder", "")
    folder = bpy.path.abspath(folder) if folder else ""
    try:
        skins = car_skins(folder)
    except OSError:
        skins = ()
    if not skins:
        paths = collection.get("ac_skin_paths", {})
        labels = collection.get("ac_skin_labels", {})
        skins = tuple((key, labels[key] if key in labels else key, path) for key, path in paths.items())
    items = (("BASE", "Base textures", "Original KN5 textures"),) + tuple(
        (key, label, key) for key, label, _ in skins)
    selected = collection.get("ac_skin_choice_id", "BASE")
    if selected and selected not in {item[0] for item in items}:
        items += ((selected, f"Unavailable: {selected}", "Skin directory is missing"),)
    return _stable_items(items)


def _get_skin_choice(collection):
    selected = collection.get("ac_skin_choice_id", "BASE")
    return next((item[4] for item in _skin_items(collection, None)
                 if item[0] == selected), 0)


def _set_skin_choice(collection, value):
    collection["ac_skin_choice_id"] = next(
        item[0] for item in _skin_items(collection, None) if item[4] == value)


def _import_skin_items(self, _context):
    try:
        skins = car_skins(bpy.path.abspath(self.directory))
    except OSError:
        skins = ()
    items = (("BASE", "Base textures", "Original KN5 textures"),) + tuple(
        (key, label, key) for key, label, _ in skins)
    return _stable_items(items)


def _lod_items(self, _context):
    try:
        lods = car_lods(bpy.path.abspath(self.directory))
    except (OSError, ValueError):
        lods = ()
    items = (("AUTO", "Highest quality", "First available visual LOD"),) + tuple(
        (lod.key, f"{lod.label}: {lod.path.name}", lod.path.name) for lod in lods)
    return _stable_items(items)


def _layout_items(self, _context):
    try:
        layouts = track_layouts(bpy.path.abspath(self.directory))
    except (OSError, ValueError):
        layouts = ()
    items = (("AUTO", "Default layout", "First available layout"),) + tuple(
        (layout.key, f"{layout.label} ({len(layout.parts)} KN5)", layout.label)
        for layout in layouts)
    return _stable_items(items)


def _selected_car(context):
    name = getattr(context.scene, "ac_car_choice", "NONE")
    collection = bpy.data.collections.get(name)
    if collection and collection.get("ac_kind") == "CAR":
        return collection
    return next((c for c in bpy.data.collections if c.get("ac_kind") == "CAR"), None)


def _selected_asset(context):
    active = context.active_object
    tracks = [c for c in bpy.data.collections if c.get("ac_kind") == "TRACK"]
    if active:
        track = next((c for c in tracks if c.all_objects.get(active.name) == active), None)
        if track:
            return track
    imported = find_import_collection(context)
    if imported and imported.get("ac_kind") != "CAR":
        return imported
    return _selected_car(context) or imported or (tracks[0] if len(tracks) == 1 else None)


def _skin_target(context, name):
    collection = bpy.data.collections.get(name) if name else _selected_asset(context)
    return collection if collection is not None and collection.get("ac_kind") == "CAR" else None


class IMPORT_SCENE_OT_assetto_corsa_car(bpy.types.Operator):
    bl_idname = "import_scene.assetto_corsa_car"
    bl_label = "Import Assetto Corsa Car"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(name="Car Folder", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    lod: EnumProperty(name="Visual LOD", items=_lod_items)
    skin: EnumProperty(name="Skin", items=_import_skin_items)

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, _context):
        self.layout.prop(self, "lod")
        self.layout.prop(self, "skin")

    def execute(self, context):
        try:
            folder = Path(bpy.path.abspath(self.directory)).expanduser().resolve()
            lods = car_lods(folder)
            chosen = lods[0] if self.lod == "AUTO" else next(lod for lod in lods if lod.key == self.lod)
            if self.skin != "BASE" and self.skin.casefold() not in {
                    key.casefold() for key, _, _ in car_skins(folder)}:
                raise FileNotFoundError(f"Skin folder not found: {folder / 'skins' / self.skin}")
            model = parse(chosen.path)
            with import_transaction():
                collection, warnings = build(model, chosen.path)
                collection.name = folder.name.upper()
                warnings = tuple(warnings) + prepare_car(collection, folder, chosen.path, chosen.label, model)
                collection.ac_skin_choice = self.skin
                if self.skin != "BASE":
                    _, skin_warnings = apply_skin(collection, self.skin)
                    warnings = tuple(warnings) + skin_warnings
                context.scene.ac_car_choice = collection.name
        except (OSError, ValueError, RuntimeError, StopIteration) as exc:
            self.report({"ERROR"}, f"Car import failed: {exc}")
            return {"CANCELLED"}
        for warning in warnings:
            print("Assetto Corsa car warning:", warning)
        self.report({"INFO"}, f"Imported {collection.name} from {chosen.path.name}")
        return {"FINISHED"}


class IMPORT_SCENE_OT_assetto_corsa_track(bpy.types.Operator):
    bl_idname = "import_scene.assetto_corsa_track"
    bl_label = "Import Assetto Corsa Track"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(name="Track Folder", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})
    layout_choice: EnumProperty(name="Layout", items=_layout_items)

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, _context):
        self.layout.prop(self, "layout_choice")

    def execute(self, context):
        wm = context.window_manager
        started = False
        try:
            folder = Path(bpy.path.abspath(self.directory)).expanduser().resolve()
            layouts = track_layouts(folder)
            chosen = layouts[0] if self.layout_choice == "AUTO" else next(
                layout for layout in layouts if layout.key == self.layout_choice)
            wm.progress_begin(0, len(chosen.parts))
            started = True
            collection, warnings = import_track(folder, chosen,
                progress=lambda index, _total, name: (wm.progress_update(index),
                    print(f"Track import {index + 1}/{len(chosen.parts)}: {name}", flush=True)))
        except (OSError, ValueError, RuntimeError, StopIteration) as exc:
            self.report({"ERROR"}, f"Track import failed: {exc}")
            return {"CANCELLED"}
        finally:
            if started:
                wm.progress_end()
        for warning in warnings:
            print("Assetto Corsa track warning:", warning)
        self.report({"INFO"}, f"Imported {collection.name}: {len(chosen.parts)} visual KN5 files")
        return {"FINISHED"}


class OBJECT_OT_ac_apply_skin(bpy.types.Operator):
    bl_idname = "object.ac_apply_skin"
    bl_label = "Apply Skin"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        collection = _skin_target(context, self.collection_name)
        if collection is None:
            return {"CANCELLED"}
        try:
            skin = collection.ac_skin_choice
            discovered = car_skins(bpy.path.abspath(collection.get("ac_source_folder", "")))
            if discovered:
                collection["ac_skin_paths"] = {key: str(path) for key, _, path in discovered}
            count, warnings = apply_skin(collection, skin)
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for warning in warnings:
            print("Assetto Corsa skin warning:", warning)
        self.report({"INFO"}, f"Applied {skin}: {count} texture overrides")
        return {"FINISHED"}


class OBJECT_OT_ac_reload_skin(bpy.types.Operator):
    bl_idname = "object.ac_reload_skin"
    bl_label = "Reload Skin"
    bl_options = {"REGISTER", "UNDO"}

    collection_name: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        collection = _skin_target(context, self.collection_name)
        if collection is None:
            return {"CANCELLED"}
        try:
            count, warnings = apply_skin(collection, collection.get("ac_active_skin", "BASE"), reload=True)
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        for warning in warnings:
            print("Assetto Corsa skin warning:", warning)
        self.report({"INFO"}, f"Reloaded active skin: {count} texture overrides")
        return {"FINISHED"}


class OBJECT_OT_ac_toggle_hierarchy(bpy.types.Operator):
    bl_idname = "object.ac_toggle_hierarchy"
    bl_label = "Show/Hide KN5 Hierarchy"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        collection = _selected_asset(context)
        if collection is None:
            return {"CANCELLED"}
        hierarchy = next((child for child in collection.children
                          if child.get("kn5_collection_role") == "KN5_HIERARCHY"), None)
        if hierarchy is None:
            self.report({"ERROR"}, "No KN5 hierarchy found")
            return {"CANCELLED"}
        hierarchy.hide_viewport = not hierarchy.hide_viewport
        return {"FINISHED"}


class VIEW3D_PT_assetto_corsa(bpy.types.Panel):
    bl_label = "Assetto Corsa"
    bl_idname = "VIEW3D_PT_assetto_corsa"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Assetto Corsa"

    def draw(self, context):
        layout = self.layout
        imports = layout.box()
        imports.label(text="Import")
        imports.operator("import_scene.assetto_corsa_kn5", text="KN5 File")
        imports.operator(IMPORT_SCENE_OT_assetto_corsa_car.bl_idname, text="Car Folder")
        imports.operator(IMPORT_SCENE_OT_assetto_corsa_track.bl_idname, text="Track Folder")
        collection = _selected_asset(context)
        if collection is None:
            layout.label(text="Select an imported Assetto Corsa object")
            return

        kind = collection.get("ac_kind", "KN5")
        asset = layout.box()
        asset.label(text="Imported Asset")
        asset.label(text=collection.name)
        asset.label(text=f"Type: {kind.title()}")
        if collection.get("ac_source_folder"):
            asset.label(text=f"Source: {collection['ac_source_folder']}")

        if kind == "CAR":
            layout.prop(context.scene, "ac_car_choice", text="Car")
            car = layout.box()
            car.label(text="Car")
            car.label(text=f"KN5: {Path(collection['ac_source_kn5']).name}")
            car.label(text=f"LOD: {collection.get('ac_lod', 'Main')}")
            skins = layout.box()
            skins.label(text="Skins")
            skins.prop(collection, "ac_skin_choice", text="Skin")
            row = skins.row(align=True)
            row.operator(OBJECT_OT_ac_apply_skin.bl_idname).collection_name = collection.name
            row.operator(OBJECT_OT_ac_reload_skin.bl_idname).collection_name = collection.name
            skins.label(text=f"Active: {collection.get('ac_active_skin', 'BASE')}")
        elif kind == "TRACK":
            asset.label(text=f"Layout: {collection.get('ac_layout', 'Default')}")

        if kind != "TRACK":
            organization = layout.box()
            organization.label(text="Organization")
            organization.operator("object.organize_imported_kn5")
        hierarchy = next((child for child in collection.children
                          if child.get("kn5_collection_role") == "KN5_HIERARCHY"), None)
        if hierarchy:
            box = layout.box()
            box.label(text="Hierarchy")
            box.operator(OBJECT_OT_ac_toggle_hierarchy.bl_idname,
                         text="Show KN5 Hierarchy" if hierarchy.hide_viewport else "Hide KN5 Hierarchy")


def _menu(self, _context):
    self.layout.operator(IMPORT_SCENE_OT_assetto_corsa_car.bl_idname, text="Assetto Corsa Car")
    self.layout.operator(IMPORT_SCENE_OT_assetto_corsa_track.bl_idname, text="Assetto Corsa Track")


_CLASSES = (IMPORT_SCENE_OT_assetto_corsa_car, IMPORT_SCENE_OT_assetto_corsa_track,
            OBJECT_OT_ac_apply_skin, OBJECT_OT_ac_reload_skin,
            OBJECT_OT_ac_toggle_hierarchy, VIEW3D_PT_assetto_corsa)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ac_car_choice = EnumProperty(
        name="Car", items=_car_items, get=_get_car_choice, set=_set_car_choice)
    bpy.types.Collection.ac_skin_choice = EnumProperty(
        name="Skin", items=_skin_items, get=_get_skin_choice, set=_set_skin_choice)
    bpy.types.TOPBAR_MT_file_import.append(_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    del bpy.types.Collection.ac_skin_choice
    del bpy.types.Scene.ac_car_choice
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _enum_cache.clear()
