"""Track-specific scene organization built on the existing KN5 importer."""

import json
import math
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

from .classification import TRACK_CATEGORIES, classify_track
from .kn5 import parse
from .organize import _assigned_material, _assigned_material_name, _child, _clean, _move
from .scene import build, import_transaction

def _model_transform(anchor, part):
    if part.position == (0.0, 0.0, 0.0) and part.rotation == (0.0, 0.0, 0.0):
        return
    source = Matrix.Translation(Vector(part.position)) @ Euler(
        tuple(math.radians(value) for value in part.rotation), "XYZ").to_matrix().to_4x4()
    anchor.matrix_world = Matrix.Rotation(math.pi / 2, 4, "X") @ source


def _move_part(top, source, part):
    hierarchy = None
    for obj in list(source.all_objects):
        if obj.type == "EMPTY":
            hierarchy = hierarchy or _child(top, "KN5_HIERARCHY")
            _move(obj, hierarchy)
        elif obj.type == "MESH":
            original = obj.get("kn5_original_name", obj.name)
            material = _assigned_material_name(obj)
            ancestors = json.loads(obj.get("kn5_parent_path", "[]"))
            mat = _assigned_material(obj)
            textures = json.loads(mat.get("kn5_textures", "{}")) if mat else {}
            category, evidence = classify_track(
                original, original, ancestors, material,
                mat.get("kn5_shader", "") if mat else "", textures.values(),
                part.path.name)
            _move(obj, _child(top, category))
            obj["ac_category"] = category
            obj["ac_classification_evidence"] = evidence
            obj["ac_source_kn5"] = part.path.name
            obj.name = _clean(original)
    if hierarchy:
        hierarchy.hide_viewport = True
    for child in list(source.children):
        if not child.all_objects and not child.children:
            bpy.data.collections.remove(child)
    bpy.data.collections.remove(source)


def import_track(folder, layout, *, progress=None):
    """Import all visual MODEL entries of one layout as one organized track."""
    folder = Path(folder).resolve()
    warnings = set()
    with import_transaction():
        top = bpy.data.collections.new(folder.name.upper())
        bpy.context.scene.collection.children.link(top)
        for index, part in enumerate(layout.parts):
            if progress:
                progress(index, len(layout.parts), part.path.name)
            source, part_warnings = build(parse(part.path), part.path,
                                          organize_meshes=False, clean_mesh_names=False)
            warnings.update(part_warnings)
            anchor = next((obj for obj in source.all_objects if obj.get("kn5_import_root")), None)
            if anchor is None:
                raise RuntimeError(f"Missing KN5 root in {part.path.name}")
            _model_transform(anchor, part)
            _move_part(top, source, part)
        top["ac_kind"] = "TRACK"
        top["ac_source_folder"] = str(folder)
        top["ac_layout"] = layout.key
        top["ac_source_kn5s"] = json.dumps([part.path.name for part in layout.parts])
        if progress:
            progress(len(layout.parts), len(layout.parts), "Complete")
        return top, tuple(sorted(warnings))
