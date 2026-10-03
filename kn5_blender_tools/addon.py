"""Blender operator and menu registration."""

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .kn5 import KN5Error, parse
from .organize import find_import_collection, organize_collection
from .scene import build
from . import ac_ui


class IMPORT_SCENE_OT_assetto_corsa_kn5(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.assetto_corsa_kn5"
    bl_label = "Import Assetto Corsa KN5"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".kn5"
    filter_glob: StringProperty(default="*.kn5", options={"HIDDEN"})
    import_textures: BoolProperty(name="Import Textures", default=True)
    import_materials: BoolProperty(name="Import Materials", default=True)
    import_hidden: BoolProperty(name="Import Hidden / LOD Nodes", default=False)
    scale: FloatProperty(name="Scale", default=1.0, min=0.0001, max=1000.0)
    organize_meshes: BoolProperty(name="Organize Meshes", default=True)
    clean_mesh_names: BoolProperty(name="Clean Mesh Names", default=True)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "import_materials")
        row = layout.row()
        row.enabled = self.import_materials
        row.prop(self, "import_textures")
        layout.prop(self, "import_hidden")
        layout.prop(self, "scale")
        layout.separator()
        layout.prop(self, "organize_meshes")
        layout.prop(self, "clean_mesh_names")

    def execute(self, context):
        try:
            model = parse(self.filepath)
            root, warnings = build(
                model, self.filepath,
                import_materials=self.import_materials,
                import_textures=self.import_textures,
                import_hidden=self.import_hidden,
                scale=self.scale,
                organize_meshes=self.organize_meshes,
                clean_mesh_names=self.clean_mesh_names,
            )
        except Exception as exc:
            if not isinstance(exc, (KN5Error, OSError, ValueError, RuntimeError)):
                import traceback
                traceback.print_exc()
            self.report({"ERROR"}, f"KN5 import failed: {exc}")
            return {"CANCELLED"}
        for warning in warnings:
            print("KN5 importer warning:", warning)
        if warnings:
            self.report({"WARNING"}, f"Imported {root.name} with {len(warnings)} warning(s); see console")
        else:
            self.report({"INFO"}, f"Imported {root.name}")
        return {"FINISHED"}


class OBJECT_OT_organize_imported_kn5(bpy.types.Operator):
    bl_idname = "object.organize_imported_kn5"
    bl_label = "Organize Imported KN5"
    bl_description = "Organize an imported KN5 using its object, material and parent names"
    bl_options = {"REGISTER", "UNDO"}

    organize_meshes: BoolProperty(name="Organize Meshes", default=True)
    clean_mesh_names: BoolProperty(name="Clean Mesh Names", default=True)

    def execute(self, context):
        collection = find_import_collection(context)
        if collection is None:
            self.report({"ERROR"}, "Select a mesh from the KN5 model to organize")
            return {"CANCELLED"}
        try:
            counts = organize_collection(collection, organize_meshes=self.organize_meshes,
                                         clean_names=self.clean_mesh_names)
        except Exception as exc:
            self.report({"ERROR"}, f"KN5 organization failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Organized {sum(counts.values())} KN5 meshes")
        return {"FINISHED"}


def _menu(self, context):
    self.layout.operator(IMPORT_SCENE_OT_assetto_corsa_kn5.bl_idname, text="Assetto Corsa (.kn5)")


def register():
    bpy.utils.register_class(IMPORT_SCENE_OT_assetto_corsa_kn5)
    bpy.utils.register_class(OBJECT_OT_organize_imported_kn5)
    bpy.types.TOPBAR_MT_file_import.append(_menu)
    ac_ui.register()


def unregister():
    ac_ui.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    bpy.utils.unregister_class(OBJECT_OT_organize_imported_kn5)
    bpy.utils.unregister_class(IMPORT_SCENE_OT_assetto_corsa_kn5)
